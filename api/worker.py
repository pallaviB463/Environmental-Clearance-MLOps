import time
from typing import Any, Dict

from agent.graph import graph
from agent.state import (
    AgentState,
    ProjectRequest,
    Capacity,
    Location,
    ProtectedArea
)
from api.storage import storage, RunRecord
from api.metrics import (
    RUNS_TOTAL,
    RUN_LATENCY_SECONDS,
    STEPS_TOTAL,
    TOOL_CALLS_TOTAL,
    VERIFICATION_RETRIES_TOTAL,
    COST_USD_TOTAL,
    TOKENS_TOTAL,
    ESCALATIONS_TOTAL
)


def execute_agent_run(run_id: str):
    """
    Asynchronous agent execution task (Requirement A4).
    Reads the queued run record, invokes the LangGraph pipeline,
    records execution counters, resolves citations, and updates storage.
    """
    record = storage.get_run(run_id)
    if not record:
        return

    payload = record.request_payload
    cache_key = storage.compute_cache_key(payload)

    # --------------------------------------------------
    # D7: Caching Check
    # --------------------------------------------------
    if cache_key in storage.cache:
        cached_run_id = storage.cache[cache_key]
        cached_record = storage.get_run(cached_run_id)
        if cached_record and cached_record.status in ["answered", "escalated"]:
            now = time.time()
            record.status = cached_record.status
            record.completed_at = now
            record.latency_seconds = round(now - record.submitted_at, 4)
            record.category = cached_record.category
            record.route = cached_record.route
            record.basis = cached_record.basis
            record.cited_chunk_ids = cached_record.cited_chunk_ids
            record.citations = cached_record.citations
            record.verification = cached_record.verification
            record.escalation = cached_record.escalation
            record.steps = 0
            record.tool_calls = 0
            record.tokens = 0
            record.cost_usd = 0.0
            record.from_cache = True
            storage.update_run(record)
            RUNS_TOTAL.labels(status=record.status).inc()
            return

    record.status = "RUNNING"
    storage.update_run(record)

    start_time = time.time()

    # --------------------------------------------------
    # Convert input payload into ProjectRequest
    # --------------------------------------------------
    cap = None
    if payload.get("capacity"):
        cap = Capacity(
            value=float(payload["capacity"]["value"]),
            unit=payload["capacity"]["unit"]
        )

    loc = None
    if payload.get("location"):
        loc = Location(
            state=payload["location"]["state"],
            district=payload["location"]["district"]
        )

    nearest_pa = None
    # Parse proximity or nearest_protected_area
    if payload.get("nearest_protected_area"):
        npa = payload["nearest_protected_area"]
        nearest_pa = ProtectedArea(
            type=npa.get("type", "protected_area"),
            name=npa.get("name"),
            distance_km=npa.get("distance_km"),
            basis=npa.get("basis", "surveyed")
        )
    elif payload.get("proximity"):
        for p in payload["proximity"]:
            if "protected_area" in p.get("feature", "").lower() or "national_park" in p.get("subtype", "").lower():
                nearest_pa = ProtectedArea(
                    type=p.get("subtype") or "protected_area",
                    name=p.get("name"),
                    distance_km=p.get("distance_km"),
                    basis=p.get("basis", "surveyed")
                )
                break

    request_obj = ProjectRequest(
        run_id=run_id,
        correlation_id=record.correlation_id,
        description=payload.get("description", ""),
        project_name=payload.get("project_name"),
        activity=payload.get("activity", "new"),
        sector_description=payload.get("sector_description"),
        sector_hint=payload.get("sector_hint"),
        capacity=cap,
        area_ha=payload.get("project_area_ha") or payload.get("area_ha"),
        project_area_ha=payload.get("project_area_ha") or payload.get("area_ha"),
        location=loc,
        nearest_protected_area=nearest_pa,
        proximity=payload.get("proximity"),
        in_critically_polluted_area=payload.get("in_critically_polluted_area", False),
        eco_sensitive_zone=payload.get("eco_sensitive_zone")
    )

    initial_state = AgentState(
        request=request_obj,
        start_time=start_time,
        prompt_version=record.prompt_version
    )

    # --------------------------------------------------
    # Execute LangGraph Agent
    # --------------------------------------------------
    try:
        raw_result = graph.invoke(initial_state)
        final_state = AgentState.model_validate(raw_result)
    except Exception as e:
        end_time = time.time()
        record.status = "FAILED"
        record.completed_at = end_time
        record.latency_seconds = round(end_time - start_time, 4)
        record.escalation = {
            "reason_code": "SYSTEM_EXCEPTION",
            "detail": f"Execution halted due to internal error: {str(e)}"
        }
        storage.update_run(record)
        RUNS_TOTAL.labels(status="failed").inc()
        return

    end_time = time.time()
    latency = round(end_time - start_time, 4)

    # --------------------------------------------------
    # Resolve Citations (A3: Every citation must resolve)
    # --------------------------------------------------
    citations_data = []
    if final_state.draft_answer:
        for chunk_id in final_state.draft_answer.cited_chunk_ids:
            chunk = final_state.retrieved_chunks.get(chunk_id)
            if chunk:
                citations_data.append({
                    "chunk_id": chunk.chunk_id,
                    "section": chunk.section,
                    "clause": chunk.clause,
                    "doc": chunk.doc,
                    "doc_version": chunk.doc_version,
                    "text": chunk.text
                })

    # Update record
    record.status = final_state.status
    record.completed_at = end_time
    record.latency_seconds = latency
    record.steps = final_state.steps
    record.tool_calls = final_state.tool_calls
    record.tokens = final_state.prompt_tokens + final_state.completion_tokens
    record.cost_usd = final_state.cost_usd

    if final_state.draft_answer:
        record.category = final_state.draft_answer.category
        record.route = final_state.draft_answer.route
        record.basis = final_state.draft_answer.basis
        record.cited_chunk_ids = final_state.draft_answer.cited_chunk_ids
        record.citations = citations_data

    if final_state.verification:
        record.verification = final_state.verification.model_dump()

    if final_state.escalation:
        record.escalation = final_state.escalation.model_dump()
        ESCALATIONS_TOTAL.labels(reason_code=final_state.escalation.reason_code).inc()

    storage.update_run(record)
    storage.cache[cache_key] = run_id

    # Update Prometheus metrics
    RUN_LATENCY_SECONDS.observe(latency)
    RUNS_TOTAL.labels(status=final_state.status).inc()
    STEPS_TOTAL.inc(final_state.steps)
    TOOL_CALLS_TOTAL.inc(final_state.tool_calls)
    VERIFICATION_RETRIES_TOTAL.inc(final_state.verification_retries)
    if final_state.cost_usd > 0:
        COST_USD_TOTAL.inc(final_state.cost_usd)
