from langgraph.graph import StateGraph, START, END
from agent.guardrails.output_filter import validate_output

from agent.state import AgentState, Escalation
from agent.agents.extractor import extract_entities
from agent.agents.analyst import analyse_provisions
from agent.agents.verifier import verify_answer
from agent.config import settings


# ---------------------------------------------------------
# NODE WRAPPERS
# ---------------------------------------------------------

def extractor_node(state: AgentState):
    return extract_entities(state)


def analyst_node(state: AgentState):
    return analyse_provisions(state)


def verifier_node(state: AgentState):
    return verify_answer(state)


# ---------------------------------------------------------
# FINALISE
# ---------------------------------------------------------

def finalise_node(state: AgentState):

    state.steps += 1

    # ---------------------------------------------
    # Verification must have passed
    # ---------------------------------------------

    if not (
        state.verification
        and state.verification.passed
        and state.draft_answer
    ):
        state.status = "escalated"

        if state.escalation is None:
            state.escalation = Escalation(
                reason_code="VERIFICATION_FAILED",
                detail=(
                    "The answer could not be safely verified."
                )
            )

        return state

    # ---------------------------------------------
    # OUTPUT GUARDRAIL
    # ---------------------------------------------

    output_text = (
        state.draft_answer.basis
    )

    route = (
        state.draft_answer.route
    )

    guardrail_result = validate_output(
        text=output_text,
        route=route
    )

    state.metadata[
        "output_guardrail"
    ] = guardrail_result

    # ---------------------------------------------
    # Unsafe output → do NOT return answer
    # ---------------------------------------------

    if not guardrail_result["safe"]:

        state.status = "escalated"

        state.escalation = Escalation(
            reason_code="OUTPUT_GUARDRAIL_FAILED",
            detail=(
                "The generated determination failed "
                "the output safety checks."
            )
        )

        return state

    # ---------------------------------------------
    # Safe + verified
    # ---------------------------------------------

    state.status = "answered"

    state.metadata[
        "disclaimer"
    ] = guardrail_result["disclaimer"]

    return state

# ---------------------------------------------------------
# ESCALATION NODE
# ---------------------------------------------------------

def escalate_node(state: AgentState):

    state.steps += 1

    state.status = "escalated"

    if state.escalation is None:
        state.escalation = Escalation(
            reason_code="VERIFICATION_FAILED",
            detail="The system could not produce a verified answer."
        )

    return state


# ---------------------------------------------------------
# ROUTING AFTER EXTRACTOR
# ---------------------------------------------------------

def after_extractor(state: AgentState):

    if state.status in ("escalated", "failed"):
        return "escalate"

    if state.steps >= settings.max_steps:
        state.escalation = Escalation(
            reason_code="LIMIT_STEPS",
            detail="Maximum graph step limit reached."
        )
        return "escalate"

    return "analyse"


# ---------------------------------------------------------
# ROUTING AFTER ANALYST
# ---------------------------------------------------------

def after_analyst(state: AgentState):

    if state.status in ("escalated", "failed"):
        return "escalate"

    if state.steps >= settings.max_steps:
        state.escalation = Escalation(
            reason_code="LIMIT_STEPS",
            detail="Maximum graph step limit reached."
        )
        return "escalate"

    if state.tool_calls > settings.max_tool_calls:
        state.escalation = Escalation(
            reason_code="LIMIT_TOOL_CALLS",
            detail="Maximum tool-call limit reached."
        )
        return "escalate"

    return "verify"


# ---------------------------------------------------------
# ROUTING AFTER VERIFIER
# ---------------------------------------------------------

def after_verifier(state: AgentState):

    if state.verification is None:
        state.escalation = Escalation(
            reason_code="VERIFICATION_FAILED",
            detail="Verifier returned no result."
        )
        return "escalate"

    # Successful verification
    if state.verification.verdict == "pass":
        return "finalise"

    # Verifier requests another attempt
    if state.verification.verdict == "retry":

        state.verification_retries += 1

        if state.verification_retries > settings.max_verification_retries:
            state.escalation = Escalation(
                reason_code="VERIFICATION_FAILED",
                detail=(
                    "Verification failed after the maximum "
                    "number of retries."
                )
            )
            return "escalate"

        if state.steps >= settings.max_steps:
            state.escalation = Escalation(
                reason_code="LIMIT_STEPS",
                detail="Maximum graph step limit reached."
            )
            return "escalate"

        return "analyse"

    # Anything else is unsafe
    state.escalation = Escalation(
        reason_code="VERIFICATION_FAILED",
        detail="Verifier requested escalation."
    )

    return "escalate"


# ---------------------------------------------------------
# BUILD LANGGRAPH
# ---------------------------------------------------------

builder = StateGraph(AgentState)

builder.add_node("extract", extractor_node)
builder.add_node("analyse", analyst_node)
builder.add_node("verify", verifier_node)
builder.add_node("finalise", finalise_node)
builder.add_node("escalate", escalate_node)


builder.add_edge(
    START,
    "extract"
)


builder.add_conditional_edges(
    "extract",
    after_extractor,
    {
        "analyse": "analyse",
        "escalate": "escalate"
    }
)


builder.add_conditional_edges(
    "analyse",
    after_analyst,
    {
        "verify": "verify",
        "escalate": "escalate"
    }
)


builder.add_conditional_edges(
    "verify",
    after_verifier,
    {
        "finalise": "finalise",
        "analyse": "analyse",
        "escalate": "escalate"
    }
)


builder.add_edge(
    "finalise",
    END
)

builder.add_edge(
    "escalate",
    END
)


graph = builder.compile()