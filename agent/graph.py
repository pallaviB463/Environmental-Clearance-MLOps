"""
LangGraph topology (Requirements A1 / A2 / A3 / A5).

    START -> extract --(guardrail / proximity escalation)--------------------> escalate -> END
                |
                v
             screen  <-------------------- retry with Verifier feedback -----+
                |                                                             |
                +--(draft says escalate / budget exhausted)--> escalate       |
                +--(LLM provider unavailable)----------------> degrade        |
                v                                                             |
             verify ---(pass)--> finalise -> END                              |
                |  \---(retry, budget left)--------------------------------- +
                |  \---(escalate / retries exhausted)--> escalate -> END
                \---(verifier model unavailable)----> degrade -> END

Agents: the Screener (screen) and the Verifier (verify) are separate agents with their own
prompts, tools and budgets. The Verifier can run in its own service (VERIFIER_URL); the
hand-off is the DraftDetermination plus the passages retrieved in the run.

Failure mid-run: if the Screener's model is unavailable, the run goes to `degrade`; if the
Verifier is unreachable, the run is escalated (an unverified draft is never returned); if
a worker process dies, the queue re-delivers the run (see api/worker.py).
"""
import time

from langgraph.graph import END, START, StateGraph

from agent.agents.extractor import extract_entities
from agent.agents.screener import run_screener
from agent.agents.verifier_client import run_verifier
from agent.config import settings
from agent.fallback import rules
from agent.guardrails.output_filter import validate_output
from agent.guardrails.toxicity import check_toxicity
from agent.retrieval.store import get_store
from agent.state import AgentState, Escalation
from observability.recorder import get_recorder


# ---------------------------------------------------------
# NODES
# ---------------------------------------------------------

def finalise_node(state: AgentState) -> AgentState:
    """Output guardrails (L4) on a verified draft; only a verified, safe draft is answered."""
    state.steps += 1
    draft = state.draft_answer
    recorder = get_recorder()

    with recorder.step("finalise", agent="output_guardrail") as outcome:
        guard = validate_output(text=draft.basis, route=draft.route)
        is_toxic, toxicity = check_toxicity(draft.basis)
        state.metadata["output_guardrail"] = {**guard, "toxicity": toxicity}

        if not guard["safe"] or is_toxic:
            state.status = "escalated"
            state.escalation = Escalation(
                reason_code="OUTPUT_GUARDRAIL_FAILED",
                detail="The draft opinion failed the output checks: " + "; ".join(guard["problems"] or ["toxicity"]),
            )
        else:
            state.status = "answered"
            state.metadata["disclaimer"] = guard["disclaimer"]
        outcome.update(status=state.status)
    return state


def escalate_node(state: AgentState) -> AgentState:
    """Decide the escalation reason here: routers cannot write to the state."""
    state.steps += 1
    state.status = "escalated"
    if state.escalation is None:
        draft = state.draft_answer
        verification = state.verification
        budget = _budget_exceeded(state)
        if budget:
            state.escalation = Escalation(reason_code=budget, detail="The run reached a safety limit before a verified answer.")
        elif draft is not None and draft.decision == "escalate":
            state.escalation = Escalation(
                reason_code=draft.escalation_reason_code or "SCREENER_ESCALATED",
                detail=draft.escalation_detail or draft.basis or "The Screener escalated to a human reviewer.",
            )
        elif verification is not None and verification.verdict == "retry":
            state.escalation = Escalation(
                reason_code="VERIFICATION_FAILED",
                detail=f"Draft still unsupported after {state.verification_retries} retries "
                       f"({verification.reason}): {verification.feedback}",
            )
        elif verification is not None and verification.verdict != "pass":
            state.escalation = Escalation(
                reason_code=verification.reason or "VERIFICATION_FAILED",
                detail="The draft could not be verified against the retrieved passages: "
                       + "; ".join(verification.checks[-2:]),
            )
        else:
            state.escalation = Escalation(reason_code="VERIFICATION_FAILED",
                                          detail="The system could not produce a verified answer.")
    get_recorder().event("escalation", agent="graph", **state.escalation.model_dump())
    return state


def degrade_node(state: AgentState) -> AgentState:
    """
    Graceful degradation (A5): the LLM path is unavailable. The rule engine produces a
    provisional opinion, the deterministic verifier checks it, and the run is ESCALATED
    with that opinion attached for the human reviewer. It is never returned as an answer.
    """
    state.steps += 1
    state.mode = "degraded"
    recorder = get_recorder()

    with recorder.step("degrade", agent="rule_engine") as outcome:
        entities = state.extracted_entities
        draft, retrieved = rules.screen(entities, state.request.description, get_store())
        state.retrieved_chunks.update(retrieved)
        state.provisional_opinion = draft
        outcome.update(provisional_category=draft.category or "escalate", provisional_route=draft.route or "")

    state.status = "escalated"
    state.escalation = Escalation(
        reason_code="PROVIDER_UNAVAILABLE",
        detail=(
            "The language model provider is unavailable (circuit breaker open or retries exhausted). "
            "A rule-based provisional opinion is attached for the reviewer; it has not been through the "
            "agentic screening and must not be relied on as a screening result."
        ),
    )
    return state


# ---------------------------------------------------------
# ROUTING
# ---------------------------------------------------------

# Routers only read the state: LangGraph discards changes a routing function makes, so
# counters and escalation reasons are written by nodes (screen, escalate).

def _budget_exceeded(state: AgentState):
    if state.deadline and time.time() > state.deadline:
        return "LIMIT_WALL_CLOCK"
    if state.steps >= settings.max_steps:
        return "LIMIT_STEPS"
    return None


def after_extract(state: AgentState) -> str:
    if state.status in ("escalated", "failed"):
        return "escalate"
    return "screen"


def after_screen(state: AgentState) -> str:
    if state.llm_unavailable:
        return "degrade"
    if state.status in ("escalated", "failed") or state.draft_answer is None:
        return "escalate"
    if state.draft_answer.decision == "escalate":
        return "escalate"
    if _budget_exceeded(state):
        return "escalate"
    return "verify"


def after_verify(state: AgentState) -> str:
    verification = state.verification
    if state.llm_unavailable:
        return "degrade"
    if verification is None:
        return "escalate"
    if verification.verdict == "pass":
        return "finalise"
    if verification.verdict == "retry":
        if state.verification_retries >= settings.max_verification_retries or _budget_exceeded(state):
            return "escalate"
        return "screen"
    return "escalate"


# ---------------------------------------------------------
# BUILD LANGGRAPH
# ---------------------------------------------------------

builder = StateGraph(AgentState)

builder.add_node("extract", extract_entities)
builder.add_node("screen", run_screener)
builder.add_node("verify", run_verifier)
builder.add_node("finalise", finalise_node)
builder.add_node("escalate", escalate_node)
builder.add_node("degrade", degrade_node)

builder.add_edge(START, "extract")
builder.add_conditional_edges("extract", after_extract, {"screen": "screen", "escalate": "escalate"})
builder.add_conditional_edges("screen", after_screen, {"verify": "verify", "escalate": "escalate", "degrade": "degrade"})
builder.add_conditional_edges("verify", after_verify,
                              {"finalise": "finalise", "screen": "screen", "escalate": "escalate", "degrade": "degrade"})
builder.add_edge("finalise", END)
builder.add_edge("escalate", END)
builder.add_edge("degrade", END)

graph = builder.compile()
