import json
import uuid
from pathlib import Path

import pytest

from tests.conftest import needs_index


pytestmark = needs_index

SCENARIOS = {s["id"]: s for s in json.loads((Path(__file__).parent.parent / "eval" / "scenarios.json").read_text())}


def run(scenario_id, **kwargs):
    from agent.runner import run_screening
    from api.contract import ScreeningSubmission
    from api.worker import build_request
    from observability.recorder import RunRecorder

    run_id = f"test_{uuid.uuid4().hex[:6]}"
    request = build_request(ScreeningSubmission(**SCENARIOS[scenario_id]["payload"]).model_dump(exclude_none=True), run_id, run_id)
    recorder = RunRecorder(run_id, run_id)
    return run_screening(request, run_id, run_id, recorder=recorder, **kwargs), recorder


def test_index_links_schedule_row_to_general_condition():
    from agent.retrieval.store import get_store
    store = get_store()
    row = store.get("schedule:3(b)")
    assert row.metadata["gc_applies"] is True
    relations = dict((c.chunk_id, r) for c, r in store.modifiers("schedule:3(b)"))
    assert "schedule:gc" in relations
    assert "1(d)" in store.get("schedule:gc").metadata["references"]
    assert store.get("footnote:92").metadata["in_force"] is False


def test_section_4_1_cites_schedule_row_and_general_condition():
    final, recorder = run("RC-1")
    assert final.status == "answered"
    assert final.draft_answer.route == "category_a_central"
    assert {"schedule:3(b)", "schedule:gc"} <= set(final.draft_answer.cited_chunk_ids)
    assert final.verification.passed
    assert any(e["kind"] == "tool_call" and e["tool"] == "find_modifiers" for e in recorder.events)


@pytest.mark.parametrize("scenario_id", ["RC-2", "RC-5", "RC-7", "RC-9", "RC-21", "RC-24", "RC-26"])
def test_expected_outcomes(scenario_id):
    final, _ = run(scenario_id)
    expected = SCENARIOS[scenario_id]
    if expected["expected_status"] == "answered":
        assert final.status == "answered" and final.draft_answer.route == expected["expected_route"]
    else:
        assert final.status == "escalated" and final.escalation.reason_code == expected["expected_reason"]


def test_injection_is_stopped_before_any_model_call():
    final, _ = run("RC-10")
    assert final.escalation.reason_code == "PROMPT_INJECTION_DETECTED"
    assert final.llm_calls == 0 and final.tool_calls == 0


def test_verifier_rejects_a_fabricated_quote():
    from agent.agents.verifier import deterministic_checks
    from agent.state import Citation

    final, _ = run("RC-1")
    draft = final.draft_answer.model_copy(deep=True)
    draft.citations[0] = Citation(chunk_id="schedule:3(b)", quote="Cement plants are always Category B")
    assert deterministic_checks(final, draft).reason == "QUOTE_NOT_FOUND"


def test_verifier_rejects_category_b_when_general_condition_distance_is_met():
    from agent.agents.verifier import deterministic_checks

    final, _ = run("RC-1")
    draft = final.draft_answer.model_copy(deep=True)
    draft.category, draft.route = "B", "category_b_state"
    assert deterministic_checks(final, draft).reason == "GENERAL_CONDITION_IGNORED"


def test_without_find_modifiers_the_verifier_forces_another_search():
    final, recorder = run("RC-1", enabled_tools=["search_corpus", "get_clause", "get_request_fields"])
    verdicts = [e["verdict"] for e in recorder.events if e["kind"] == "verification"]
    assert verdicts[0] == "retry" and verdicts[-1] == "pass"
    assert final.draft_answer.route == "category_a_central"


def test_provider_outage_degrades_and_escalates():
    from agent import chaos
    chaos.set_llm_down(True)
    try:
        final, _ = run("RC-1")
    finally:
        chaos.set_llm_down(False)
    assert final.mode == "degraded"
    assert final.status == "escalated" and final.escalation.reason_code == "PROVIDER_UNAVAILABLE"
    assert final.provisional_opinion is not None


def test_no_clearance_may_cite_a_row_it_rules_out_without_modifier_checks():
    from agent.agents.verifier import deterministic_checks
    from agent.state import Citation

    final, _ = run("RC-24")
    draft = final.draft_answer.model_copy(deep=True)
    row = final.retrieved_chunks.get("schedule:1(d)") or __import__("agent.retrieval.store", fromlist=["get_store"]).get_store().get("schedule:1(d)")
    final.retrieved_chunks[row.chunk_id] = row
    draft.citations.append(Citation(chunk_id="schedule:1(d)", quote="Thermal Power Plants"))
    assert deterministic_checks(final, draft).verdict == "pass"
