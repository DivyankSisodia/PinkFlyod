"""Start Shorts Studio: ``python -m shorts_studio`` (opens your browser when the server is ready)."""
from __future__ import annotations

import argparse
import logging
import threading
import time
import urllib.request
import webbrowser

from .config import load_settings


def _open_when_ready(url: str) -> None:
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.2)


def _already_running(url: str) -> bool | None:
    """None: the port is free. True: Shorts Studio answers there. False: something else holds the port."""
    import json
    import socket
    from urllib.parse import urlparse
    u = urlparse(url)
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex((u.hostname, u.port)) != 0:
            return None
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as r:
            return json.loads(r.read()).get("ok") is True
    except (OSError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(prog="shorts-studio")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    parser.add_argument("--port", type=int, help="port to listen on (default 17860)")
    args = parser.parse_args()

    import os
    if args.port:
        os.environ["SHORTS_STUDIO_PORT"] = str(args.port)
    settings = load_settings()
    if settings.host not in ("127.0.0.1", "localhost"):
        print(f"Warning: listening on {settings.host}; other devices on your network can reach Shorts Studio.")

    settings.ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(settings.logs_dir / "studio.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    import uvicorn

    from .app import create_app
    url = f"http://127.0.0.1:{settings.port}/"
    running = _already_running(url)
    if running is not None:
        if running:
            print(f"Shorts Studio is already running at {url}" + ("" if args.no_browser else "; opening it."))
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise SystemExit(f"Port {settings.port} is used by another program. Close it, or start Shorts Studio on "
                         f"another port: python -m shorts_studio --port {settings.port + 10}")
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    print(f"Shorts Studio {url}  (data: {settings.data_dir})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
