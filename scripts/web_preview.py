#!/usr/bin/env python3
"""Local simulation of the Vercel deployment (WEB_CLOUD runtime).

Serves the built single-file UI from dist/ and routes every /api/* request
through backend/webapi.py — the same router the Vercel Python function
uses. This is for development/verification of Web Mode without deploying:

    npm run build
    python3 scripts/web_preview.py --host 0.0.0.0 --port 3000

Cloud keys are read from the environment / .env exactly like production
(server-side only; never sent to the browser).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("VORTEX_RUNTIME", "WEB_CLOUD")
os.environ.setdefault("VORTEX_CONFIG_DIR", "/tmp/vortex-web-preview")

from webapi import handle_request  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _api(self, method: str) -> None:
        body = b""
        if method == "POST":
            try:
                length = int(self.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length:
                body = self.rfile.read(min(length, 128 * 1024))
        client = self.client_address[0] if self.client_address else ""
        status, payload = handle_request(method, self.path, body, client)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Vortex-Runtime", "WEB_CLOUD")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            return self._api("GET")
        index = ROOT / "dist" / "index.html"
        if not index.is_file():
            message = b"dist/index.html missing - run: npm run build"
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
            return
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            return self._api("POST")
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[web-preview] %s\n" % (fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="Vortex Web Mode local preview")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    options = parser.parse_args()
    server = ThreadingHTTPServer((options.host, options.port), Handler)
    print(json.dumps({"web_preview": "online", "host": options.host,
                      "port": options.port, "runtime": "WEB_CLOUD"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
