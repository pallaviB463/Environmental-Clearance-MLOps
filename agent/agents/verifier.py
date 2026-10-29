"""
Verifier agent (Requirement A3): no draft reaches the caller unless it passes here.

1. Deterministic checks, cheap and authoritative:
   - every citation resolves to a passage retrieved in THIS run
   - every quote appears verbatim in that passage (catches invented text)
   - category and route agree; a Schedule row is cited
   - the modifier check: if the cited Schedule row says the General Condition applies,
     the GC must have been retrieved, and if the project falls within the GC distance a
     Category B answer is rejected (the PS section 4.1 failure)
   - a row whose amendment history is recorded as not in force forces escalation
2. LLM review with its own prompt and its own tools: does the cited text, read in full,
   support the conclusion, and does it contain a provision the draft ignored?

Verdicts: pass -> finalise; retry -> back to the Screener with feedback; escalate -> human.
"""
import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from agent.fallback.rules import THRESHOLDS, gc_triggers
from agent.llm.client import LLMUnavailableError, RunDeadlineExceeded
from agent.llm.gateway import get_gateway
from agent.llm.json_extract import extract_json_object
from agent.prompts import load_prompt
from agent.retrieval.store import get_store
from agent.state import AgentState, DraftDetermination, VerificationResult
from agent.tools.toolbox import ToolBox, ToolBudgetExceeded
from observability.metrics import AGENT_TASKS_TOTAL, VERIFICATION_OUTCOMES_TOTAL
from observability.recorder import get_recorder


EXPECTED_ROUTES = {"A": "category_a_central", "B": "category_b_state", "NO_CLEARANCE": "no_clearance"}
VERIFIER_MAX_TURNS = 3
VERIFIER_MAX_TOOL_CALLS = 2


QUOTE_MIN_COVERAGE = 0.85
QUOTE_MIN_BLOCK = 8


def _normalise(text: str) -> str:
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.rstrip(" .…").removesuffix("...").strip()


def quote_found(quote: str, passage: str) -> bool:
    """
    A quote is supported if it is a verbatim span of the passage, or if, after dropping the
    ellipses and column separators models insert when quoting table rows, at least 85 % of it
    is made of verbatim runs (8+ characters) of the passage. Invented wording fails.
    """
    quote, passage = _normalise(quote), _normalise(passage)
    if not quote:
        return False
    if quote in passage:
        return True
    cleaned = re.sub(r"\s*(\.\.\.|…|\|)\s*", " ", quote).strip()
    matcher = SequenceMatcher(None, passage, cleaned, autojunk=False)
    verbatim = sum(block.size for block in matcher.get_matching_blocks() if block.size >= QUOTE_MIN_BLOCK)
    return verbatim / len(cleaned) >= QUOTE_MIN_COVERAGE


def _result(verdict: str, checks: List[str], reason: Optional[str] = None, feedback: Optional[str] = None) -> VerificationResult:
    return VerificationResult(passed=verdict == "pass", verdict=verdict, checks=checks, reason=reason, feedback=feedback)


def deterministic_checks(state: AgentState, draft: DraftDetermination) -> VerificationResult:
    checks: List[str] = []
    store = get_store()
    retrieved = state.retrieved_chunks

    if not draft.citations:
        return _result("retry", ["FAIL no citations"], "NO_CITATIONS",
                       "The draft cites nothing. Cite the Schedule row and any provision you relied on.")

    missing = [c.chunk_id for c in draft.citations if c.chunk_id not in retrieved]
    if missing:
        return _result("retry", checks + [f"FAIL citations not retrieved in this run: {missing}"], "CITATION_NOT_RETRIEVED",
                       f"These citations were not returned by any tool in this run: {missing}. Fetch them with get_clause or cite only passages you retrieved.")
    checks.append("PASS every citation resolves to a passage retrieved in this run")

    bad_quotes = [c.chunk_id for c in draft.citations if not quote_found(c.quote, retrieved[c.chunk_id].text)]
    if bad_quotes:
        return _result("retry", checks + [f"FAIL quotes not found verbatim in: {bad_quotes}"], "QUOTE_NOT_FOUND",
                       f"The quotes given for {bad_quotes} do not appear in those passages. Copy quotes exactly from the passage text.")
    checks.append("PASS every quote appears verbatim in its passage")

    if EXPECTED_ROUTES.get(draft.category) != draft.route:
        return _result("retry", checks + [f"FAIL category {draft.category} does not match route {draft.route}"], "CATEGORY_ROUTE_MISMATCH",
                       f"Category {draft.category} must use route {EXPECTED_ROUTES.get(draft.category)}.")
    checks.append("PASS category and route agree")

    cited = [retrieved[c.chunk_id] for c in draft.citations]
    rows = [c for c in cited if c.chunk_id.startswith("schedule:") and c.chunk_id not in ("schedule:gc", "schedule:sc")]

    if draft.category in ("A", "B") and not rows:
        return _result("retry", checks + ["FAIL no Schedule row cited"], "SCHEDULE_CITATION_MISSING",
                       "A Category A or B opinion must cite the Schedule row it relies on.")
    if draft.category == "NO_CLEARANCE" and not (rows or any(c.chunk_id.startswith("para:2") or c.chunk_id.startswith("para:preamble") for c in cited)):
        return _result("retry", checks + ["FAIL no-clearance opinion cites neither a Schedule row nor paragraph 2"], "SCOPE_CITATION_MISSING",
                       "A no-clearance opinion must cite paragraph 2 or the Schedule row whose threshold is not met.")
    checks.append("PASS the governing Schedule row / scope paragraph is cited")

    entities = state.extracted_entities
    # The modifier checks concern the row that decides the category. A no-clearance opinion may
    # cite rows only to show the activity is NOT them, and the General Condition only moves
    # Category B to A, so those rows are not checked. When the draft names its Schedule item,
    # only that row governs.
    governing = []
    if draft.category in ("A", "B"):
        named = f"schedule:{draft.schedule_item}" if draft.schedule_item else None
        governing = [r for r in rows if r.chunk_id == named] or rows
    for row in governing:
        item = row.chunk_id.split(":", 1)[1]

        for modifier, relation in store.modifiers(row.chunk_id):
            if "NOT IN FORCE" in relation:
                return _result("escalate", checks + [f"ESCALATE {modifier.chunk_id} records an amendment to {item} as not in force"],
                               "AMENDMENT_CONFLICT")

        if row.metadata.get("gc_applies"):
            if "schedule:gc" not in retrieved:
                return _result("retry", checks + [f"FAIL row {item} says the General Condition applies but it was never retrieved"],
                               "MODIFIERS_NOT_CHECKED",
                               f"Schedule item {item} states 'General Condition shall apply'. Call find_modifiers on {row.chunk_id} and apply the General Condition before deciding.")
            gc = retrieved["schedule:gc"]
            in_proviso = item in gc.metadata.get("references", [])
            distance = THRESHOLDS["general_condition"]["proviso_distance_km" if in_proviso else "default_distance_km"]
            triggers = gc_triggers(entities, distance) if entities else []
            if triggers and draft.category == "B":
                return _result("retry", checks + [f"FAIL GC distance {distance:g} km is met ({'; '.join(triggers)}) but the draft says Category B"],
                               "GENERAL_CONDITION_IGNORED",
                               f"The project is {'; '.join(triggers)}, within the {distance:g} km of the General Condition for item {item}. Re-read schedule:gc.")
            if triggers and draft.category == "A" and "general condition" in draft.basis.lower() and "schedule:gc" not in draft.cited_chunk_ids:
                return _result("retry", checks + ["FAIL Category A via the General Condition without citing it"], "REQUIRED_CITATION_MISSING",
                               "The opinion relies on the General Condition: cite both the Schedule row and schedule:gc.")
            checks.append(f"PASS General Condition considered for {item} ({distance:g} km{' proviso' if in_proviso else ''}; triggers: {len(triggers)})")

    return _result("pass", checks)


def _llm_review(state: AgentState, draft: DraftDetermination) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Ask the verifier model whether the cited passages support the draft. Returns (verdict, error)."""
    gateway = get_gateway()
    prompt, prompt_hash = load_prompt("verifier", state.prompt_version)
    state.metadata.setdefault("prompt_hashes", {})["verifier"] = prompt_hash
    toolbox = ToolBox(state, agent="verifier", enabled=["get_clause", "search_corpus"])

    passages = {
        c.chunk_id: state.retrieved_chunks[c.chunk_id].text
        for c in draft.citations if c.chunk_id in state.retrieved_chunks
    }
    facts = state.extracted_entities.model_dump(exclude_none=True) if state.extracted_entities else {}
    content = "\n\n".join([
        f"<project_data>\n{json.dumps(facts, ensure_ascii=False)}\n</project_data>",
        f"Draft opinion:\n{json.dumps(draft.model_dump(exclude={'produced_by'}), ensure_ascii=False)}",
        f"Cited passages (full text):\n{json.dumps(passages, ensure_ascii=False)}",
    ])
    messages: List[Dict[str, Any]] = [{"role": "system", "content": prompt}, {"role": "user", "content": content}]

    tool_calls_used = 0
    for turn in range(1, VERIFIER_MAX_TURNS + 1):
        state.steps += 1
        state.llm_calls += 1
        # The last turn, or an exhausted tool allowance, offers no tools: the model must give its verdict
        final_turn = turn == VERIFIER_MAX_TURNS or tool_calls_used >= VERIFIER_MAX_TOOL_CALLS
        if final_turn and turn > 1:
            messages.append({"role": "user", "content": "Give your verdict now as the JSON object described in your instructions."})
        try:
            response = gateway.complete(messages, toolbox.schemas(), agent="verifier",
                                        step=f"verifier.turn{turn}", prompt_version=state.prompt_version,
                                        tool_choice="none" if final_turn else "auto", deadline=state.deadline)
        except RunDeadlineExceeded:
            return None, "deadline"
        except LLMUnavailableError as error:
            return None, str(error)

        state.prompt_tokens += response["prompt_tokens"]
        state.completion_tokens += response["completion_tokens"]
        state.cost_usd += response["cost_usd"]
        state.usage_by_step.append({
            "agent": "verifier", "step": f"turn{turn}", "model": response["model"],
            "prompt_tokens": response["prompt_tokens"], "completion_tokens": response["completion_tokens"],
            "cost_usd": response["cost_usd"], "latency_ms": response["latency_ms"],
        })
        messages.append(response["raw_message"])

        if response["tool_calls"] and not final_turn:
            for call in response["tool_calls"]:
                if tool_calls_used >= VERIFIER_MAX_TOOL_CALLS:
                    result = {"error": "verifier tool allowance used; judge from the passages given"}
                else:
                    tool_calls_used += 1
                    try:
                        result = toolbox.execute(call["name"], call["arguments"])
                    except ToolBudgetExceeded as error:
                        result = {"error": str(error)}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
            continue

        verdict = extract_json_object(response["content"], expected_keys=("supported",))
        if verdict is None:
            return {"supported": False, "unsupported_claims": ["verifier reply was not valid JSON"]}, None
        return verdict, None

    return {"supported": False, "unsupported_claims": ["verifier did not reach a verdict"]}, None


def verify_draft(state: AgentState) -> AgentState:
    """Run the Verifier on state.draft_answer and set state.verification."""
    recorder = get_recorder()
    state.steps += 1
    draft = state.draft_answer

    with recorder.step("verify", agent="verifier", attempt=state.screener_attempts) as outcome:
        if draft is None:
            result = _result("escalate", ["FAIL no draft"], "NO_DRAFT")
        else:
            result = deterministic_checks(state, draft)
            if result.verdict == "pass" and not state.metadata.get("skip_llm_verifier"):
                review, error = _llm_review(state, draft)
                if error == "deadline":
                    result = _result("escalate", result.checks + ["FAIL run deadline reached before the review"], "LIMIT_WALL_CLOCK")
                elif error is not None:
                    state.llm_unavailable = True
                    result = _result("escalate", result.checks + [f"FAIL verifier model unavailable: {error[:200]}"], "VERIFIER_UNAVAILABLE")
                elif not review.get("supported", False):
                    problems = (review.get("unsupported_claims") or []) + (review.get("ignored_provisions") or [])
                    result = _result("retry", result.checks + [f"FAIL LLM review: {problems}"], "LLM_REVIEW_UNSUPPORTED",
                                     "The Verifier found claims the cited passages do not support: " + "; ".join(map(str, problems)))
                else:
                    result.checks.append(f"PASS LLM review: {review.get('comment', 'supported')}")

        state.verification = result
        outcome.update(verdict=result.verdict, reason=result.reason or "")

    VERIFICATION_OUTCOMES_TOTAL.labels(verdict=result.verdict, reason=result.reason or "ok").inc()
    AGENT_TASKS_TOTAL.labels(agent="verifier", outcome=result.verdict).inc()
    recorder.event("verification", agent="verifier", attempt=state.screener_attempts, **result.model_dump())
    return state
