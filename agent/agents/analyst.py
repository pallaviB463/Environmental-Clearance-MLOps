from agent.state import (
    AgentState,
    DraftDetermination,
    Escalation
)

from agent.tools.search_corpus import search_corpus


def analyse_provisions(state: AgentState) -> AgentState:
    """
    First working version of the Provision Analyst.

    Workflow:
    1. Read extracted project entities.
    2. Search for the applicable Schedule provision.
    3. If Schedule indicates Category B, search for modifiers.
    4. If protected-area proximity exists and a General Condition
       is retrieved, draft Category A.
    5. Otherwise draft Category B.
    """

    state.steps += 1

    entities = state.extracted_entities

    # --------------------------------------------------
    # Safety check
    # --------------------------------------------------

    if entities is None:
        state.status = "failed"
        state.escalation = Escalation(
            reason_code="EXTRACTION_FAILED",
            detail="Provision Analyst received no extracted entities."
        )
        return state

    # --------------------------------------------------
    # F7: Do not guess missing proximity
    # --------------------------------------------------

    if (
        entities.protected_area_type
        and entities.protected_area_distance_km is None
    ):
        state.status = "escalated"

        state.escalation = Escalation(
            reason_code="PROXIMITY_UNCERTAIN",
            detail=(
                "A protected area was identified but its distance "
                "from the proposed project is unknown. Human review "
                "is required."
            )
        )

        return state

    # --------------------------------------------------
    # F7: Unknown sector
    # --------------------------------------------------

    if not entities.sector:
        state.status = "escalated"

        state.escalation = Escalation(
            reason_code="OUT_OF_CORPUS",
            detail="Project sector could not be determined."
        )

        return state

    # --------------------------------------------------
    # SEARCH 1: Schedule
    # --------------------------------------------------

    schedule_query = (
        f"{entities.sector} project Schedule"
    )

    schedule_results = search_corpus(
        query=schedule_query,
        k=5,
        filters={"section": "Schedule"}
    )

    state.tool_calls += 1

    if not schedule_results:
        state.status = "escalated"

        state.escalation = Escalation(
            reason_code="OUT_OF_CORPUS",
            detail=(
                f"No Schedule provision was found for sector "
                f"'{entities.sector}'."
            )
        )

        return state

    # First result = best matching Schedule provision
    schedule_chunk = schedule_results[0]

    state.retrieved_chunks[
        schedule_chunk.chunk_id
    ] = schedule_chunk

    # --------------------------------------------------
    # First provisional determination
    #
    # Our TEST stub Schedule row contains Category B.
    # This is NOT the final legal rule implementation.
    # --------------------------------------------------

    schedule_text = schedule_chunk.text.lower()

    schedule_category_b = "category b" in schedule_text

    # --------------------------------------------------
    # SEARCH 2: Look explicitly for modifying provisions
    # --------------------------------------------------

    if schedule_category_b:

        modifier_query = (
            "Category B protected area General Condition "
            "modifying provision"
        )

        modifier_results = search_corpus(
            query=modifier_query,
            k=5
        )

        state.tool_calls += 1

        for chunk in modifier_results:
            state.retrieved_chunks[
                chunk.chunk_id
            ] = chunk

        general_condition = None

        for chunk in modifier_results:
            if chunk.section.lower() == "general condition":
                general_condition = chunk
                break

        # --------------------------------------------------
        # Development rule for our stub case
        #
        # IMPORTANT:
        # We are NOT hardcoding the real legal distance.
        # Person 2 must later provide the confirmed GC text/rule.
        # --------------------------------------------------

        protected_area_known = (
            entities.protected_area_type is not None
            and entities.protected_area_type != "unknown"
        )

        proximity_known = (
            entities.protected_area_distance_km is not None
        )

        if (
            general_condition is not None
            and protected_area_known
            and proximity_known
        ):
            state.draft_answer = DraftDetermination(
                category="A",
                route="category_a_central",
                basis=(
                    "The Schedule provision initially indicates "
                    "Category B, but a General Condition modifying "
                    "provision was retrieved for a project with "
                    "protected-area proximity. This is a development "
                    "stub determination pending the confirmed corpus rule."
                ),
                cited_chunk_ids=[
                    schedule_chunk.chunk_id,
                    general_condition.chunk_id
                ]
            )

            return state

    # --------------------------------------------------
    # No applicable modifier found
    # --------------------------------------------------

    if schedule_category_b:
        state.draft_answer = DraftDetermination(
            category="B",
            route="category_b_state",
            basis=(
                "The retrieved Schedule provision indicates "
                "Category B and no applicable modifying provision "
                "was established by the current development corpus."
            ),
            cited_chunk_ids=[
                schedule_chunk.chunk_id
            ]
        )

        return state

    # --------------------------------------------------
    # Could not interpret retrieved provision safely
    # --------------------------------------------------

    state.status = "escalated"

    state.escalation = Escalation(
        reason_code="OUT_OF_CORPUS",
        detail=(
            "A Schedule provision was retrieved, but the current "
            "development logic could not determine its category safely."
        )
    )

    return state