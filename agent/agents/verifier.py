from agent.state import AgentState, VerificationResult


def verify_answer(state: AgentState) -> AgentState:
    """
    Verify the analyst's draft determination.

    Current deterministic checks:
    1. A draft answer exists.
    2. Every cited chunk was retrieved during THIS run.
    3. Every cited chunk can be resolved from retrieved_chunks.
    4. Category A due to a General Condition must cite both
       a Schedule provision and a General Condition.
    5. Route must agree with the drafted category.

    Later:
    - Exact quote verification
    - Rule recomputation using confirmed corpus rules
    - LLM-based claim-support check
    """

    state.steps += 1

    draft = state.draft_answer

    # --------------------------------------------------
    # CHECK 1: Draft exists
    # --------------------------------------------------

    if draft is None:
        state.verification = VerificationResult(
            passed=False,
            verdict="escalate",
            checks=["FAIL: No draft answer exists."],
            reason="NO_DRAFT"
        )
        return state

    checks = []

    # --------------------------------------------------
    # CHECK 2: Citations must exist
    # --------------------------------------------------

    if not draft.cited_chunk_ids:
        state.verification = VerificationResult(
            passed=False,
            verdict="retry",
            checks=["FAIL: Draft contains no citations."],
            reason="NO_CITATIONS"
        )
        return state

    # --------------------------------------------------
    # CHECK 3: Every citation must come from THIS run
    # --------------------------------------------------

    missing_citations = []

    for chunk_id in draft.cited_chunk_ids:
        if chunk_id not in state.retrieved_chunks:
            missing_citations.append(chunk_id)

    if missing_citations:
        state.verification = VerificationResult(
            passed=False,
            verdict="retry",
            checks=[
                "FAIL: One or more citations were not retrieved "
                "during this run.",
                f"Missing citations: {missing_citations}"
            ],
            reason="CITATION_NOT_RETRIEVED"
        )
        return state

    checks.append(
        "PASS: Every citation resolves to a chunk retrieved "
        "during this run."
    )

    # --------------------------------------------------
    # CHECK 4:
    # Category A caused by General Condition must cite:
    #
    # Schedule + General Condition
    # --------------------------------------------------

    if draft.category == "A":

        cited_chunks = [
            state.retrieved_chunks[chunk_id]
            for chunk_id in draft.cited_chunk_ids
        ]

        has_schedule = any(
            chunk.section.lower() == "schedule"
            for chunk in cited_chunks
        )

        has_general_condition = any(
            chunk.section.lower() == "general condition"
            for chunk in cited_chunks
        )

        if not has_schedule or not has_general_condition:
            state.verification = VerificationResult(
                passed=False,
                verdict="retry",
                checks=checks + [
                    "FAIL: Category A determination does not cite "
                    "both the Schedule and General Condition."
                ],
                reason="REQUIRED_CITATION_MISSING"
            )
            return state

        checks.append(
            "PASS: Category A determination cites both the "
            "Schedule and General Condition."
        )

    # --------------------------------------------------
    # CHECK 5: Category and route must agree
    # --------------------------------------------------

    expected_routes = {
        "A": "category_a_central",
        "B": "category_b_state",
        "NO_CLEARANCE": "no_clearance"
    }

    expected_route = expected_routes.get(draft.category)

    if expected_route != draft.route:
        state.verification = VerificationResult(
            passed=False,
            verdict="retry",
            checks=checks + [
                "FAIL: Draft category and route are inconsistent."
            ],
            reason="CATEGORY_ROUTE_MISMATCH"
        )
        return state

    checks.append(
        "PASS: Category and route are consistent."
    )

    # --------------------------------------------------
    # ALL CURRENT CHECKS PASSED
    # --------------------------------------------------

    state.verification = VerificationResult(
        passed=True,
        verdict="pass",
        checks=checks,
        reason=None
    )

    return state