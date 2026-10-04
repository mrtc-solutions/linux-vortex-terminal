"""Vercel serverless entrypoint for the Vortex WEB_CLOUD backend.

Every `/api/*` request is rewritten here (see vercel.json) and dispatched
to the shared stdlib-only router in `backend/webapi.py`. Credentials
(GEMINI_API_KEY_1/2/3, GROQ_API_KEY, OPENROUTER_API_KEY, FREE_ONLY_MODE, …)
are read from the server environment ONLY and are never echoed to the
browser — responses pass through the shared secret redaction.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_ROOT, "backend")
for entry in (_ROOT, _BACKEND):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# Serverless: writable scratch space only. Never the repo, never $HOME.
os.environ.setdefault("VORTEX_CONFIG_DIR", "/tmp/vortex")
os.environ.setdefault("VORTEX_RUNTIME", "WEB_CLOUD")

from webapi import handle_request  # noqa: E402


def _original_path(raw_path: str, headers) -> str:
    """The rewrite proxies the original URL through; fall back to headers
    if the platform ever hands us the destination path instead."""
    path = (raw_path or "/").split("?", 1)[0]
    if path.rstrip("/") in {"/api/index", "/api/index.py", ""}:
        for header in ("x-vercel-original-path", "x-original-path", "x-forwarded-uri"):
            candidate = headers.get(header) if headers else None
            if candidate:
                return str(candidate).split("?", 1)[0]
    return path


class handler(BaseHTTPRequestHandler):  # noqa: N801 (Vercel naming contract)
    protocol_version = "HTTP/1.1"

    def _client_ip(self) -> str:
        forwarded = self.headers.get("x-forwarded-for") or ""
        return forwarded.split(",")[0].strip() or (self.client_address[0] if self.client_address else "")

    def _dispatch(self, method: str) -> None:
        body = b""
        if method == "POST":
            try:
                length = int(self.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > 0:
                body = self.rfile.read(min(length, 128 * 1024))
        path = _original_path(self.path, self.headers)
        try:
            status, payload = handle_request(method, path, body, self._client_ip())
        except Exception:
            # Never leak internals (paths, env, tracebacks) to the browser.
            status, payload = 500, {"error": {"code": "internal",
                                              "message": "The Vortex web backend hit an unexpected error."}}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Vortex-Runtime", "WEB_CLOUD")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, *_args) -> None:  # no request logging of user content
        return
