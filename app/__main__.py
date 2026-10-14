import argparse
import threading
import webbrowser

import uvicorn

from .config import Config
from .main import create_app


def main():
    parser = argparse.ArgumentParser(description="Local inventory capture")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    cfg = Config.load()
    url = f"http://127.0.0.1:{cfg.port}"
    print(f"inv_flow · {cfg.mode.upper()} · {url}")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(cfg), host="127.0.0.1", port=cfg.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
