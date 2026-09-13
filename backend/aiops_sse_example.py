"""
Example SSE endpoints for AI-ops streaming.
This module provides a lightweight example of a Server-Sent Events
(streaming) endpoint that emits routing/partial/final events the
frontend's aiops.js client listens for at /api/aiops/stream.

This example uses FastAPI; add it to your backend or run separately.
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json, asyncio

app = FastAPI()

def sse_encode(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

@app.get("/api/aiops/stream")
async def aiops_stream():
    async def event_generator():
        # initial routing snapshot
        routing = {
            "routing": {
                "winner": "deterministic",
                "confidence": 0.72,
                "ranking": [
                    {"provider": "gguf", "score": 0.38},
                    {"provider": "ollama", "score": 0.41},
                    {"provider": "deterministic", "score": 0.72}
                ]
            },
            "models": {"gguf": {"files": [], "engine": {"state": "unavailable"}}}
        }
        yield sse_encode('routing', routing)
        await asyncio.sleep(0.3)

        # emit a few partials (simulates a live model streaming output)
        for i in range(3):
            partial = {"text": f"partial line {i+1}", "model": "local-3b", "model_latency_ms": 30 + i*10}
            yield sse_encode('partial', partial)
            await asyncio.sleep(1.0)

        # final event
        final = {"text": "final consolidated answer", "result": "ok", "snapshot": {}}
        yield sse_encode('final', final)

    return StreamingResponse(event_generator(), media_type='text/event-stream')
