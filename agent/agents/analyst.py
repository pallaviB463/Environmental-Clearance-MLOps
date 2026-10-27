from agent.state import (
    AgentState,
    DraftDetermination,
    Escalation
)
from agent.tools.search_corpus import search_corpus
from agent.tools.find_modifiers import find_modifiers
from agent.tools.get_clause import get_clause


def analyse_provisions(state: AgentState) -> AgentState:
    """
    Provision Analyst (Screener reasoning):
    1. Evaluates out-of-corpus, uncertain-proximity, and conflict escalation boundaries (F7).
    2. Searches for applicable Schedule provision (F3/F4).
    3. Evaluates project capacity against statutory thresholds.
    4. Deterministically searches for modifying provisions (General Condition).
    5. Drafts category determination citing exact retrieved provisions (F5/F6 / Section 4.1).
    """
    state.steps += 1
    entities = state.extracted_entities

    if entities is None:
        state.status = "failed"
        state.escalation = Escalation(
            reason_code="EXTRACTION_FAILED",
            detail="Provision Analyst received no extracted entities."
        )
        return state

    # --------------------------------------------------
    # F7: Out of corpus escalation (e.g., RC-9 CRZ / Beach resort)
    # --------------------------------------------------
    if entities.sector == "crz_coastal" or "crz" in (state.request.description or "").lower():
        crz_clause = get_clause("crz_jurisdiction_note")
        if crz_clause:
            state.retrieved_chunks[crz_clause.chunk_id] = crz_clause
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="OUT_OF_CORPUS",
            detail=(
                "Project falls under Coastal Regulation Zone (CRZ) Notification, "
                "which is outside the EIA Notification 2006 corpus. Escalated to human expert."
            )
        )
        return state

    # --------------------------------------------------
    # F7: Proximity uncertainty escalation (e.g., RC-8)
    # --------------------------------------------------
    if entities.protected_area_type and entities.protected_area_distance_km is None:
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="PROXIMITY_UNCERTAIN",
            detail=(
                "A protected area was identified but its distance is unknown. "
                "Human review is required."
            )
        )
        return state

    # If proximity basis is estimated and falls within 1 km margin of the 5.0 km threshold
    if (
        entities.protected_area_distance_km is not None
        and entities.proximity_basis == "estimated"
        and 4.0 <= entities.protected_area_distance_km <= 6.0
    ):
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="PROXIMITY_UNCERTAIN",
            detail=(
                f"Proximity of {entities.protected_area_distance_km} km is estimated within "
                f"the critical 5 km statutory margin (+/- 1 km). Certified survey required."
            )
        )
        return state

    if not entities.sector:
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="OUT_OF_CORPUS",
            detail="Project sector could not be determined from corpus."
        )
        return state

    # --------------------------------------------------
    # F7: Amendment conflict escalation (e.g., RC-7 Item 8(a))
    # --------------------------------------------------
    if entities.sector == "construction":
        # Item 8(a) has quashed amendments recorded in footnote 92
        fn92 = get_clause("footnote:92_conflict")
        sch8a = get_clause("schedule:8(a)")
        if fn92:
            state.retrieved_chunks[fn92.chunk_id] = fn92
        if sch8a:
            state.retrieved_chunks[sch8a.chunk_id] = sch8a
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="AMENDMENT_CONFLICT",
            detail=(
                "Statutory amendment conflict: S.O. 3999(E) was quashed by NGT (Footnote 92). "
                "Escalating to accredited consultant."
            )
        )
        return state

    # --------------------------------------------------
    # SEARCH 1: Schedule provision
    # --------------------------------------------------
    schedule_query = f"{entities.sector} project Schedule"
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
            detail=f"No Schedule provision found for sector '{entities.sector}'."
        )
        return state

    schedule_chunk = schedule_results[0]
    state.retrieved_chunks[schedule_chunk.chunk_id] = schedule_chunk

    # --------------------------------------------------
    # Evaluate Schedule Thresholds
    # --------------------------------------------------
    # By default, check if threshold places it in Cat A or B
    capacity = entities.capacity_value or 0.0
    is_standalone_grinding = "grinding" in (state.request.description or "").lower()

    schedule_cat = "B"
    if entities.sector == "cement":
        if capacity >= 1.0 and not is_standalone_grinding:
            schedule_cat = "A"
        else:
            schedule_cat = "B"
    elif entities.sector == "power":
        if capacity >= 500.0:
            schedule_cat = "A"
        else:
            schedule_cat = "B"

    # If Category A from Schedule alone (e.g. RC-4: 1.2 MTPA cement plant)
    if schedule_cat == "A":
        para4_ii = get_clause("para:4(ii)")
        if para4_ii:
            state.retrieved_chunks[para4_ii.chunk_id] = para4_ii

        state.draft_answer = DraftDetermination(
            category="A",
            route="category_a_central",
            basis=(
                f"Project capacity ({capacity} {entities.capacity_unit or ''}) meets or exceeds "
                f"the Category A threshold under Schedule Item {schedule_chunk.clause}. "
                f"Appraised at Central level by MoEFCC on EAC recommendation."
            ),
            cited_chunk_ids=[
                schedule_chunk.chunk_id,
                para4_ii.chunk_id if para4_ii else schedule_chunk.chunk_id
            ]
        )
        return state

    # --------------------------------------------------
    # SEARCH 2: Search for Modifying Provisions (General Condition)
    # Addresses §4.1, L1, L3: find_modifiers tool
    # --------------------------------------------------
    modifiers = find_modifiers(schedule_chunk.chunk_id)
    state.tool_calls += 1

    general_condition = None
    for mod in modifiers:
        state.retrieved_chunks[mod.chunk_id] = mod
        if "general condition" in mod.section.lower() or "gc" in mod.chunk_id.lower():
            general_condition = mod

    # Fallback to search if not found in structured map
    if not general_condition:
        mod_results = search_corpus(
            query="Category B protected area General Condition modifying provision",
            k=3
        )
        state.tool_calls += 1
        for chunk in mod_results:
            state.retrieved_chunks[chunk.chunk_id] = chunk
            if "general condition" in chunk.section.lower():
                general_condition = chunk
                break

    # Determine applicable distance threshold (5 km standard, 10 km for proviso items like 1(d))
    gc_distance_limit = 5.0
    if entities.sector == "power" or "1(d)" in schedule_chunk.chunk_id:
        gc_distance_limit = 10.0

    # Check triggers:
    # Trigger (i): Protected area
    pa_dist = entities.protected_area_distance_km
    pa_triggered = pa_dist is not None and pa_dist <= gc_distance_limit

    # Trigger (iv): Interstate boundary (<= 5 km)
    is_dist = entities.interstate_distance_km
    is_triggered = is_dist is not None and is_dist <= 5.0

    # Trigger (ii): Critically polluted area
    cpa_triggered = bool(entities.in_critically_polluted_area)

    gc_applies = (pa_triggered or is_triggered or cpa_triggered) and (general_condition is not None)

    if gc_applies:
        # Category A Central via General Condition
        para4_ii = get_clause("para:4(ii)")
        if para4_ii:
            state.retrieved_chunks[para4_ii.chunk_id] = para4_ii

        trigger_reason = []
        if pa_triggered:
            trigger_reason.append(f"located {pa_dist} km (<= {gc_distance_limit} km) from a Protected Area")
        if is_triggered:
            trigger_reason.append(f"located {is_dist} km (<= 5.0 km) from an inter-State boundary")
        if cpa_triggered:
            trigger_reason.append("located in a Critically Polluted Area")

        trigger_text = " and ".join(trigger_reason)

        state.draft_answer = DraftDetermination(
            category="A",
            route="category_a_central",
            basis=(
                f"Schedule provision ({schedule_chunk.clause}) places project in Category B. "
                f"However, because the project is {trigger_text}, "
                f"the General Condition applies, upgrading appraisal to Central Level as Category A."
            ),
            cited_chunk_ids=[
                schedule_chunk.chunk_id,
                general_condition.chunk_id,
                para4_ii.chunk_id if para4_ii else schedule_chunk.chunk_id
            ]
        )
        return state

    # Otherwise Category B State route
    para4_iii = get_clause("para:4(iii)")
    if para4_iii:
        state.retrieved_chunks[para4_iii.chunk_id] = para4_iii

    state.draft_answer = DraftDetermination(
        category="B",
        route="category_b_state",
        basis=(
            f"Project is classified under Schedule Item {schedule_chunk.clause} as Category B. "
            f"No modifying provisions or General Condition triggers apply. "
            f"Appraisal requires clearance from State SEIAA under Paragraph 4(iii)."
        ),
        cited_chunk_ids=[
            schedule_chunk.chunk_id,
            para4_iii.chunk_id if para4_iii else schedule_chunk.chunk_id
        ]
    )
    return state