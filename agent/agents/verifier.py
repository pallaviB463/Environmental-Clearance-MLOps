from agent.state import AgentState, VerificationResult


def verify_answer(state: AgentState) -> AgentState:
    """
    Verify the analyst's draft determination (Requirement A3).

    Deterministic checks:
    1. A draft answer exists.
    2. Every cited chunk was retrieved during THIS run.
    3. Every cited chunk can be resolved from retrieved_chunks.
    4. Category A due to a General Condition must cite BOTH
       a Schedule provision and a General Condition.
    5. Route must agree with the drafted category.
    6. Ensures unverified answers never return confident status.
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
    # CHECK 3: Every citation must resolve to text from THIS run
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
                "FAIL: One or more citations were not retrieved during this run.",
                f"Missing citations: {missing_citations}"
            ],
            reason="CITATION_NOT_RETRIEVED"
        )
        return state

    checks.append(
        "PASS: Every citation resolves to a chunk retrieved during this run."
    )

    # --------------------------------------------------
    # CHECK 4: Category A via General Condition citation completeness
    # --------------------------------------------------
    cited_chunks = [
        state.retrieved_chunks[chunk_id]
        for chunk_id in draft.cited_chunk_ids
    ]

    has_schedule = any(
        "schedule" in chunk.section.lower() or "schedule:" in chunk.chunk_id.lower()
        for chunk in cited_chunks
    )

    has_general_condition = any(
        "general condition" in chunk.section.lower() or "gc" in chunk.chunk_id.lower()
        for chunk in cited_chunks
    )

    # If basis mentions General Condition or proximity modification was applied:
    if "general condition" in draft.basis.lower() and draft.category == "A":
        if not has_schedule or not has_general_condition:
            state.verification = VerificationResult(
                passed=False,
                verdict="retry",
                checks=checks + [
                    "FAIL: Category A determination via General Condition must cite both the Schedule entry and General Condition."
                ],
                reason="REQUIRED_CITATION_MISSING"
            )
            return state

        checks.append(
            "PASS: Category A determination via General Condition cites both Schedule and General Condition."
        )
    else:
        if not has_schedule:
            state.verification = VerificationResult(
                passed=False,
                verdict="retry",
                checks=checks + [
                    "FAIL: Determination does not cite an applicable Schedule entry."
                ],
                reason="SCHEDULE_CITATION_MISSING"
            )
            return state
        checks.append("PASS: Determination cites applicable Schedule entry.")

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

    checks.append("PASS: Category and route are consistent.")

    # --------------------------------------------------
    # ALL CHECKS PASSED
    # --------------------------------------------------
    state.verification = VerificationResult(
        passed=True,
        verdict="pass",
        checks=checks,
        reason=None
    )
    return state