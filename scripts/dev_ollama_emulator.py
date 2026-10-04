"""Wire-accurate Ollama API emulator for integration testing.

Implements the exact endpoints and JSON shapes of Ollama v0.35 that the
Vortex sidecar uses: /api/tags, /api/ps, /api/generate (warm-up idiom),
/api/chat (stream:false). The only non-real part is the reply text itself.
Knobs via env:
  EMU_MODELS      comma list of installed tags (default "qwen2.5:3b")
  EMU_TAGS_DELAY  seconds to stall /api/tags (simulates a hung daemon)
  EMU_LOAD_DELAY  seconds of cold-start delay on first generate/chat (default 1.5)
  EMU_CHAT_DELAY  seconds each /api/chat takes after load (simulates slow CPUs)
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = [m.strip() for m in os.environ.get("EMU_MODELS", "qwen2.5:3b").split(",") if m.strip()]
TAGS_DELAY = float(os.environ.get("EMU_TAGS_DELAY", "0"))
LOAD_DELAY = float(os.environ.get("EMU_LOAD_DELAY", "1.5"))
CHAT_DELAY = float(os.environ.get("EMU_CHAT_DELAY", "0"))

_loaded: set[str] = set()
_lock = threading.Lock()


def _model_entry(name: str) -> dict:
    return {
        "name": name, "model": name, "modified_at": "2026-10-03T12:00:00Z",
        "size": 1929912432, "digest": "a" * 64,
        "details": {"family": "qwen2", "parameter_size": "3.1B", "quantization_level": "Q4_K_M"},
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            if TAGS_DELAY:
                time.sleep(TAGS_DELAY)
            return self._json(200, {"models": [_model_entry(m) for m in MODELS]})
        if self.path.startswith("/api/ps"):
            with _lock:
                loaded = sorted(_loaded)
            return self._json(200, {"models": [_model_entry(m) for m in loaded]})
        if self.path.startswith("/api/version"):
            return self._json(200, {"version": "0.35.1-emulated"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})
        model = str(body.get("model") or "")
        if model not in MODELS:
            return self._json(404, {"error": f"model '{model}' not found, try pulling it first"})

        def ensure_loaded():
            with _lock:
                cold = model not in _loaded
            if cold:
                time.sleep(LOAD_DELAY)
                with _lock:
                    _loaded.add(model)

        if self.path.startswith("/api/generate"):
            ensure_loaded()
            return self._json(200, {
                "model": model, "created_at": "2026-10-03T12:00:00Z",
                "response": "", "done": True, "done_reason": "load",
            })
        if self.path.startswith("/api/chat"):
            ensure_loaded()
            if CHAT_DELAY:
                time.sleep(CHAT_DELAY)
            user = next((m.get("content", "") for m in reversed(body.get("messages") or [])
                         if m.get("role") == "user"), "")
            reply = ("Hello! I'm Qwen 2.5, running locally through Ollama on your machine. "
                     "Nothing you say here leaves this computer. How can I help you today?")
            if "joke" in user.lower():
                reply = ("Why do programmers prefer dark mode? Because light attracts bugs.")
            return self._json(200, {
                "model": model, "created_at": "2026-10-03T12:00:00Z",
                "message": {"role": "assistant", "content": reply},
                "done": True, "done_reason": "stop",
                "total_duration": 1203456789, "eval_count": 38, "prompt_eval_count": 27,
            })
        return self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print("[emu]", fmt % args, flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 11434), Handler)
    print(f"[emu] serving on 127.0.0.1:11434 models={MODELS} tags_delay={TAGS_DELAY}", flush=True)
    server.serve_forever()
