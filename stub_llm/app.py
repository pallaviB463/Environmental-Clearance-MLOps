"""
Stub LLM service: an OpenAI-compatible /v1/chat/completions endpoint that answers with
scripted responses after a realistic delay (Requirement D6).

Point the system at it with LLM_BASE_URL=http://llm-stub:8001/v1. Nothing else changes,
which is the point: the load test exercises the real agent loop, queue and verifier.

POST /admin/fault {"mode": "error503" | "timeout" | "ok"} makes it misbehave on request.
"""
import asyncio
import os
import random
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from agent.retrieval.store import get_store
from stub_llm import policy


DELAY_SECONDS = float(os.getenv("STUB_LLM_DELAY_SECONDS", "1.5"))

app = FastAPI(title="Stub LLM (OpenAI-compatible)")
state = {"mode": "ok"}

STUB_REQUESTS = Counter("stub_llm_requests_total", "Stub LLM requests", ["outcome"])
STUB_LATENCY = Histogram("stub_llm_latency_seconds", "Stub LLM response time",
                         buckets=[0.25, 0.5, 1, 1.5, 2, 3, 5, 10])


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    started = time.time()
    body = await request.json()

    if state["mode"] == "error503":
        STUB_REQUESTS.labels(outcome="error503").inc()
        return JSONResponse(status_code=503, content={"error": "stub fault injection: service unavailable"})
    if state["mode"] == "timeout":
        STUB_REQUESTS.labels(outcome="timeout").inc()
        await asyncio.sleep(600)

    # Simulated model latency without blocking the event loop
    await asyncio.sleep(DELAY_SECONDS * random.uniform(0.8, 1.2))
    message, prompt_tokens, completion_tokens = await asyncio.to_thread(
        policy.respond, body.get("messages", []), get_store(), body.get("tools"), body.get("tool_choice", "auto")
    )

    STUB_REQUESTS.labels(outcome="ok").inc()
    STUB_LATENCY.observe(time.time() - started)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "stub-model"),
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


@app.post("/admin/fault")
async def set_fault(payload: dict):
    state["mode"] = payload.get("mode", "ok")
    return {"mode": state["mode"]}


@app.get("/health")
async def health():
    return {"status": "healthy", "mode": state["mode"], "delay_seconds": DELAY_SECONDS}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
