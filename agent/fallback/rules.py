"""
Deterministic rule engine.

Two uses, never the primary path:
  1. Degraded fallback (A5): when every LLM on the fallback path is unavailable, this
     produces a *provisional* opinion. The run is still escalated to a human; the
     opinion is attached for them, never returned as a confident answer.
  2. Brain of the stub LLM service used for load testing (D6), so the stub returns
     plausible fixed responses without calling a provider.

It reads thresholds from data/schedule_thresholds.yaml and everything else (does the
General Condition apply, is the item in the 10 km proviso, is an amendment not in
force) from the indexed corpus text, and cites real chunks with verbatim quotes.
"""
from typing import Dict, List, Optional, Tuple

import yaml

from agent.config import ROOT_DIR
from agent.state import Chunk, Citation, DraftDetermination, ExtractedEntities


THRESHOLDS = yaml.safe_load((ROOT_DIR / "data" / "schedule_thresholds.yaml").read_text())

OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def resolve_sector(sector: Optional[str]) -> Optional[str]:
    if not sector:
        return None
    sector = sector.strip().lower()
    return THRESHOLDS["sector_aliases"].get(sector, sector)


def quote(chunk: Chunk, phrase: str, width: int = 160) -> str:
    """Return a verbatim window of the chunk text around `phrase` (case-insensitive)."""
    text = chunk.text
    position = text.lower().find(phrase.lower())
    if position < 0:
        return text[:width]
    start = max(0, position - 20)
    return text[start:start + width]


def _meets(rule: Optional[Dict], value: float) -> bool:
    return bool(rule) and OPS[rule["op"]](value, rule["value"])


def gc_triggers(entities: ExtractedEntities, distance_km: float) -> List[str]:
    triggers = []
    pa = entities.protected_area_distance_km
    if pa is not None and pa <= distance_km:
        triggers.append(f"{pa} km from a Protected Area ({entities.protected_area_type or 'protected area'})")
    if entities.interstate_distance_km is not None and entities.interstate_distance_km <= distance_km:
        triggers.append(f"{entities.interstate_distance_km} km from an inter-State/international boundary")
    if entities.eco_sensitive_distance_km is not None and entities.eco_sensitive_distance_km <= distance_km:
        triggers.append(f"{entities.eco_sensitive_distance_km} km from a notified eco-sensitive area")
    elif entities.eco_sensitive_zone:
        triggers.append(f"inside eco-sensitive zone '{entities.eco_sensitive_zone}'")
    if entities.in_critically_polluted_area:
        triggers.append("within a Critically Polluted Area")
    return triggers


def _escalate(code: str, detail: str, citations: Optional[List[Citation]] = None) -> DraftDetermination:
    return DraftDetermination(
        decision="escalate",
        route="escalate_to_human",
        escalation_reason_code=code,
        escalation_detail=detail,
        basis=detail,
        citations=citations or [],
        produced_by="rule_engine",
    )


def screen(entities: ExtractedEntities, description: str, store) -> Tuple[DraftDetermination, Dict[str, Chunk]]:
    """Return a draft determination and every chunk it read (for citation verification)."""
    retrieved: Dict[str, Chunk] = {}

    def read(chunk_id: str) -> Optional[Chunk]:
        chunk = store.get(chunk_id)
        if chunk:
            retrieved[chunk.chunk_id] = chunk
        return chunk

    sector = resolve_sector(entities.sector)
    text = (description or "").lower()

    if sector in THRESHOLDS["out_of_corpus"] or sector is None or sector in ("unknown", "other"):
        return _escalate(
            "OUT_OF_CORPUS",
            "The activity could not be matched to a Schedule item of the EIA Notification 2006 "
            "(it may fall under another notification, e.g. the CRZ Notification). An accredited consultant must decide."
        ), retrieved

    if sector in THRESHOLDS["non_scheduled"]:
        para = read("para:2(i)")
        return DraftDetermination(
            category="NO_CLEARANCE",
            route="no_clearance",
            basis=(
                "The activity is not listed in the Schedule. Paragraph 2(i) requires prior environmental "
                "clearance only for projects or activities listed in the Schedule."
            ),
            citations=[Citation(chunk_id=para.chunk_id, quote=quote(para, "listed in the Schedule"))] if para else [],
            produced_by="rule_engine",
        ), retrieved

    rules = THRESHOLDS["sectors"].get(sector)
    if rules is None:
        return _escalate(
            "SECTOR_AMBIGUOUS",
            f"Sector '{entities.sector}' does not identify a single Schedule item. "
            "State the specific activity (e.g. cement plant, thermal power plant)."
        ), retrieved

    row = read(f"schedule:{rules['item']}")
    if row is None:
        return _escalate("OUT_OF_CORPUS", f"Schedule item {rules['item']} is not in the index."), retrieved

    row_citation = Citation(chunk_id=row.chunk_id, quote=quote(row, row.clause.split(" - ", 1)[-1][:25]))

    # An amendment to this row that is recorded as not in force / quashed -> conflicting amendment history
    modifiers = store.modifiers(row.chunk_id)
    for chunk, relation in modifiers:
        retrieved[chunk.chunk_id] = chunk
        if "NOT IN FORCE" in relation:
            return _escalate(
                "AMENDMENT_CONFLICT",
                f"Schedule item {rules['item']} has an amendment recorded as not in force / quashed "
                f"({chunk.chunk_id}). The applicable text must be confirmed by an accredited consultant.",
                [row_citation, Citation(chunk_id=chunk.chunk_id, quote=quote(chunk, "not in force"))],
            ), retrieved

    value = entities.capacity_value if entities.capacity_value is not None else entities.area_ha
    if value is None:
        return _escalate(
            "INSUFFICIENT_INFORMATION",
            f"Schedule item {rules['item']} is decided by capacity/area, which was not provided."
        ), retrieved

    category_a_rule = rules.get("category_a")
    if sector == "mining" and "coal" in text and "coal" in rules:
        category_a_rule = rules["coal"]["category_a"]

    forced_b = any(keyword in text for keyword in rules.get("always_category_b_if", []))

    if not forced_b and _meets(category_a_rule, value):
        para = read("para:4(ii)")
        return DraftDetermination(
            category="A",
            route="category_a_central",
            schedule_item=rules["item"],
            basis=(
                f"{value} {entities.capacity_unit or ''} meets the Category A threshold of Schedule item "
                f"{rules['item']}. Under Paragraph 4(ii), Category A projects need prior environmental "
                "clearance from the Central Government on the recommendation of the Expert Appraisal Committee."
            ),
            citations=[row_citation] + ([Citation(chunk_id=para.chunk_id, quote=quote(para, "Category ‘A’"))] if para else []),
            modifiers_checked=[c.chunk_id for c, _ in modifiers],
            produced_by="rule_engine",
        ), retrieved

    if not forced_b and not _meets(rules.get("category_b"), value):
        para = read("para:2(i)")
        return DraftDetermination(
            category="NO_CLEARANCE",
            route="no_clearance",
            schedule_item=rules["item"],
            basis=(
                f"{value} {entities.capacity_unit or ''} is below the lowest threshold of Schedule item "
                f"{rules['item']}, so the project is not a listed activity under Paragraph 2(i)."
            ),
            citations=[row_citation] + ([Citation(chunk_id=para.chunk_id, quote=quote(para, "listed in the Schedule"))] if para else []),
            modifiers_checked=[c.chunk_id for c, _ in modifiers],
            produced_by="rule_engine",
        ), retrieved

    # Category B by the Schedule: does the General Condition move it to Category A?
    gc = next((c for c, relation in modifiers if c.chunk_id == "schedule:gc" and "applies" in relation and "excluded" not in relation), None)
    if gc is not None:
        in_proviso = rules["item"] in gc.metadata.get("references", [])
        distance = THRESHOLDS["general_condition"]["proviso_distance_km" if in_proviso else "default_distance_km"]
        triggers = gc_triggers(entities, distance)
        if triggers:
            para = read("para:4(ii)")
            return DraftDetermination(
                category="A",
                route="category_a_central",
                schedule_item=rules["item"],
                basis=(
                    f"Schedule item {rules['item']} places the project in Category B, and the row states that the "
                    f"General Condition shall apply. The project is {' and '.join(triggers)}, within the "
                    f"{distance:g} km set by the General Condition{' (10 km proviso for this item)' if in_proviso else ''}, "
                    "so it is appraised at the Central level as Category A."
                ),
                citations=[
                    row_citation,
                    Citation(chunk_id=gc.chunk_id, quote=quote(gc, "will be appraised at the Central Level")),
                ] + ([Citation(chunk_id=para.chunk_id, quote=quote(para, "Category ‘A’"))] if para else []),
                modifiers_checked=[c.chunk_id for c, _ in modifiers],
                produced_by="rule_engine",
            ), retrieved

    para = read("para:4(iii)")
    return DraftDetermination(
        category="B",
        route="category_b_state",
        schedule_item=rules["item"],
        basis=(
            f"{value} {entities.capacity_unit or ''} falls in Category B of Schedule item {rules['item']}, and no "
            "General Condition trigger applies at the stated distances. Under Paragraph 4(iii), Category B projects "
            "need prior environmental clearance from the State/UT Environment Impact Assessment Authority (SEIAA)."
        ),
        citations=[row_citation] + ([Citation(chunk_id=para.chunk_id, quote=quote(para, "Category ‘B’"))] if para else []),
        modifiers_checked=[c.chunk_id for c, _ in modifiers],
        produced_by="rule_engine",
    ), retrieved
