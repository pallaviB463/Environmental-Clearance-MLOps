"""
Run one screening in-process (no server, no Redis) and print the result and its trace.

    python run_local.py                 # the PS 4.1 case
    python run_local.py RC-26           # any scenario id from eval/scenarios.json
"""
import json
import sys
import uuid
from pathlib import Path

from agent.config import settings
from agent.retrieval.store import warm_up
from agent.runner import run_screening
from api.contract import ScreeningSubmission
from api.worker import build_request
from observability.recorder import RunRecorder


def main() -> int:
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "RC-1"
    scenarios = {s["id"]: s for s in json.loads(Path("eval/scenarios.json").read_text())}
    scenario = scenarios[scenario_id]

    print(f"{scenario_id}: {scenario['name']}")
    print(f"provider={settings.llm_provider} model={settings.llm_model} prompt={settings.prompt_version}")
    warm_up()

    run_id = f"local_{uuid.uuid4().hex[:6]}"
    recorder = RunRecorder(run_id, run_id)
    request = build_request(ScreeningSubmission(**scenario["payload"]).model_dump(exclude_none=True), run_id, run_id)
    final = run_screening(request, run_id, run_id, recorder=recorder)

    print("\nTRACE")
    for e in recorder.events:
        what = e.get("tool") or e.get("step") or ""
        extra = e.get("returned_chunk_ids") or e.get("verdict") or e.get("outcome") or ""
        print(f"  +{e['t_offset_ms']:>8}ms {e['kind']:<14} {e.get('agent', ''):<16} {what:<28} {extra}")

    print(f"\nSTATUS {final.status} (mode {final.mode}) steps={final.steps} tool_calls={final.tool_calls} "
          f"llm_calls={final.llm_calls} tokens={final.prompt_tokens}+{final.completion_tokens} cost=${final.cost_usd:.5f}")
    if final.status == "answered":
        d = final.draft_answer
        print(f"{d.category} -> {d.route} (Schedule item {d.schedule_item})\n{d.basis}")
        for c in d.citations:
            print(f"  [{c.chunk_id}] \"{c.quote.strip()[:90]}\"")
    if final.escalation:
        print(f"ESCALATED {final.escalation.reason_code}: {final.escalation.detail}")
    expected = scenario.get("expected_route") or f"escalate:{scenario.get('expected_reason')}"
    print(f"\nexpected: {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
