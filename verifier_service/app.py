"""
Verifier agent service (Requirement A2).

The Verifier runs in its own container with its own model budget, circuit breaker and
metrics. The Screener's worker hands off over HTTP: POST /v1/verify with the run state
(draft + every passage retrieved in the run); the response is the state with
`verification` set. Trace context arrives in the request headers, and trace events are
written to the same Redis run log, so the run stays one trace and one event history.

Deployment boundary justification: verification is on the critical path of every
answer and must not be skipped when the Screener's worker is busy or crashing; as a
separate service it fails independently (the worker escalates with VERIFIER_UNAVAILABLE),
scales independently, and can be released independently (e.g. a stricter verifier
prompt) without redeploying the Screener.
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from agent.agents.verifier import verify_draft
from agent.retrieval.store import get_store
from agent.state import AgentState
from api.storage import storage
from observability.logs import correlation_id_var, log_event, run_id_var, setup_logging
from observability.recorder import RunRecorder, set_recorder
from observability.tracing import extract_context, get_tracer, setup_tracing


setup_logging("verifier")
setup_tracing("verifier-agent")
logger = logging.getLogger("eia.verifier")

app = FastAPI(title="Verifier agent")


@app.post("/v1/verify")
async def verify(request: Request):
    body = await request.json()
    state = AgentState(**body)
    run_id_var.set(state.run_id)
    correlation_id_var.set(state.correlation_id)

    recorder = RunRecorder(state.run_id or "adhoc", state.correlation_id or "adhoc", sink=storage.append_event)
    set_recorder(recorder)

    started = time.time()
    with get_tracer().start_as_current_span("verifier.handle", context=extract_context(dict(request.headers))):
        import asyncio
        result = await asyncio.to_thread(_run, state, recorder)
    log_event(logger, "verification done", verdict=result.verification.verdict if result.verification else None,
              seconds=round(time.time() - started, 3))
    return result.model_dump(mode="json")


def _run(state: AgentState, recorder: RunRecorder) -> AgentState:
    set_recorder(recorder)
    return verify_draft(state)


@app.get("/health")
async def health():
    store = get_store()
    return {"status": "healthy", "service": "verifier", "index_chunks": len(store.raw)}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
