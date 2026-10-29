"""
Agent worker (Requirements A4 / A7): consumes run ids from the Redis queue and executes
the agent graph. Scales horizontally with `docker compose up --scale agent-worker=3`.

Reliable hand-off from the queue: BLMOVE moves a message atomically from eia:queue to
eia:queue:processing. It is removed only after the run's result is stored. If a worker
dies mid-run, the message stays in the processing list; the reaper in any live worker
re-queues it once (then marks the run failed), so no run is silently lost.
"""
import json
import logging
import os
import random
import signal
import socket
import time
from typing import Any, Dict, Optional

from prometheus_client import start_http_server

from agent.config import settings
from agent.llm.gateway import get_gateway
from agent.redis_client import get_redis
from agent.retrieval.store import warm_up
from agent.runner import run_screening
from agent.state import AgentState, Capacity, Location, ProjectRequest, ProtectedArea
from api.escalation import escalation_path
from api.storage import RunRecord, storage
from eval.metrics import reference_free_scores
from observability.logs import correlation_id_var, log_event, run_id_var, setup_logging
from observability.metrics import (
    ESCALATIONS_TOTAL,
    LIVE_QUALITY_SCORE,
    RUN_COST_USD,
    RUN_E2E_SECONDS,
    RUNS_IN_PROGRESS,
    RUNS_TOTAL,
)
from observability.recorder import RunRecorder
from observability.tracing import current_trace_id, extract_context, get_tracer, setup_tracing


QUEUE = "eia:queue"
PROCESSING = "eia:queue:processing"
BREAKERS_KEY = "eia:breakers"
MAX_ATTEMPTS = 2
STALE_AFTER_SECONDS = settings.run_deadline_seconds + 60
REAP_EVERY_SECONDS = 30
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Runs ending with these are not cached: the next identical request should try again
UNCACHEABLE_REASONS = {"PROVIDER_UNAVAILABLE", "VERIFIER_UNAVAILABLE", "INTERNAL_ERROR",
                       "LIMIT_WALL_CLOCK", "LIMIT_STEPS", "LIMIT_TOOL_CALLS"}

logger = logging.getLogger("eia.worker")


def enqueue(run_id: str, trace_context: Dict[str, str]) -> bool:
    redis = get_redis()
    if redis is None:
        return False
    redis.lpush(QUEUE, json.dumps({"run_id": run_id, "trace": trace_context, "enqueued_at": time.time()}))
    return True


def build_request(payload: Dict[str, Any], run_id: str, correlation_id: str) -> ProjectRequest:
    capacity = payload.get("capacity")
    location = payload.get("location")
    nearest = payload.get("nearest_protected_area")
    return ProjectRequest(
        run_id=run_id,
        correlation_id=correlation_id,
        description=payload.get("description", ""),
        project_name=payload.get("project_name"),
        activity=payload.get("activity") or "new",
        sector_description=payload.get("sector_description"),
        sector_hint=payload.get("sector_hint"),
        capacity=Capacity(**capacity) if capacity else None,
        area_ha=payload.get("project_area_ha") or payload.get("area_ha"),
        location=Location(**location) if location else None,
        nearest_protected_area=ProtectedArea(**nearest) if nearest else None,
        proximity=payload.get("proximity") or [],
        in_critically_polluted_area=bool(payload.get("in_critically_polluted_area")),
        eco_sensitive_zone=payload.get("eco_sensitive_zone"),
    )


def apply_result(record: RunRecord, final: AgentState) -> RunRecord:
    now = time.time()
    record.status = final.status
    record.mode = final.mode
    record.completed_at = now
    record.latency_seconds = round(now - record.submitted_at, 3)
    record.prompt_version = final.prompt_version
    record.prompt_hashes = final.metadata.get("prompt_hashes", {})
    record.steps = final.steps
    record.tool_calls = final.tool_calls
    record.llm_calls = final.llm_calls
    record.prompt_tokens = final.prompt_tokens
    record.completion_tokens = final.completion_tokens
    record.cost_usd = round(final.cost_usd, 6)
    record.usage_by_step = final.usage_by_step

    draft = final.draft_answer
    if draft is not None:
        record.category = draft.category
        record.route = draft.route
        record.schedule_item = draft.schedule_item
        record.basis = draft.basis
        record.citations = [
            {
                "chunk_id": c.chunk_id,
                "quote": c.quote,
                "clause": final.retrieved_chunks[c.chunk_id].clause,
                "section": final.retrieved_chunks[c.chunk_id].section,
                "doc_version": final.retrieved_chunks[c.chunk_id].doc_version,
                "text": final.retrieved_chunks[c.chunk_id].text,
            }
            for c in draft.citations if c.chunk_id in final.retrieved_chunks
        ]
    if final.status != "answered":
        record.category = None
        record.route = "escalate_to_human"

    record.verification = final.verification.model_dump() if final.verification else None
    record.escalation = escalation_path(final.escalation.model_dump()) if final.escalation else None
    record.provisional_opinion = final.provisional_opinion.model_dump() if final.provisional_opinion else None
    record.disclaimer = final.metadata.get("disclaimer")
    return record


def _sample_live_quality(record: RunRecord, final: AgentState, recorder: RunRecorder) -> None:
    """L6: automatically score a sample of live runs with the reference-free eval metrics."""
    if final.draft_answer is None or random.random() > settings.live_eval_sample_rate:
        return
    scores = reference_free_scores(final)
    for metric, value in scores.items():
        if value is not None:
            LIVE_QUALITY_SCORE.labels(metric=metric).observe(value)
    redis = get_redis()
    if redis:
        redis.rpush("eia:quality", json.dumps({"ts": time.time(), "run_id": record.run_id,
                                                "prompt_version": final.prompt_version, **scores}))
        redis.ltrim("eia:quality", -5000, -1)
    recorder.event("live_quality_sample", agent="worker", **scores)


def execute_run(message: Dict[str, Any]) -> None:
    run_id = message["run_id"]
    record = storage.get_run(run_id)
    if record is None:
        logger.warning(f"run {run_id} not found in store; dropping message")
        return
    if record.status not in ("queued", "running"):
        return  # already completed (duplicate delivery): idempotent

    run_id_var.set(run_id)
    correlation_id_var.set(record.correlation_id)
    tracer = get_tracer()

    with tracer.start_as_current_span("worker.execute_run", context=extract_context(message.get("trace"))) as span:
        span.set_attribute("run.id", run_id)
        record.status = "running"
        record.started_at = time.time()
        record.attempts += 1
        record.worker_id = WORKER_ID
        record.trace_id = current_trace_id()
        storage.update_run(record)

        recorder = RunRecorder(run_id, record.correlation_id, sink=storage.append_event)
        recorder.event("dequeued", agent="worker", worker_id=WORKER_ID, attempt=record.attempts,
                       queue_wait_ms=round((record.started_at - record.submitted_at) * 1000, 1),
                       trace_id=record.trace_id)
        log_event(logger, "run started", worker_id=WORKER_ID, attempt=record.attempts)

        try:
            final = run_screening(
                build_request(record.request_payload, run_id, record.correlation_id),
                run_id, record.correlation_id, prompt_version=record.prompt_version, recorder=recorder,
            )
        except Exception as error:
            logger.exception("run failed")
            record.status = "failed"
            record.route = "escalate_to_human"
            record.completed_at = time.time()
            record.latency_seconds = round(record.completed_at - record.submitted_at, 3)
            record.escalation = escalation_path({"reason_code": "INTERNAL_ERROR", "detail": f"{type(error).__name__}: {error}"})
            storage.update_run(record)
            recorder.event("run_failed", agent="worker", error=f"{type(error).__name__}: {error}"[:400])
            RUNS_TOTAL.labels(status="failed", mode="agentic").inc()
            return

        apply_result(record, final)
        storage.update_run(record)

        reason = (record.escalation or {}).get("reason_code")
        if final.mode == "agentic" and reason not in UNCACHEABLE_REASONS and record.request_payload.get("_cache_key"):
            storage.cache_set(record.request_payload["_cache_key"], run_id)

        RUNS_TOTAL.labels(status=record.status, mode=record.mode).inc()
        RUN_E2E_SECONDS.observe(record.latency_seconds)
        RUN_COST_USD.observe(record.cost_usd)
        if reason:
            ESCALATIONS_TOTAL.labels(reason_code=reason).inc()
        _sample_live_quality(record, final, recorder)

        redis = get_redis()
        if redis:
            redis.hset(BREAKERS_KEY, WORKER_ID, json.dumps({"ts": time.time(), **get_gateway().breaker_states()}))

        log_event(logger, "run finished", status=record.status, mode=record.mode,
                  latency_s=record.latency_seconds, steps=record.steps, tool_calls=record.tool_calls,
                  cost_usd=record.cost_usd)


def reap_stale(redis) -> None:
    """Re-queue runs whose worker died mid-run (message stuck in the processing list)."""
    now = time.time()
    for raw in redis.lrange(PROCESSING, 0, -1):
        message = json.loads(raw)
        record = storage.get_run(message["run_id"])
        if record is None or record.status not in ("queued", "running"):
            redis.lrem(PROCESSING, 1, raw)
            continue
        if record.started_at and now - record.started_at < STALE_AFTER_SECONDS:
            continue
        redis.lrem(PROCESSING, 1, raw)
        if record.attempts < MAX_ATTEMPTS:
            record.status = "queued"
            storage.update_run(record)
            redis.lpush(QUEUE, raw)
            storage.append_event(record.run_id, {"ts": now, "kind": "requeued", "agent": "reaper",
                                                 "reason": "worker lost mid-run", "by": WORKER_ID})
        else:
            record.status = "failed"
            record.completed_at = now
            record.escalation = escalation_path({"reason_code": "WORKER_LOST",
                                                 "detail": "The run was interrupted twice and was not completed."})
            storage.update_run(record)


_stopping = {"flag": False}


def _request_stop(*_):
    _stopping["flag"] = True


def run_worker_daemon() -> None:
    setup_logging("agent-worker")
    setup_tracing("agent-worker")
    start_http_server(int(os.getenv("WORKER_METRICS_PORT", "9100")))
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    log_event(logger, "worker starting", worker_id=WORKER_ID)
    log_event(logger, "index warm", seconds=round(warm_up(), 2))

    last_reap = 0.0
    while not _stopping["flag"]:
        redis = get_redis()
        if redis is None:
            time.sleep(1)
            continue
        try:
            if time.time() - last_reap > REAP_EVERY_SECONDS:
                reap_stale(redis)
                last_reap = time.time()

            raw: Optional[str] = redis.blmove(QUEUE, PROCESSING, timeout=2, src="RIGHT", dest="LEFT")
            if raw is None:
                continue

            RUNS_IN_PROGRESS.inc()
            try:
                execute_run(json.loads(raw))
            finally:
                RUNS_IN_PROGRESS.dec()
                redis.lrem(PROCESSING, 1, raw)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(1)

    log_event(logger, "worker stopped", worker_id=WORKER_ID)


if __name__ == "__main__":
    run_worker_daemon()
