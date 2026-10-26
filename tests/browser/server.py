"""Isolated demo server for browser acceptance; all external providers are fixtures."""
import asyncio
import json
import tempfile
import os
from pathlib import Path

import httpx
import uvicorn

from app.capture import CaptureAssistance
from app.config import Config
from app.demo import DemoService
from app.main import create_app


async def provider(request):
    if request.url.host == "api.upcitemdb.com":
        upc = request.url.params["upc"]
        if upc == "001234567890":
            return httpx.Response(200, json=dict(code="OK", items=[dict(upc=upc, title="New demo drink", size="12 oz bottle")]))
        return httpx.Response(429)
    context = json.loads(json.loads(request.content)["input"])
    command = context["transcript"]
    if command == "quota":
        return httpx.Response(429, json={"error":{"code":"insufficient_quota", "message":"fixture quota exhausted"}})
    result = dict(status="ready", movement_type=context["movement_type"], question="", candidate_ids=[], actions=[])
    def edit(op, pid, quantity):
        return dict(action=op, product_id=pid, quantity=quantity)
    if command == "two drinks": result["actions"] = [edit("add", "sapporo", 2), edit("add", "tepache", 3)]
    if command == "set three": result["actions"] = [edit("set", "sapporo", 3)]
    if command == "remove": result["actions"] = [edit("remove", "tepache", 0)]
    if command == "cancel": result["actions"] = [edit("cancel", "", 0)]
    if command == "slow":
        await asyncio.sleep(1)
        result["actions"] = [edit("add", "sapporo", 10)]
    if command == "ambiguous":
        result.update(status="clarify", question="Which second drink?", candidate_ids=["tepache", "perrier"], actions=[edit("add", "sapporo", 2)])
        if context.get("clarification"):
            result.update(status="ready", question="", candidate_ids=[], actions=[edit("add", "sapporo", 2), edit("add", "tepache", 1)])
    return httpx.Response(200, json=dict(status="completed", output=[dict(type="message", content=[dict(type="output_text", text=json.dumps(result))])], usage=dict(input_tokens=100, output_tokens=100)))


if __name__ == "__main__":
    Path("artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capture-browser-", dir="artifacts") as directory:
        cfg = Config(port=int(os.environ.get("INV_BROWSER_TEST_PORT", "8882")), state_dir=Path(directory), openai_api_key="fixture-only")
        app = create_app(cfg, DemoService(cfg), CaptureAssistance(cfg, httpx.MockTransport(provider)))
        uvicorn.run(app, host="127.0.0.1", port=cfg.port, access_log=False)
