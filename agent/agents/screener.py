"""
Screener agent: an LLM in a tool-calling loop.

Each turn the model either calls tools (search_corpus, get_clause, find_modifiers,
get_request_fields) or returns its draft as JSON. Nothing about the order of retrieval
is fixed in code: the model decides. The loop is bounded by the run's step budget,
tool-call budget and wall-clock deadline (A1).

Hand-off: the draft (DraftDetermination) plus every passage retrieved in this run goes
to the Verifier agent. On a rejected draft the Verifier's feedback comes back here and
the Screener tries again with a different strategy.
"""
import json
import time
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from agent.config import settings
from agent.llm.client import LLMUnavailableError, RunDeadlineExceeded
from agent.llm.gateway import get_gateway
from agent.llm.json_extract import extract_json_object
from agent.prompts import load_prompt
from agent.state import AgentState, Citation, DraftDetermination, Escalation
from agent.tools.toolbox import ToolBox, ToolBudgetExceeded
from observability.metrics import AGENT_TASKS_TOTAL
from observability.recorder import get_recorder


# Tool calls one Screener attempt may make before it must answer from what it has read.
# The run-wide MAX_TOOL_CALLS still bounds everything; this leaves room for a retry.
ATTEMPT_TOOL_CALLS = 8
FINAL_ANSWER_PROMPT = (
    "Tool budget for this attempt is used. Do not call tools. Using only the passages already "
    "returned above, reply now with the JSON object described in your instructions (escalate if "
    "they are not enough to decide)."
)

EXPECTED_ROUTES = {"A": "category_a_central", "B": "category_b_state", "NO_CLEARANCE": "no_clearance"}

REQUEST_FIELDS_FOR_PROMPT = (
    "project_name", "activity", "description", "sector_description", "sector_hint", "capacity",
    "area_ha", "location", "nearest_protected_area", "proximity", "in_critically_polluted_area",
    "eco_sensitive_zone",
)


def _as_data(value: Any) -> str:
    """Serialise request data so free text cannot close or open our prompt delimiters."""
    return json.dumps(value, ensure_ascii=False, default=str).replace("<", "‹").replace(">", "›")


def render_user_message(state: AgentState) -> str:
    request = state.request.model_dump(include=set(REQUEST_FIELDS_FOR_PROMPT), exclude_none=True)
    entities = state.extracted_entities.model_dump(exclude_none=True) if state.extracted_entities else {}
    parts = [
        "Screen this project.",
        f"<project_data>\n{_as_data(request)}\n</project_data>",
        "Fields pre-extracted from the validated request (sector is a keyword hint only; confirm the Schedule row from the corpus):",
        f"<extracted_entities>\n{_as_data(entities)}\n</extracted_entities>",
    ]
    if state.verification and state.verification.verdict == "retry" and state.draft_answer:
        parts += [
            "Your previous draft was REJECTED by the Verifier agent:",
            state.verification.feedback or state.verification.reason or "unsupported draft",
            f"Previous draft: {_as_data(state.draft_answer.model_dump(exclude={'produced_by'}))}",
            "Use a different strategy this time: fetch the provisions the Verifier named, search with "
            "different terms, and cite only passages returned by your tools in this conversation.",
        ]
    return "\n\n".join(parts)


def parse_draft(content: str) -> Optional[DraftDetermination]:
    """Extract the JSON draft from the model's final message, tolerating code fences and prose."""
    data = extract_json_object(content, expected_keys=("decision", "route", "category"))
    if data is None:
        return None

    citations = []
    for item in data.get("citations") or []:
        if isinstance(item, str):
            citations.append(Citation(chunk_id=item))
        elif isinstance(item, dict) and item.get("chunk_id"):
            citations.append(Citation(chunk_id=str(item["chunk_id"]), quote=str(item.get("quote") or "")))
    data["citations"] = citations

    category = str(data.get("category") or "").strip().upper().replace("CATEGORY ", "").replace(" ", "_")
    data["category"] = category if category in EXPECTED_ROUTES else None
    decision = str(data.get("decision") or "").lower()
    if decision.startswith("escalat") or data.get("route") in ("escalate", "escalate_to_human", "human_review"):
        data["decision"] = "escalate"
        data["route"] = "escalate_to_human"
        data["category"] = None
    else:
        data["decision"] = "determination"
        # Models sometimes give a valid category with a free-form route: the category decides
        if data["category"] is not None and data.get("route") not in EXPECTED_ROUTES.values():
            data["route"] = EXPECTED_ROUTES[data["category"]]
    try:
        return DraftDetermination(**{k: v for k, v in data.items() if k in DraftDetermination.model_fields})
    except ValidationError:
        return None


def _stop(state: AgentState, code: str, detail: str) -> AgentState:
    state.status = "escalated"
    state.escalation = Escalation(reason_code=code, detail=detail)
    AGENT_TASKS_TOTAL.labels(agent="screener", outcome=code.lower()).inc()
    return state


def run_screener(state: AgentState) -> AgentState:
    recorder = get_recorder()
    gateway = get_gateway()
    if state.verification is not None and state.verification.verdict == "retry":
        state.verification_retries += 1
        recorder.event("retry", agent="screener", attempt=state.verification_retries,
                       reason=state.verification.reason, feedback=state.verification.feedback)
    state.screener_attempts += 1
    state.steps += 1

    prompt, prompt_hash = load_prompt("screener", state.prompt_version)
    state.metadata.setdefault("prompt_hashes", {})["screener"] = prompt_hash
    toolbox = ToolBox(state, agent="screener", enabled=state.metadata.get("enabled_tools"))

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": render_user_message(state)},
    ]
    recorder.event("agent_start", agent="screener", attempt=state.screener_attempts,
                   prompt_version=state.prompt_version, prompt_hash=prompt_hash,
                   tools=toolbox.enabled)

    repaired = False
    turn = 0
    attempt_tool_calls = 0

    while True:
        if state.deadline and time.time() > state.deadline:
            return _stop(state, "LIMIT_WALL_CLOCK", f"Run exceeded its {settings.run_deadline_seconds:g}s deadline.")
        if state.steps >= settings.max_steps:
            return _stop(state, "LIMIT_STEPS", f"Run reached its limit of {settings.max_steps} steps.")

        turn += 1
        state.steps += 1
        state.llm_calls += 1
        remaining = settings.max_tool_calls - state.tool_calls
        must_answer = attempt_tool_calls >= ATTEMPT_TOOL_CALLS or remaining <= 1
        if must_answer and messages[-1].get("content") != FINAL_ANSWER_PROMPT:
            messages.append({"role": "user", "content": FINAL_ANSWER_PROMPT})
        try:
            response = gateway.complete(
                messages, toolbox.schemas(), agent="screener", tool_choice="none" if must_answer else "auto",
                step=f"screener.attempt{state.screener_attempts}.turn{turn}",
                prompt_version=state.prompt_version,
                deadline=state.deadline,
            )
        except RunDeadlineExceeded:
            return _stop(state, "LIMIT_WALL_CLOCK", f"Run exceeded its {settings.run_deadline_seconds:g}s deadline.")
        except LLMUnavailableError as error:
            state.llm_unavailable = True
            recorder.event("llm_unavailable", agent="screener", error=str(error)[:400])
            AGENT_TASKS_TOTAL.labels(agent="screener", outcome="llm_unavailable").inc()
            return state

        state.prompt_tokens += response["prompt_tokens"]
        state.completion_tokens += response["completion_tokens"]
        state.cost_usd += response["cost_usd"]
        state.usage_by_step.append({
            "agent": "screener", "step": f"attempt{state.screener_attempts}.turn{turn}",
            "model": response["model"], "prompt_tokens": response["prompt_tokens"],
            "completion_tokens": response["completion_tokens"], "cost_usd": response["cost_usd"],
            "latency_ms": response["latency_ms"],
        })
        raw_message = response["raw_message"]
        if must_answer and raw_message.get("tool_calls"):
            # No tools were offered: drop stray calls so no unanswered tool call stays in the conversation
            raw_message = {"role": "assistant", "content": raw_message.get("content") or ""}
        messages.append(raw_message)

        if response["tool_calls"] and not must_answer:
            for call in response["tool_calls"]:
                if attempt_tool_calls >= ATTEMPT_TOOL_CALLS:
                    result = {"error": "tool budget for this attempt is used; answer from what you have read"}
                else:
                    try:
                        result = toolbox.execute(call["name"], call["arguments"])
                    except ToolBudgetExceeded as error:
                        return _stop(state, "LIMIT_TOOL_CALLS", str(error))
                    attempt_tool_calls += 1
                    result["tool_calls_remaining"] = max(0, ATTEMPT_TOOL_CALLS - attempt_tool_calls)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
            continue

        draft = parse_draft(response["content"])
        if draft is None:
            if repaired:
                return _stop(state, "SCREENER_OUTPUT_INVALID", "The Screener did not return a valid JSON draft.")
            repaired = True
            messages.append({"role": "user", "content": "Reply with only the JSON object described in your instructions."})
            continue

        draft.produced_by = f"screener_llm:{response['model']}"
        state.draft_answer = draft
        recorder.event("draft", agent="screener", attempt=state.screener_attempts, draft=draft.model_dump())
        AGENT_TASKS_TOTAL.labels(agent="screener", outcome="draft").inc()
        return state
