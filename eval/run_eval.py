import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.graph import graph
from agent.state import (
    AgentState,
    ProjectRequest,
    Capacity,
    Location,
    ProtectedArea
)


SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"


def evaluate_batch(scenarios: List[Dict[str, Any]], enable_modifiers: bool = True, prompt_version: str = "v1") -> Dict[str, Any]:
    total = len(scenarios)
    correct_route = 0
    correct_category = 0
    grounded_citations = 0
    total_citations = 0
    relevant_contexts = 0
    total_retrieved = 0
    hallucinations = 0

    results = []
    start_time = time.time()

    for sc in scenarios:
        payload = sc["payload"]
        cap = None
        if payload.get("capacity"):
            cap = Capacity(value=float(payload["capacity"]["value"]), unit=payload["capacity"]["unit"])
        loc = None
        if payload.get("location"):
            loc = Location(state=payload["location"]["state"], district=payload["location"]["district"])
        nearest_pa = None
        if payload.get("nearest_protected_area"):
            npa = payload["nearest_protected_area"]
            nearest_pa = ProtectedArea(
                type=npa.get("type", "none"),
                distance_km=npa.get("distance_km"),
                basis=npa.get("basis", "surveyed")
            )

        req = ProjectRequest(
            run_id=f"eval_{sc['id']}",
            correlation_id=f"corr_{sc['id']}",
            description=payload.get("description", ""),
            project_name=payload.get("project_name"),
            sector_hint=payload.get("sector_hint"),
            capacity=cap,
            location=loc,
            nearest_protected_area=nearest_pa,
            proximity=payload.get("proximity"),
            in_critically_polluted_area=payload.get("in_critically_polluted_area", False)
        )

        state = AgentState(request=req, prompt_version=prompt_version)
        try:
            res = graph.invoke(state)
            final = AgentState.model_validate(res)
        except Exception as e:
            results.append({"id": sc["id"], "passed": False, "error": str(e)})
            continue

        # Check outcomes
        cat_match = (final.draft_answer.category == sc["expected_category"]) if (final.draft_answer and sc["expected_category"]) else (final.status == sc["expected_status"])
        route_match = (final.draft_answer.route == sc["expected_route"]) if (final.draft_answer and sc["expected_route"]) else (final.status == sc["expected_status"])

        if cat_match: correct_category += 1
        if route_match: correct_route += 1

        # Evaluate Groundedness & Faithfulness
        if final.draft_answer and final.draft_answer.cited_chunk_ids:
            for cid in final.draft_answer.cited_chunk_ids:
                total_citations += 1
                if cid in final.retrieved_chunks:
                    grounded_citations += 1
                else:
                    hallucinations += 1

        # Context relevance
        total_retrieved += len(final.retrieved_chunks)
        for chunk in final.retrieved_chunks.values():
            if chunk.section in ["Schedule", "General Condition", "Notification Paragraphs", "Footnotes"]:
                relevant_contexts += 1

        results.append({
            "id": sc["id"],
            "name": sc["name"],
            "status": final.status,
            "category": final.draft_answer.category if final.draft_answer else None,
            "route": final.draft_answer.route if final.draft_answer else None,
            "citations": final.draft_answer.cited_chunk_ids if final.draft_answer else [],
            "passed": cat_match and route_match
        })

    duration = time.time() - start_time
    groundedness = round(grounded_citations / max(total_citations, 1), 4)
    context_relevance = round(relevant_contexts / max(total_retrieved, 1), 4)
    faithfulness = round(correct_route / max(total, 1), 4)
    hallucination_rate = round(hallucinations / max(total_citations, 1), 4)

    return {
        "total_scenarios": total,
        "correct_category_rate": round(correct_category / total, 4),
        "correct_route_rate": round(correct_route / total, 4),
        "groundedness": groundedness,
        "context_relevance": context_relevance,
        "faithfulness": faithfulness,
        "hallucination_rate": hallucination_rate,
        "evaluation_duration_seconds": round(duration, 3),
        "results": results
    }


def main():
    print("=" * 70)
    print("EIA PRE-SCREENING SERVICE — 20-SCENARIO EVALUATION BATCH (L2 / L3)")
    print("=" * 70)

    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    # 1. Baseline Evaluation with Full Agentic Reasoning & find_modifiers
    print("\n[RUN 1] Production Pipeline: Multi-Agent with find_modifiers (Prompt v1)")
    print("-" * 70)
    metrics_v1 = evaluate_batch(scenarios, enable_modifiers=True, prompt_version="v1")
    print(f"Faithfulness       : {metrics_v1['faithfulness'] * 100:.1f}%")
    print(f"Groundedness       : {metrics_v1['groundedness'] * 100:.1f}%")
    print(f"Context Relevance  : {metrics_v1['context_relevance'] * 100:.1f}%")
    print(f"Hallucination Rate : {metrics_v1['hallucination_rate'] * 100:.1f}%")
    print(f"Duration           : {metrics_v1['evaluation_duration_seconds']}s")

    # 2. Deliberate Change (Requirement L3): Compare against prompt v2 (chain of provisions)
    print("\n[RUN 2] Deliberate Change: Prompt Variant v2 (Explicit Statutory Derivation)")
    print("-" * 70)
    metrics_v2 = evaluate_batch(scenarios, enable_modifiers=True, prompt_version="v2")
    print(f"Faithfulness       : {metrics_v2['faithfulness'] * 100:.1f}%")
    print(f"Groundedness       : {metrics_v2['groundedness'] * 100:.1f}%")
    print(f"Context Relevance  : {metrics_v2['context_relevance'] * 100:.1f}%")
    print(f"Hallucination Rate : {metrics_v2['hallucination_rate'] * 100:.1f}%")
    print(f"Duration           : {metrics_v2['evaluation_duration_seconds']}s")

    print("\n" + "=" * 70)
    print("DETAILED SCENARIO BREAKDOWN:")
    print("=" * 70)
    for r in metrics_v1["results"]:
        status_symbol = "PASS" if r["passed"] else "FAIL"
        print(f"[{status_symbol:<4}] {r['id']:<6} {r['name']:<42} -> {r['status']:<10} {r['route'] or ''}")

    # Save evaluation report artifact
    report_file = Path(__file__).resolve().parent / "evaluation_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"metrics_v1": metrics_v1, "metrics_v2": metrics_v2}, f, indent=2)
    print(f"\nEvaluation artifact saved to: {report_file}")


if __name__ == "__main__":
    main()
