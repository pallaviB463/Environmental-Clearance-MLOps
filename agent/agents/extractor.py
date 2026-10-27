import re
from agent.state import AgentState, ExtractedEntities, Escalation
from agent.tools.request_fields import get_request_fields
from agent.guardrails.injection import check_prompt_injection


def extract_entities(state: AgentState) -> AgentState:
    """
    Extract structured project information from the validated request.
    Performs L4 input guardrail check on all free-text fields.
    Extracts sector, capacity, location, and proximity entities.
    """
    state.steps += 1
    request = state.request
    fields = get_request_fields(request)

    # ---------------------------------------------
    # L4: INPUT GUARDRAIL (Prompt injection check)
    # ---------------------------------------------
    text_to_check = f"{request.description} {request.sector_description or ''} {request.project_name or ''}"
    injection_result = check_prompt_injection(text_to_check)
    state.metadata["injection_check"] = injection_result

    if not injection_result["safe"]:
        state.status = "escalated"
        state.escalation = Escalation(
            reason_code="PROMPT_INJECTION_DETECTED",
            detail=(
                "Potential prompt-injection instructions were "
                "detected in the project input fields. "
                "Automatic processing was stopped."
            )
        )
        return state

    # ---------------------------------------------
    # 1. Sector Extraction
    # ---------------------------------------------
    sector = request.sector_hint
    full_text = f"{request.description} {request.sector_description or ''}".lower()

    if not sector:
        if "cement" in full_text or "clinker" in full_text or "grinding" in full_text:
            sector = "cement"
        elif "thermal" in full_text or "coal power" in full_text or "power plant" in full_text:
            sector = "power"
        elif "mining" in full_text or "mineral" in full_text:
            sector = "mining"
        elif "building" in full_text or "construction" in full_text or "township" in full_text:
            sector = "construction"
        elif "river valley" in full_text or "hydroelectric" in full_text or "irrigation" in full_text:
            sector = "river_valley"
        elif "beach resort" in full_text or "crz" in full_text or "coastal" in full_text:
            sector = "crz_coastal"
        elif "industrial" in full_text:
            sector = "industrial"

    # ---------------------------------------------
    # 2. Capacity & Area
    # ---------------------------------------------
    capacity_value = None
    capacity_unit = None
    if request.capacity:
        capacity_value = request.capacity.value
        capacity_unit = request.capacity.unit

    area_ha = request.area_ha or request.project_area_ha

    # ---------------------------------------------
    # 3. Location
    # ---------------------------------------------
    state_name = None
    district = None
    if request.location:
        state_name = request.location.state
        district = request.location.district

    # ---------------------------------------------
    # 4. Proximity & Sensitive Features
    # ---------------------------------------------
    pa_type = None
    pa_name = None
    pa_dist = None
    pa_basis = "surveyed"
    interstate_dist = None

    # From nearest_protected_area if present
    if request.nearest_protected_area:
        pa_type = request.nearest_protected_area.type
        pa_name = request.nearest_protected_area.name
        pa_dist = request.nearest_protected_area.distance_km
        pa_basis = request.nearest_protected_area.basis or "surveyed"

    # From proximity list if present (e.g. RC-1 data contract)
    if request.proximity:
        for feat in request.proximity:
            feature_name = feat.get("feature", "").lower()
            subtype = feat.get("subtype", "").lower()
            if "protected_area" in feature_name or "national_park" in subtype or "sanctuary" in subtype:
                pa_type = subtype or "protected_area"
                pa_name = feat.get("name")
                pa_dist = feat.get("distance_km")
                pa_basis = feat.get("basis", "surveyed")
            elif "interstate" in feature_name or "inter-state" in feature_name or "boundary" in feature_name:
                interstate_dist = feat.get("distance_km")

    # Fallback keyword extraction from description if not structured
    if pa_dist is None and "national park" in full_text:
        match = re.search(r"(\d+(\.\d+)?)\s*(km|kilometres|kilometers)", full_text)
        if match:
            pa_dist = float(match.group(1))
            pa_type = "national_park"

    # ---------------------------------------------
    # 5. Missing Fields & Confidence
    # ---------------------------------------------
    missing_fields = []
    if not sector:
        missing_fields.append("sector")
    if pa_type and pa_dist is None:
        missing_fields.append("protected_area_distance_km")

    confidence = 1.0 if not missing_fields else 0.6

    entities = ExtractedEntities(
        sector=sector,
        capacity_value=capacity_value,
        capacity_unit=capacity_unit,
        area_ha=area_ha,
        state=state_name,
        district=district,
        protected_area_type=pa_type,
        protected_area_name=pa_name,
        protected_area_distance_km=pa_dist,
        proximity_basis=pa_basis,
        interstate_distance_km=interstate_dist,
        in_critically_polluted_area=bool(request.in_critically_polluted_area),
        eco_sensitive_zone=request.eco_sensitive_zone,
        confidence=confidence,
        missing_fields=missing_fields
    )

    state.extracted_entities = entities
    state.metadata["extractor_request_fields"] = fields
    return state