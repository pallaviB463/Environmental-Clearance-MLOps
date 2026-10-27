import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.contract import ScreeningSubmission
from api.quarantine import quarantine_store
from api.storage import storage
from api.worker import execute_agent_run
from api.metrics import (
    REQUESTS_TOTAL,
    QUARANTINE_RECORDS_TOTAL
)


app = FastAPI(
    title="EIA Clearance Pre-Screening Service",
    description="Multi-agent regulatory screening under EIA Notification 2006",
    version="1.0.0"
)

FRONTEND_FILE = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# In-memory client rate limiter: client_ip -> [timestamps] (Requirement D7)
RATE_LIMIT_STORE: Dict[str, list] = {}
RATE_LIMIT_PER_MINUTE = 60


@app.middleware("http")
async def rate_limit_and_correlation_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Skip rate limiting for static / health / metrics
    if request.url.path not in ["/v1/screenings"]:
        return await call_next(request)

    now = time.time()
    history = RATE_LIMIT_STORE.get(client_ip, [])
    # Keep only timestamps in last 60 seconds
    history = [t for t in history if now - t < 60]

    if len(history) >= RATE_LIMIT_PER_MINUTE:
        REQUESTS_TOTAL.labels(status="rate_limited").inc()
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
    request: Request,
    background_tasks: BackgroundTasks
):
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        raw_body = await request.json()
    except Exception as e:
        qid = f"quar_{uuid.uuid4().hex[:8]}"
        quarantine_store.record_quarantine(
            quarantine_id=qid,
            payload={},
            field_errors=[{"loc": ["body"], "msg": f"Malformed JSON: {str(e)}"}],
            client_ip=client_ip
        )
        QUARANTINE_RECORDS_TOTAL.inc()
        REQUESTS_TOTAL.labels(status="quarantined").inc()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"quarantine_id": qid, "detail": "Invalid JSON payload."}
        )

    # Validate against strict published contract (D1 / F2)
    try:
        submission = ScreeningSubmission.model_validate(raw_body)
    except ValidationError as ve:
        qid = f"quar_{uuid.uuid4().hex[:8]}"
        field_errors = []
        for err in ve.errors():
            field_errors.append({
                "loc": [str(x) for x in err.get("loc", [])],
                "msg": err.get("msg", ""),
                "type": err.get("type", "")
            })

        quarantine_store.record_quarantine(
            quarantine_id=qid,
            payload=raw_body,
            field_errors=field_errors,
            client_ip=client_ip
        )
        QUARANTINE_RECORDS_TOTAL.inc()
        REQUESTS_TOTAL.labels(status="quarantined").inc()

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "quarantine_id": qid,
                "message": "Submission rejected and quarantined at ingestion boundary. No agent run started.",
                "detail": field_errors
            }
        )

    # Valid submission -> create run and dispatch asynchronously (A4)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    correlation_id = f"corr_{uuid.uuid4().hex[:8]}"

    storage.create_run(
        run_id=run_id,
        correlation_id=correlation_id,
        payload=raw_body
    )

    REQUESTS_TOTAL.labels(status="accepted").inc()

    # Enqueue execution
    background_tasks.add_task(execute_agent_run, run_id)

    return {
        "run_id": run_id,
        "correlation_id": correlation_id,
        "status": "QUEUED",
        "poll_url": f"/v1/screenings/{run_id}",
        "message": "Screening submission accepted. Polling status asynchronously."
    }


# -------------------------------------------------------------
# Polling Status & Result Endpoint (Requirement A4 / F5 / F6)
# -------------------------------------------------------------
@app.get("/v1/screenings/{run_id}")
async def get_screening_status(run_id: str):
    record = storage.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return record.model_dump()


# -------------------------------------------------------------
# Quarantine Audit Endpoint (Requirement D1 / Demo Item 4)
# -------------------------------------------------------------
@app.get("/v1/quarantine")
async def list_quarantined_records():
    return {
        "count": quarantine_store.count(),
        "records": quarantine_store.get_all()
    }


# -------------------------------------------------------------
# Feedback Endpoint (Requirement L6)
# -------------------------------------------------------------
@app.post("/v1/screenings/{run_id}/feedback")
async def submit_feedback(run_id: str, payload: Dict[str, Any]):
    record = storage.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found.")

    satisfactory = bool(payload.get("satisfactory", True))
    reason = payload.get("reason")
    fb = storage.add_feedback(run_id, satisfactory, reason)
    return {"message": "Feedback recorded", "feedback_id": fb.feedback_id}


@app.get("/v1/feedback/summary")
async def get_feedback_summary():
    return storage.get_feedback_summary()


# -------------------------------------------------------------
# Health Check Endpoint (Requirement F8)
# -------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "environmental-clearance-pre-screening",
        "orchestration": "LangGraph",
        "corpus_loaded": True,
        "timestamp": time.time()
    }


# -------------------------------------------------------------
# Prometheus Metrics Scraping Endpoint (Requirement F8 / D5)
# -------------------------------------------------------------
@app.get("/metrics")
async def prometheus_metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
