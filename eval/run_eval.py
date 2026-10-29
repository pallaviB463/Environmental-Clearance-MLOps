"""
Batch evaluation from the command line (Requirements L2 / L3).

    python -m eval.run_eval                                   # current PROMPT_VERSION
    python -m eval.run_eval --compare v1 v2                   # L2: two prompt variants, same set
    python -m eval.run_eval --change no_find_modifiers        # L3: one deliberate change, before/after
    python -m eval.run_eval --only RC-1 RC-26 --judge llm     # subset, with an LLM faithfulness judge

Every scenario is validated against the published data contract first, then run through
the same runner the worker uses (agent.runner.run_screening), with whatever LLM is
configured. Metric definitions are in eval/metrics.py. Reports go to eval/reports/.
"""
import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.config import settings
from agent.retrieval.store import warm_up
from agent.runner import run_screening
from api.contract import ScreeningSubmission
from api.worker import build_request
from eval import metrics
from observability.recorder import RunRecorder


EVAL_DIR = Path(__file__).resolve().parent
SCENARIOS = EVAL_DIR / "scenarios.json"
REPORTS = EVAL_DIR / "reports"

# Deliberate changes for L3 (one variable at a time)
CHANGES = {
    "none": {},
    "no_find_modifiers": {"enabled_tools": ["search_corpus", "get_clause", "get_request_fields"]},
    "no_llm_verifier": {"skip_llm_verifier": True},
}


def _mean(values: List[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(statistics.mean(present), 4) if present else None


def _p95(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 3)


def run_scenario(scenario: Dict[str, Any], prompt_version: str, change: str, judge: Optional[str]) -> Dict[str, Any]:
    submission = ScreeningSubmission(**scenario["payload"])  # contract check: raises if the scenario is malformed
    run_id = f"eval_{scenario['id']}_{uuid.uuid4().hex[:6]}"
    request = build_request(submission.model_dump(exclude_none=True), run_id, run_id)
    recorder = RunRecorder(run_id, run_id)

    started = time.time()
    final = run_screening(request, run_id, run_id, prompt_version=prompt_version, recorder=recorder, **CHANGES[change])
    latency = time.time() - started

    supporting = scenario.get("supporting_passages", [])
    actual_route = final.draft_answer.route if final.status == "answered" and final.draft_answer else "escalate_to_human"
    actual_reason = final.escalation.reason_code if final.escalation else None

    if scenario["expected_status"] == "answered":
        correct = final.status == "answered" and actual_route == scenario["expected_route"]
    else:
        correct = final.status == "escalated" and actual_reason == scenario.get("expected_reason")
    safe = not (scenario["expected_status"] == "escalated" and final.status == "answered")

    answered = final.status == "answered"
    faithful = metrics.faithful(final) if answered else None
    if answered and judge == "llm" and faithful:
        from eval.judge import judge_entailment
        faithful = judge_entailment(final)

    return {
        "id": scenario["id"],
        "name": scenario["name"],
        "expected": scenario.get("expected_route") or f"escalate:{scenario.get('expected_reason')}",
        "actual": actual_route if answered else f"escalate:{actual_reason}",
        "status": final.status,
        "mode": final.mode,
        "correct": correct,
        "safe": safe,
        "groundedness": metrics.groundedness(final) if answered else None,
        "context_relevance": metrics.context_relevance(final, supporting) if final.retrieved_chunks else None,
        "context_recall": metrics.context_recall(final, supporting) if supporting else None,
        "faithful": faithful,
        "fabricated_evidence": metrics.has_fabricated_evidence(final) if final.draft_answer else False,
        "verification_retries": final.verification_retries,
        "steps": final.steps,
        "tool_calls": final.tool_calls,
        "llm_calls": final.llm_calls,
        "prompt_tokens": final.prompt_tokens,
        "completion_tokens": final.completion_tokens,
        "cost_usd": round(final.cost_usd, 6),
        "latency_s": round(latency, 3),
        "cited": final.draft_answer.cited_chunk_ids if final.draft_answer else [],
        "retrieved": sorted(final.retrieved_chunks),
    }


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    answered = [r for r in rows if r["status"] == "answered"]
    with_draft = [r for r in rows if r["cited"]]
    total_cost = sum(r["cost_usd"] for r in rows)
    return {
        "scenarios": len(rows),
        "route_accuracy": round(sum(r["correct"] for r in rows) / len(rows), 4),
        "unsafe_answers": sum(not r["safe"] for r in rows),
        "groundedness": _mean([r["groundedness"] for r in answered]),
        "context_relevance": _mean([r["context_relevance"] for r in rows]),
        "context_recall": _mean([r["context_recall"] for r in rows]),
        "faithfulness": _mean([None if r["faithful"] is None else float(r["faithful"]) for r in answered]),
        "hallucination_rate": round(sum(r["fabricated_evidence"] for r in with_draft) / len(with_draft), 4) if with_draft else 0.0,
        "verification_retry_rate": round(sum(r["verification_retries"] > 0 for r in rows) / len(rows), 4),
        "mean_steps": _mean([r["steps"] for r in rows]),
        "mean_tool_calls": _mean([r["tool_calls"] for r in rows]),
        "mean_llm_calls": _mean([r["llm_calls"] for r in rows]),
        "latency_p50_s": round(statistics.median(r["latency_s"] for r in rows), 3),
        "latency_p95_s": _p95([r["latency_s"] for r in rows]),
        "cost_per_100_runs_usd": round(total_cost / len(rows) * 100, 4),
        "tokens_per_run": round(sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows) / len(rows), 1),
    }


def run_batch(scenarios, prompt_version: str, change: str, judge: Optional[str], label: str) -> Dict[str, Any]:
    print(f"\n=== {label}: prompt {prompt_version}, change '{change}', provider {settings.llm_provider} ({settings.llm_model}) ===")
    rows = []
    for scenario in scenarios:
        row = run_scenario(scenario, prompt_version, change, judge)
        rows.append(row)
        mark = "PASS" if row["correct"] else "FAIL"
        print(f"[{mark}] {row['id']:6s} expected {row['expected']:32s} got {row['actual']:32s} "
              f"steps={row['steps']:2d} tools={row['tool_calls']} {row['latency_s']:.1f}s")
    summary = summarise(rows)
    print(json.dumps(summary, indent=2))
    return {"label": label, "prompt_version": prompt_version, "change": change, "summary": summary, "rows": rows}


def comparison_table(a: Dict, b: Dict) -> str:
    keys = ["route_accuracy", "groundedness", "context_relevance", "context_recall", "faithfulness",
            "hallucination_rate", "unsafe_answers", "verification_retry_rate", "mean_llm_calls",
            "latency_p95_s", "cost_per_100_runs_usd"]
    lines = [f"| metric | {a['label']} | {b['label']} | change |", "|---|---|---|---|"]
    for key in keys:
        va, vb = a["summary"].get(key), b["summary"].get(key)
        delta = round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
        lines.append(f"| {key} | {va} | {vb} | {delta:+} |" if delta != "" else f"| {key} | {va} | {vb} | |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval")
    parser.add_argument("--prompt", default=settings.prompt_version, help="prompt version for a single run")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"), help="compare two prompt versions (L2)")
    parser.add_argument("--change", choices=[c for c in CHANGES if c != "none"],
                        help="run before/after one deliberate change (L3)")
    parser.add_argument("--only", nargs="+", help="scenario ids to run")
    parser.add_argument("--judge", choices=["none", "llm"], default="none", help="add an LLM faithfulness judge")
    args = parser.parse_args()

    scenarios = json.loads(SCENARIOS.read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    judge = None if args.judge == "none" else args.judge

    print(f"warming index ... {warm_up():.1f}s")
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.compare:
        a = run_batch(scenarios, args.compare[0], "none", judge, f"prompt {args.compare[0]}")
        b = run_batch(scenarios, args.compare[1], "none", judge, f"prompt {args.compare[1]}")
        name, results = f"compare_{args.compare[0]}_{args.compare[1]}", [a, b]
    elif args.change:
        a = run_batch(scenarios, args.prompt, "none", judge, "before")
        b = run_batch(scenarios, args.prompt, args.change, judge, f"after ({args.change})")
        name, results = f"change_{args.change}", [a, b]
    else:
        results = [run_batch(scenarios, args.prompt, "none", judge, f"prompt {args.prompt}")]
        name = f"single_{args.prompt}"

    report = {
        "generated_at": stamp,
        "provider": settings.llm_provider,
        "models": [m for m in (settings.llm_model, settings.llm_fallback_model) if m],
        "judge": args.judge,
        "results": results,
    }
    out = REPORTS / f"{stamp}_{name}.json"
    out.write_text(json.dumps(report, indent=2))

    if len(results) == 2:
        table = comparison_table(*results)
        print("\n" + table)
        (REPORTS / f"{stamp}_{name}.md").write_text(
            f"# {name}\n\nProvider: {settings.llm_provider} {report['models']}, judge: {args.judge}\n\n{table}\n")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
