import re

from agent.guardrails.injection import check_prompt_injection
from agent.guardrails.toxicity import check_toxicity
from agent.state import AgentState, Escalation, ExtractedEntities
from observability.recorder import get_recorder


# Keyword hints only: the Screener confirms the Schedule row from the corpus.
SECTOR_KEYWORDS = [
    ("cement", ("cement", "clinker", "grinding unit")),
    ("thermal_power", ("thermal power", "coal power", "coal-fired", "power plant", "lignite")),
    ("river_valley", ("hydroelectric", "hydro-electric", "river valley", "irrigation", "dam ")),
    ("mining", ("mining", "mine lease", "mineral", "quarry")),
    ("construction", ("building", "construction", "township", "built up area", "built-up area")),
    ("crz_coastal", ("coastal regulation zone", "crz", "beach resort")),
    ("solar", ("solar",)),
    ("it_software", ("software", "it park", "data entry")),
]

# GC distances: 5 km, or 10 km for items in the GC proviso. An *estimated* distance this
# close to either line is too uncertain to decide on (F7).
GC_DISTANCES_KM = (5.0, 10.0)
PROXIMITY_MARGIN_KM = 1.0


def _classify_sector(request) -> str:
    if request.sector_hint:
        return request.sector_hint.strip().lower()
    text = f"{request.description} {request.sector_description or ''}".lower()
    for sector, keywords in SECTOR_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return sector
    return "unknown"


def extract_entities(state: AgentState) -> AgentState:
    """
    Extractor (first node): input guardrails, then entity extraction (F3) from the validated
    request, then the cheap pre-LLM escalation checks. Anything stopped here never costs an
    LLM call.
    """
    state.steps += 1
    request = state.request
    recorder = get_recorder()

    with recorder.step("extract", agent="extractor") as outcome:

        # ---------------------------------------------
        # L4: INPUT GUARDRAILS on every free-text field
        # ---------------------------------------------
        free_text = " ".join(filter(None, [
            request.description, request.sector_description, request.project_name, request.eco_sensitive_zone,
        ]))
        injection = check_prompt_injection(free_text)
        is_toxic, toxicity = check_toxicity(free_text)
        state.metadata["input_guardrails"] = {"injection": injection, "toxicity": toxicity}

        if not injection["safe"]:
            state.status = "escalated"
            state.escalation = Escalation(
                reason_code="PROMPT_INJECTION_DETECTED",
                detail="Instruction-like text was found in the project fields. Automatic processing was stopped before any model saw it."
            )
            outcome.update(guardrail="injection", patterns=len(injection["detected_patterns"]))
            return state

        if is_toxic:
            state.status = "escalated"
            state.escalation = Escalation(
                reason_code="TOXIC_INPUT",
                detail=f"Input failed the toxicity check ({', '.join(f['category'] for f in toxicity['flagged'])})."
            )
            outcome.update(guardrail="toxicity")
            return state

        # ---------------------------------------------
        # F3: ENTITY EXTRACTION
        # ---------------------------------------------
        pa_type = pa_name = pa_dist = None
        pa_basis = "surveyed"
        interstate_dist = eco_dist = None

        if request.nearest_protected_area:
            pa_type = request.nearest_protected_area.type
            pa_name = request.nearest_protected_area.name
            pa_dist = request.nearest_protected_area.distance_km
            pa_basis = request.nearest_protected_area.basis or "surveyed"

        for feature in request.proximity or []:
            name = (feature.get("feature") or "").lower()
            subtype = (feature.get("subtype") or "").lower()
            distance = feature.get("distance_km")
            if name in ("protected_area", "national_park", "wildlife_sanctuary") or subtype in ("national_park", "wildlife_sanctuary"):
                if pa_dist is None or (distance is not None and distance < pa_dist):
                    pa_type = subtype or name
                    pa_name = feature.get("name")
                    pa_dist = distance
                    pa_basis = feature.get("basis") or "surveyed"
            elif "boundary" in name and distance is not None:
                interstate_dist = distance if interstate_dist is None else min(interstate_dist, distance)
            elif "eco_sensitive" in name and distance is not None:
                eco_dist = distance if eco_dist is None else min(eco_dist, distance)

        description = f"{request.description} {request.sector_description or ''}".lower()
        if pa_dist is None and re.search(r"national park|sanctuary|tiger reserve", description):
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilomet)", description)
            pa_type = pa_type or "protected_area"
            if match:
                pa_dist = float(match.group(1))
                pa_basis = "estimated"  # taken from free text, not a surveyed field

        missing = []
        if pa_type and pa_dist is None:
            missing.append("protected_area_distance_km")

        entities = ExtractedEntities(
            sector=_classify_sector(request),
            capacity_value=request.capacity.value if request.capacity else None,
            capacity_unit=request.capacity.unit if request.capacity else None,
            area_ha=request.area_ha or request.project_area_ha,
            state=request.location.state if request.location else None,
            district=request.location.district if request.location else None,
            protected_area_type=pa_type,
            protected_area_name=pa_name,
            protected_area_distance_km=pa_dist,
            proximity_basis=pa_basis,
            interstate_distance_km=interstate_dist,
            eco_sensitive_distance_km=eco_dist,
            in_critically_polluted_area=bool(request.in_critically_polluted_area),
            eco_sensitive_zone=request.eco_sensitive_zone,
            confidence=1.0 if not missing else 0.6,
            missing_fields=missing,
        )
        state.extracted_entities = entities
        outcome.update(sector=entities.sector, protected_area_km=pa_dist if pa_dist is not None else -1)

        # ---------------------------------------------
        # F7: PROXIMITY UNCERTAINTY (decided before any model call)
        # ---------------------------------------------
        if "protected_area_distance_km" in missing:
            state.status = "escalated"
            state.escalation = Escalation(
                reason_code="PROXIMITY_UNCERTAIN",
                detail="A protected area is mentioned but its distance is not given. The General Condition depends on it; a surveyed distance is required."
            )
            return state

        if pa_dist is not None and pa_basis == "estimated":
            near = [d for d in GC_DISTANCES_KM if abs(pa_dist - d) <= PROXIMITY_MARGIN_KM]
            if near:
                state.status = "escalated"
                state.escalation = Escalation(
                    reason_code="PROXIMITY_UNCERTAIN",
                    detail=(
                        f"The distance to the protected area ({pa_dist} km) is an estimate within "
                        f"{PROXIMITY_MARGIN_KM:g} km of the {near[0]:g} km General Condition line. A certified survey is required."
                    )
                )
                return state

    return state
