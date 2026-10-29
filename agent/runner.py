"""
Single entry point for running one screening through the graph. Used by the worker,
the evaluation harness and run_local.py, so all three exercise the same code.
"""
import time
from typing import List, Optional

from agent.config import settings
from agent.graph import graph
from agent.state import AgentState, ProjectRequest
from observability.logs import correlation_id_var, run_id_var
from observability.metrics import AGENT_STEPS_PER_RUN, AGENT_TOOL_CALLS_PER_RUN
from observability.recorder import RunRecorder, set_recorder
from observability.tracing import get_tracer


def run_screening(
    request: ProjectRequest,
    run_id: str,
    correlation_id: str,
    prompt_version: Optional[str] = None,
    recorder: Optional[RunRecorder] = None,
    enabled_tools: Optional[List[str]] = None,
    skip_llm_verifier: bool = False,
) -> AgentState:
    recorder = recorder or RunRecorder(run_id, correlation_id)
    set_recorder(recorder)
    run_id_var.set(run_id)
    correlation_id_var.set(correlation_id)

    now = time.time()
    state = AgentState(
        run_id=run_id,
        correlation_id=correlation_id,
        request=request,
        prompt_version=prompt_version or settings.prompt_version,
        start_time=now,
        deadline=now + settings.run_deadline_seconds,
    )
    if enabled_tools:
        state.metadata["enabled_tools"] = enabled_tools
    if skip_llm_verifier:
        state.metadata["skip_llm_verifier"] = True

    recorder.event("run_start", agent="graph", prompt_version=state.prompt_version,
                   llm_provider=settings.llm_provider, models=[m for m in (settings.llm_model, settings.llm_fallback_model) if m],
                   limits={"max_steps": settings.max_steps, "max_tool_calls": settings.max_tool_calls,
                           "deadline_s": settings.run_deadline_seconds})

    with get_tracer().start_as_current_span("agent.run") as span:
        span.set_attribute("run.id", run_id)
        span.set_attribute("correlation.id", correlation_id)
        span.set_attribute("prompt.version", state.prompt_version)
        result = graph.invoke(state, config={"recursion_limit": 60})
        final = result if isinstance(result, AgentState) else AgentState(**result)
        span.set_attribute("run.status", final.status)
        span.set_attribute("run.mode", final.mode)

    AGENT_STEPS_PER_RUN.labels(agent="all").observe(final.steps)
    AGENT_TOOL_CALLS_PER_RUN.labels(agent="all").observe(final.tool_calls)
    recorder.event(
        "run_end", agent="graph", status=final.status, mode=final.mode,
        category=final.draft_answer.category if final.draft_answer else None,
        route=final.draft_answer.route if final.draft_answer else None,
        escalation=final.escalation.model_dump() if final.escalation else None,
        steps=final.steps, tool_calls=final.tool_calls, llm_calls=final.llm_calls,
        prompt_tokens=final.prompt_tokens, completion_tokens=final.completion_tokens,
        cost_usd=round(final.cost_usd, 6), latency_ms=round((time.time() - now) * 1000, 1),
    )
    return final
