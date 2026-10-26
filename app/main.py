import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Config
from .capture import CaptureAssistance
from .demo import DemoService
from .inventory import Inventory
from .recovery import Journal
from .sheets import Problem, Sheets, google_service, connection_error


def create_app(config=None, service=None, capture=None):
    cfg = config or Config.load()
    token = secrets.token_urlsafe(32)
    assistance = capture or CaptureAssistance(cfg)
    state = cfg.state_dir / cfg.mode
    state.mkdir(parents=True, exist_ok=True)
    instance_lock = FileLock(state / "instance.lock")

    @asynccontextmanager
    async def lifespan(app):
        try:
            instance_lock.acquire(timeout=0)
        except Timeout:
            raise RuntimeError("Another inv_flow instance is using this state directory. Close it first.") from None
        try:
            journal = Journal(state / "requests.sqlite", cfg.identity)
            client = service or (DemoService(cfg, state / "demo-workbook.json") if cfg.mode == "demo" else google_service(cfg))
            app.state.inventory = Inventory(Sheets(client, cfg), journal, cfg)
            app.state.inventory.recover()
            yield
        finally:
            instance_lock.release()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            allowed = {f"http://127.0.0.1:{cfg.port}", f"http://localhost:{cfg.port}"}
            if origin not in allowed or not secrets.compare_digest(request.headers.get("x-session-token", ""), token):
                return JSONResponse({"error": "Local session expired or request origin is not allowed. Reload the app."}, 403)
            if len(await request.body()) > 65536:
                return JSONResponse({"error": "Request is too large."}, 413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected_handler(request, exc):
        return JSONResponse({"error": "Connection or local storage is unavailable. Your basket is retained. Check configuration and recovery before continuing."}, status_code=503)

    @app.get("/api/status")
    def status(request: Request, request_id: str = ""):
        inv = request.app.state.inventory
        base = dict(mode=cfg.mode, identity=cfg.identity, device=cfg.device, token=token,
                    voice_available=bool(cfg.openai_api_key))
        try:
            base.update(inv.status())
            base["connected"] = True
        except Exception as exc:
            base.update(connected=False, products=[], recent=inv.journal.recent(), pending=inv.pending(),
                        error=connection_error(exc))
        if request_id:
            record = inv.journal.get(request_id)
            import json
            base["request"] = {"state": record["state"], "receipt": json.loads(record["receipt"]) if record["receipt"] else None} if record else {"state": "unknown"}
        return base

    @app.post("/api/withdrawals")
    def submit(request: Request, body: dict):
        return request.app.state.inventory.submit(body)

    @app.post("/api/recovery")
    def recover(request: Request):
        return {"pending": request.app.state.inventory.recover()}

    @app.post("/api/receiving")
    def receive(request: Request, body: dict):
        return request.app.state.inventory.submit(body, "receiving")

    async def capture_catalog(request):
        from starlette.concurrency import run_in_threadpool
        status = await run_in_threadpool(request.app.state.inventory.status)
        if status["pending"]:
            raise Problem("Capture paused until recovery is verified.", 409)
        return {p["id"]: p for p in status["products"]}

    @app.post("/api/capture/lookup")
    async def lookup(request: Request, body: dict):
        return await assistance.lookup(body, await capture_catalog(request))

    @app.post("/api/capture/voice")
    async def voice(request: Request, body: dict):
        return await assistance.interpret(body, await capture_catalog(request))

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
