"""
FastAPI service: ingestion boundary, async run submission, polling, run traces, feedback.

Why async submit-and-poll (A4): an agent run takes tens of seconds (several LLM calls).
Holding an HTTP request open that long ties up connections, breaks behind proxies with
30-60 s idle timeouts, and loses the work if the client disconnects. So POST returns a
run id immediately (202) and the run goes onto a Redis queue; the caller polls
GET /v1/screenings/{run_id}. Polling was chosen over callbacks because callers (the web
client, Locust, curl) need no public endpoint of their own. The queue decouples
submission from execution, so workers scale independently and a burst waits in the
queue instead of overloading the provider.
"""
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from agent import chaos
from agent.config import settings
from agent.redis_client import get_redis
from api.contract import CONTRACT_VERSION, FeedbackSubmission, ScreeningSubmission
from api.metrics import FEEDBACK_TOTAL, HTTP_REQUEST_SECONDS, QUARANTINE_RECORDS_TOTAL, REQUESTS_TOTAL
from api.quarantine import quarantine_store
from api.storage import FeedbackRecord, RunRecord, storage
from api.worker import BREAKERS_KEY, enqueue, execute_run
from observability.logs import correlation_id_var, log_event, run_id_var, setup_logging
from observability.tracing import get_tracer, inject_context, setup_tracing


setup_logging("api")
setup_tracing("api")
logger = logging.getLogger("eia.api")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_FILE = ROOT / "frontend" / "index.html"
CORRELATION_HEADER = "X-Correlation-ID"
CLIENT_HEADER = "X-Client-ID"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Without Redis, runs execute inside this process: load the index before the first request
    if get_redis() is None:
        import asyncio
        from agent.retrieval.store import warm_up
        try:
            seconds = await asyncio.to_thread(warm_up)
            log_event(logger, "index warm (local mode)", seconds=round(seconds, 2))
        except Exception as error:
            log_event(logger, "index not available", level=logging.ERROR, error=str(error))
    yield


app = FastAPI(
    title="EIA Clearance Pre-Screening Service",
    description=(
        "Screening opinion (not a clearance decision) on whether a project needs prior environmental "
        "clearance under the EIA Notification 2006, and at which level, with cited provisions."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,health")
except Exception:  # pragma: no cover
    pass


def _index_version() -> str:
    manifest = settings.index_dir / "manifest.json"
    if manifest.exists():
        return f"{json.loads(manifest.read_text()).get('built_at_unix', 0):.0f}"
    return "none"


def _client_id(request: Request) -> str:
    supplied = request.headers.get(CLIENT_HEADER, "")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", supplied):
        return supplied
    return request.client.host if request.client else "unknown"


# -------------------------------------------------------------
# Correlation id + HTTP metrics
# -------------------------------------------------------------
@app.middleware("http")
async def correlation_and_metrics(request: Request, call_next):
    supplied = request.headers.get(CORRELATION_HEADER, "")
    correlation_id = supplied if re.fullmatch(r"[A-Za-z0-9_.-]{6,64}", supplied) else f"corr_{uuid.uuid4().hex[:12]}"
    request.state.correlation_id = correlation_id
    correlation_id_var.set(correlation_id)
    run_id_var.set(None)

    started = time.time()
    response = await call_next(request)
    route = request.scope.get("route")
    HTTP_REQUEST_SECONDS.labels(
        method=request.method,
        route=getattr(route, "path", "unmatched"),
        status_class=f"{response.status_code // 100}xx",
    ).observe(time.time() - started)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response


# -------------------------------------------------------------
# Rate limiting per client (D7): a cost control on submissions only
# -------------------------------------------------------------
_local_windows: Dict[str, int] = {}


def _rate_limited(client: str) -> int:
    """Fixed one-minute window per client, shared by API replicas through Redis. Returns retry-after seconds or 0."""
    window = int(time.time() // 60)
    key = f"eia:ratelimit:{client}:{window}"
    redis = get_redis()
    if redis is not None:
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, 70)
    else:
        _local_windows[key] = _local_windows.get(key, 0) + 1
        count = _local_windows[key]
    if count > settings.rate_limit_per_minute:
        return 60 - int(time.time() % 60)
    return 0


# -------------------------------------------------------------
# F2 / D1: Quarantine at the ingestion boundary
# -------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Any schema, type, range, categorical or cross-field violation is quarantined; no run starts."""
    raw_payload: Any = None
    try:
        raw_payload = json.loads(await request.body() or b"null")
    except Exception:
        raw_payload = {"unparseable_body": True}

    quarantine_id = f"quar_{uuid.uuid4().hex[:8]}"
    field_errors = [
        {"loc": [str(x) for x in err.get("loc", [])], "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    quarantine_store.record_quarantine(
        quarantine_id=quarantine_id,
        payload=raw_payload,
        field_errors=field_errors,
        client_ip=_client_id(request),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    QUARANTINE_RECORDS_TOTAL.inc()
    REQUESTS_TOTAL.labels(status="quarantined").inc()
    log_event(logger, "payload quarantined", level=logging.WARNING, quarantine_id=quarantine_id, errors=field_errors)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "quarantine_id": quarantine_id,
            "agent_started": False,
            "message": "Submission rejected and quarantined at the ingestion boundary. No agent run was started.",
            "detail": field_errors,
        },
    )


# -------------------------------------------------------------
# Web client (A8)
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend():
    return HTMLResponse(FRONTEND_FILE.read_text(encoding="utf-8"))


# -------------------------------------------------------------
# F1 / A4: Submit
# -------------------------------------------------------------
@app.post("/v1/screenings", status_code=status.HTTP_202_ACCEPTED)
async def submit_screening(submission: ScreeningSubmission, request: Request, background_tasks: BackgroundTasks):
    client = _client_id(request)
    retry_after = _rate_limited(client)
    if retry_after:
        REQUESTS_TOTAL.labels(status="rate_limited").inc()
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            content={"detail": f"Rate limit of {settings.rate_limit_per_minute} submissions per minute exceeded for client '{client}'."},
        )

    payload = submission.model_dump(exclude_none=True)
    cache_key = storage.compute_cache_key(payload, settings.prompt_version, _index_version())
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    correlation_id = request.state.correlation_id
    run_id_var.set(run_id)

    record = RunRecord(
        run_id=run_id,
        correlation_id=correlation_id,
        client_id=client,
        request_payload={**payload, "_cache_key": cache_key},
        prompt_version=settings.prompt_version,
    )

    # D7: whole-run cache. Same inputs + same prompt version + same index -> same result.
    cached_run_id = storage.cache_get(cache_key)
    cached = storage.get_run(cached_run_id) if cached_run_id else None
    if cached is not None and cached.status in ("answered", "escalated"):
        now = time.time()
        for field in ("status", "category", "route", "schedule_item", "basis", "citations", "verification",
                      "escalation", "disclaimer", "prompt_hashes"):
            setattr(record, field, getattr(cached, field))
        record.mode = cached.mode
        record.from_cache = True
        record.cached_from_run = cached.run_id
        record.started_at = record.completed_at = now
        record.latency_seconds = round(now - record.submitted_at, 4)
        storage.create_run(record)
        storage.append_event(run_id, {"ts": now, "kind": "cache_hit", "agent": "api", "cached_from_run": cached.run_id})
        REQUESTS_TOTAL.labels(status="cache_hit").inc()
        log_event(logger, "screening served from cache", cached_from_run=cached.run_id)
        return JSONResponse(status_code=202, content={
            "run_id": run_id, "correlation_id": correlation_id, "status": record.status,
            "from_cache": True, "poll_url": f"/v1/screenings/{run_id}",
        })

    storage.create_run(record)
    storage.append_event(run_id, {"ts": time.time(), "kind": "submitted", "agent": "api", "client_id": client})
    REQUESTS_TOTAL.labels(status="accepted").inc()

    with get_tracer().start_as_current_span("api.enqueue") as span:
        span.set_attribute("run.id", run_id)
        trace_context = inject_context()
        if not enqueue(run_id, trace_context):
            # Local single-process mode (no Redis): run in this process after responding
            background_tasks.add_task(execute_run, {"run_id": run_id, "trace": trace_context})

    log_event(logger, "screening accepted", project_name=submission.project_name, client_id=client)
    return JSONResponse(status_code=202, content={
        "run_id": run_id, "correlation_id": correlation_id, "status": "queued",
        "from_cache": False, "poll_url": f"/v1/screenings/{run_id}",
        "trace_url": f"/v1/screenings/{run_id}/trace",
    })


def _view(record: RunRecord) -> Dict[str, Any]:
    view: Dict[str, Any] = {
        "run_id": record.run_id,
        "correlation_id": record.correlation_id,
        "status": record.status,
        "mode": record.mode,
        "from_cache": record.from_cache,
        "submitted_at": record.submitted_at,
        "completed_at": record.completed_at,
        "latency_seconds": record.latency_seconds,
        "prompt_version": record.prompt_version,
        "metrics": {
            "steps": record.steps, "tool_calls": record.tool_calls, "llm_calls": record.llm_calls,
            "prompt_tokens": record.prompt_tokens, "completion_tokens": record.completion_tokens,
            "cost_usd": record.cost_usd,
        },
        "links": {"self": f"/v1/screenings/{record.run_id}", "trace": f"/v1/screenings/{record.run_id}/trace",
                  "feedback": f"/v1/screenings/{record.run_id}/feedback"},
    }
    if record.status == "answered":
        view["result"] = {
            "category": record.category, "route": record.route, "schedule_item": record.schedule_item,
            "basis": record.basis, "citations": record.citations, "verification": record.verification,
            "disclaimer": record.disclaimer,
        }
    elif record.status in ("escalated", "failed"):
        view["result"] = {"category": None, "route": "escalate_to_human", "basis": None,
                          "citations": record.citations, "verification": record.verification}
        view["escalation"] = record.escalation
        if record.provisional_opinion:
            view["provisional_opinion"] = {
                **record.provisional_opinion,
                "warning": "Rule-based fallback produced while the model provider was unavailable. Not a screening result.",
            }
    return view


@app.get("/v1/screenings/{run_id}")
async def get_screening(run_id: str):
    record = storage.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found.")
    return _view(record)


# -------------------------------------------------------------
# D5: Reconstruct a run from its id
# -------------------------------------------------------------
@app.get("/v1/screenings/{run_id}/trace")
async def get_screening_trace(run_id: str):
    record = storage.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found.")
    events = storage.get_events(run_id)

    per_agent: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if event.get("kind") not in ("llm_call", "tool_call"):
            continue
        totals = per_agent.setdefault(event.get("agent", "?"), {
            "llm_calls": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cost_usd": 0.0, "latency_ms": 0.0, "retries": 0,
        })
        totals["llm_calls" if event["kind"] == "llm_call" else "tool_calls"] += 1
        totals["prompt_tokens"] += event.get("prompt_tokens", 0) or 0
        totals["completion_tokens"] += event.get("completion_tokens", 0) or 0
        totals["cost_usd"] = round(totals["cost_usd"] + (event.get("cost_usd", 0) or 0), 6)
        totals["latency_ms"] = round(totals["latency_ms"] + (event.get("latency_ms", 0) or 0), 1)
        totals["retries"] += event.get("retries", 0) or 0

    jaeger = None
    if record.trace_id and settings.jaeger_ui_url:
        jaeger = f"{settings.jaeger_ui_url.rstrip('/')}/trace/{record.trace_id}"

    return {
        "run": _view(record),
        "request": {k: v for k, v in record.request_payload.items() if not k.startswith("_")},
        "prompt_version": record.prompt_version,
        "prompt_hashes": record.prompt_hashes,
        "trace_id": record.trace_id,
        "jaeger_url": jaeger,
        "verification": record.verification,
        "usage_by_step": record.usage_by_step,
        "per_agent": per_agent,
        "events": events,
    }


# -------------------------------------------------------------
# L6: Feedback
# -------------------------------------------------------------
@app.post("/v1/screenings/{run_id}/feedback")
async def record_feedback(run_id: str, feedback: FeedbackSubmission):
    record = storage.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found.")
    stored = storage.add_feedback(FeedbackRecord(
        feedback_id=f"fb_{uuid.uuid4().hex[:10]}",
        run_id=run_id,
        satisfactory=feedback.satisfactory,
        reason=feedback.reason,
        run_status=record.status,
        run_route=record.route,
        prompt_version=record.prompt_version,
    ))
    FEEDBACK_TOTAL.labels(satisfactory=str(feedback.satisfactory).lower()).inc()
    storage.append_event(run_id, {"ts": time.time(), "kind": "feedback", "agent": "caller", **stored.model_dump()})
    return {"status": "recorded", "feedback_id": stored.feedback_id, "run_id": run_id}


@app.get("/v1/feedback/summary")
async def feedback_summary():
    return storage.get_feedback_summary()


@app.get("/v1/quality")
async def live_quality(limit: int = 200):
    """Automatic scores of sampled live runs, newest last (L6)."""
    redis = get_redis()
    samples = [json.loads(raw) for raw in redis.lrange("eia:quality", -limit, -1)] if redis else []
    return {"count": len(samples), "samples": samples}


# -------------------------------------------------------------
# D1: Published contract, F2: quarantine inspection
# -------------------------------------------------------------
@app.get("/v1/contract")
async def published_contract():
    return {
        "version": CONTRACT_VERSION,
        "screening_submission": ScreeningSubmission.model_json_schema(),
        "feedback_submission": FeedbackSubmission.model_json_schema(),
    }


@app.get("/v1/quarantine")
async def list_quarantine_records(limit: int = 20):
    return quarantine_store.get_records(limit=limit)


# -------------------------------------------------------------
# A5 demonstration: provider outage on request
# -------------------------------------------------------------
@app.post("/admin/chaos")
async def set_chaos(payload: Dict[str, Any]):
    chaos.set_llm_down(bool(payload.get("llm_down")))
    log_event(logger, "chaos switch changed", level=logging.WARNING, llm_down=chaos.llm_down())
    return {"llm_down": chaos.llm_down()}


@app.get("/admin/breakers")
async def breaker_states():
    redis = get_redis()
    if redis is None:
        from agent.llm.gateway import get_gateway
        return {"local": get_gateway().breaker_states(), "llm_down": chaos.llm_down()}
    return {"workers": {k: json.loads(v) for k, v in redis.hgetall(BREAKERS_KEY).items()}, "llm_down": chaos.llm_down()}


# -------------------------------------------------------------
# F8: Health and metrics
# -------------------------------------------------------------
@app.get("/health")
async def health_check():
    manifest_file = settings.index_dir / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    redis = get_redis()
    redis_ok = False
    queue_depth = None
    if redis is not None:
        try:
            redis_ok = bool(redis.ping())
            queue_depth = redis.llen("eia:queue")
        except Exception:
            redis_ok = False
    healthy = bool(manifest) and (redis_ok or not settings.redis_url)
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "degraded",
            "service": "api",
            "index": {"built_at": manifest.get("built_at"), "chunks": manifest.get("chunk_count"),
                      "embedding_model": manifest.get("embedding_model")},
            "redis_connected": redis_ok,
            "mode": "distributed" if settings.redis_url else "local",
            "queue_depth": queue_depth,
            "llm_provider": settings.llm_provider,
            "prompt_version": settings.prompt_version,
            "llm_down_switch": chaos.llm_down(),
        },
    )


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
