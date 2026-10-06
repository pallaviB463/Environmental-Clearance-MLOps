from agent.state import AgentState, ExtractedEntities, Escalation
from agent.tools.request_fields import get_request_fields
from agent.guardrails.injection import check_prompt_injection


def extract_entities(state: AgentState) -> AgentState:
    """
    Extract structured project information from the validated request.

    First development version:
    - Uses already validated structured fields.
    - Uses sector_hint when available.
    - Records missing important fields.
    """

    state.steps += 1

    request = state.request
    fields = get_request_fields(request)
        # ---------------------------------------------
    # INPUT GUARDRAIL
    # ---------------------------------------------

    injection_result = check_prompt_injection(
        request.description
    )

    state.metadata["injection_check"] = injection_result

    if not injection_result["safe"]:

        state.status = "escalated"

        state.escalation = Escalation(
            reason_code="PROMPT_INJECTION_DETECTED",
            detail=(
                "Potential prompt-injection instructions were "
                "detected in the project description. "
                "Automatic processing was stopped."
            )
        )

        return state

    # ---------------------------------------------
    # Read capacity
    # ---------------------------------------------
    capacity_value = None
    capacity_unit = None

    if request.capacity:
        capacity_value = request.capacity.value
        capacity_unit = request.capacity.unit

    # ---------------------------------------------
    # Read location
    # ---------------------------------------------
    state_name = None
    district = None

    if request.location:
        state_name = request.location.state
        district = request.location.district

    # ---------------------------------------------
    # Read protected-area information
    # ---------------------------------------------
    protected_area_type = None
    protected_area_distance = None

    if request.nearest_protected_area:
        protected_area_type = request.nearest_protected_area.type
        protected_area_distance = (
            request.nearest_protected_area.distance_km
        )

    # ---------------------------------------------
    # Identify missing/uncertain fields
    # ---------------------------------------------
    missing_fields = []

    if not request.sector_hint:
        missing_fields.append("sector")

    if protected_area_type and protected_area_distance is None:
        missing_fields.append("protected_area_distance_km")

    # ---------------------------------------------
    # Simple confidence for first implementation
    # ---------------------------------------------
    confidence = 1.0

    if missing_fields:
        confidence = 0.6

    # ---------------------------------------------
    # Create structured extractor output
    # ---------------------------------------------
    entities = ExtractedEntities(
        sector=request.sector_hint,
        capacity_value=capacity_value,
        capacity_unit=capacity_unit,
        area_ha=request.area_ha,
        state=state_name,
        district=district,
        protected_area_type=protected_area_type,
        protected_area_distance_km=protected_area_distance,
        confidence=confidence,
        missing_fields=missing_fields
    )

    state.extracted_entities = entities

    # Keep useful information for later logging
    state.metadata["extractor_request_fields"] = fields

    return state