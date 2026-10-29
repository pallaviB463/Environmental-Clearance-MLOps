import os
import time
import uuid
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.contract import (
    ScreeningSubmission,
    FeedbackSubmission,
    VALID_SECTORS,
    VALID_PROXIMITY_FEATURES
)
from api.quarantine import quarantine_store
from api.storage import storage
from api.worker import execute_agent_run, get_redis_client
from api.metrics import (
    REQUESTS_TOTAL,
    QUARANTINE_RECORDS_TOTAL,
    CORPUS_CHUNKS_COUNT,
    CORPUS_FRESHNESS_TIMESTAMP
)
from agent.config import settings

# Configure structured logging (Requirement F8 / D5)
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "module":"%(name)s", "message":"%(message)s"}'
)
logger = logging.getLogger("eia_service")

app = FastAPI(
    title="EIA Clearance Pre-Screening Service",
    description="Statutory environmental clearance screening and categorisation engine under EIA Notification 2006 (Consolidated)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

DATA_CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus_chunks.json"
FRONTEND_FILE = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# In-memory rate limiting (Requirement D7: max 60 requests/minute per client IP)
RATE_LIMIT_STORE: Dict[str, list] = {}
RATE_LIMIT_WINDOW = 60.0
MAX_REQUESTS_PER_WINDOW = 60


# -------------------------------------------------------------
# F2 / D1: Custom Ingestion Quarantine Exception Handler
# -------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Catches any schema, range, categorical, or unexpected field violations.
    Isolates the malformed payload in the quarantine repository with HTTP 422.
    Ensures zero agent runs are started (Requirement F2, Demo Item 4).
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    raw_payload = {}
    try:
        raw_payload = await request.json()
    except Exception:
        pass

    qid = f"quar_{uuid.uuid4().hex[:8]}"
    field_errors = []
    for err in exc.errors():
        field_errors.append({
            "loc": [str(x) for x in err.get("loc", [])],
            "msg": err.get("msg", ""),
            "type": err.get("type", "")
        })

    quarantine_store.record_quarantine(
        quarantine_id=qid,
        payload=raw_payload,
        field_errors=field_errors,
        client_ip=client_ip
    )
    QUARANTINE_RECORDS_TOTAL.inc()
    REQUESTS_TOTAL.labels(status="quarantined").inc()

    logger.warning(json.dumps({
        "event": "payload_quarantined",
        "quarantine_id": qid,
        "client_ip": client_ip,
        "errors": field_errors
    }))

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "quarantine_id": qid,
            "message": "Submission rejected and quarantined at ingestion boundary. No agent run started.",
            "detail": field_errors
        }
    )


# -------------------------------------------------------------
# Rate Limiting Middleware (Requirement D7)
# -------------------------------------------------------------
@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()

    # Clean old requests
    history = RATE_LIMIT_STORE.get(client_ip, [])
    history = [t for t in history if now - t < RATE_LIMIT_WINDOW]

    if len(history) >= MAX_REQUESTS_PER_WINDOW:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded (max 60 submissions per minute)."}
        )

    history.append(now)
    RATE_LIMIT_STORE[client_ip] = history

    response = await call_next(request)
    return response


# -------------------------------------------------------------
# Web UI Endpoint (Requirement A8)
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    if FRONTEND_FILE.exists():
        with open(FRONTEND_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>EIA Clearance Pre-Screening Service Active</h2>")


# -------------------------------------------------------------
# F1, F2, D1, A4: Screening Ingestion Boundary
# -------------------------------------------------------------
@app.post("/v1/screenings", status_code=status.HTTP_202_ACCEPTED)
async def submit_screening(
    submission: ScreeningSubmission,
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Published Screening Interface (F1, D1):
    Enforces schema, range, categorical and cross-field validation.
    Dispatches task asynchronously via Redis queue (A4, A7) with fallback background execution.
    """
    raw_body = submission.model_dump()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    correlation_id = f"corr_{uuid.uuid4().hex[:8]}"

    storage.create_run(
        run_id=run_id,
        correlation_id=correlation_id,
        payload=raw_body
    )
    REQUESTS_TOTAL.labels(status="accepted").inc()

    logger.info(json.dumps({
        "event": "screening_accepted",
        "run_id": run_id,
        "correlation_id": correlation_id,
        "project_name": submission.project_name
    }))

    # Dispatch to Redis queue if Redis is running, otherwise run background task
    dispatched_to_redis = False
    rc = get_redis_client()
    if rc:
        try:
            rc.lpush("eia_screening_queue", run_id)
            dispatched_to_redis = True
        except Exception:
            pass

    if not dispatched_to_redis:
        background_tasks.add_task(execute_agent_run, run_id)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "run_id": run_id,
            "correlation_id": correlation_id,
            "status": "QUEUED",
            "message": "Project screening submitted successfully.",
            "poll_url": f"/v1/screenings/{run_id}"
        }
    )


# -------------------------------------------------------------
# A4: Async Polling Endpoint
# -------------------------------------------------------------
@app.get("/v1/screenings/{run_id}")
async def get_screening_status(run_id: str):
    record = storage.get_run(run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screening run '{run_id}' not found."
        )

    response = {
        "run_id": record.run_id,
        "correlation_id": record.correlation_id,
        "status": record.status,
        "submitted_at": record.submitted_at,
        "completed_at": record.completed_at,
        "latency_seconds": record.latency_seconds,
        "from_cache": record.from_cache,
        "metrics": {
            "steps": record.steps,
            "tool_calls": record.tool_calls,
            "tokens": record.tokens,
            "cost_usd": record.cost_usd
        }
    }

    if record.status == "answered":
        response["result"] = {
            "category": record.category,
            "route": record.route,
            "basis": record.basis,
            "cited_chunk_ids": record.cited_chunk_ids,
            "citations": record.citations,
            "verification": record.verification
        }
    elif record.status == "escalated":
        response["escalation"] = record.escalation
        response["result"] = {
            "category": "ESCALATED",
            "route": "escalate_to_human",
            "basis": record.escalation.get("detail", "Escalated to human reviewer.") if record.escalation else "",
            "cited_chunk_ids": record.cited_chunk_ids,
            "citations": record.citations
        }

    return response


# -------------------------------------------------------------
# D1 / L6: User Feedback Endpoint
# -------------------------------------------------------------
@app.post("/v1/feedback")
async def record_feedback(feedback: FeedbackSubmission):
    storage.record_feedback(
        run_id=feedback.run_id,
        rating=feedback.rating,
        comments=feedback.comments or ""
    )
    logger.info(json.dumps({
        "event": "feedback_recorded",
        "run_id": feedback.run_id,
        "rating": feedback.rating
    }))
    return {
        "status": "recorded",
        "run_id": feedback.run_id,
        "rating": feedback.rating
    }


# -------------------------------------------------------------
# F2: Quarantine Inspection Endpoint
# -------------------------------------------------------------
@app.get("/v1/quarantine")
async def list_quarantine_records(limit: int = 20):
    return quarantine_store.get_records(limit=limit)


# -------------------------------------------------------------
# F8: Service Health & Corpus Check
# -------------------------------------------------------------
@app.get("/health")
async def health_check():
    corpus_exists = DATA_CORPUS.exists()
    chunk_count = 0
    if corpus_exists:
        try:
            with open(DATA_CORPUS, "r", encoding="utf-8") as f:
                chunk_count = len(json.load(f))
        except Exception:
            corpus_exists = False

    CORPUS_CHUNKS_COUNT.set(chunk_count)
    redis_alive = False
    rc = get_redis_client()
    if rc:
        try:
            redis_alive = bool(rc.ping())
        except Exception:
            pass

    return {
        "status": "healthy" if corpus_exists else "degraded",
        "service": "eia-clearance-prescreening",
        "corpus_loaded": corpus_exists,
        "corpus_chunks_count": chunk_count,
        "redis_connected": redis_alive,
        "llm_provider": settings.llm_provider,
        "prompt_version": settings.prompt_version,
        "active_runs": storage.count_active_runs()
    }


# -------------------------------------------------------------
# F8 / D5: Prometheus Metrics Endpoint
# -------------------------------------------------------------
@app.get("/metrics")
async def prometheus_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
