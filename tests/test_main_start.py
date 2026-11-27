"""Starting the app a second time opens the running copy instead of failing with 'port in use'."""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from shorts_studio.__main__ import _already_running


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(body: bytes) -> HTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_free_port_means_start_normally():
    assert _already_running(f"http://127.0.0.1:{free_port()}/") is None


def test_running_studio_is_detected():
    srv = serve(json.dumps({"ok": True, "version": "0.1.0"}).encode())
    try:
        assert _already_running(f"http://127.0.0.1:{srv.server_port}/") is True
    finally:
        srv.shutdown()


def test_another_program_on_the_port_is_reported():
    srv = serve(b"<html>not us</html>")
    try:
        assert _already_running(f"http://127.0.0.1:{srv.server_port}/") is False
    finally:
        srv.shutdown()
