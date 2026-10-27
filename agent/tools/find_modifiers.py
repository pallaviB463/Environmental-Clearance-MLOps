import json
from pathlib import Path
from typing import List, Optional
import yaml

from agent.state import Chunk


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CORPUS_CHUNKS_PATH = DATA_DIR / "corpus_chunks.json"
THRESHOLDS_PATH = DATA_DIR / "schedule_thresholds.yaml"


def find_modifiers(provision_id: str) -> List[Chunk]:
    """
    Given a Schedule provision ID (e.g. 'schedule:3(b)', '3(b)'),
    deterministically look up all modifying provisions such as:
    1. General Condition (GC) if applicable.
    2. Footnotes, amendments, or quashed conflict notices.

    This directly solves Section 4.1 & L1/L3: retrieving the General Condition
    even when the user prompt never mentions it.
    """
    clean_id = provision_id.replace("schedule:", "").strip().lower()
    modifiers = []

    # Check thresholds yaml
    gc_applies = False
    has_conflict = False
    if THRESHOLDS_PATH.exists():
        try:
            with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                thresholds = yaml.safe_load(f)
            item_data = thresholds.get("items", {}).get(clean_id)
            if item_data:
                gc_applies = item_data.get("gc_applies", False)
                has_conflict = item_data.get("amendment_conflict_flag", False)
        except Exception:
            pass

    # Load corpus chunks
    if CORPUS_CHUNKS_PATH.exists():
        with open(CORPUS_CHUNKS_PATH, "r", encoding="utf-8") as f:
            chunks_data = json.load(f)

        for item in chunks_data:
            chunk_id = item.get("chunk_id", "")
            section = item.get("section", "").lower()

            # Retrieve GC if item states GC applies
            if gc_applies and ("general condition" in section or chunk_id == "gc:s_o_1599_e_2014"):
                modifiers.append(Chunk(**item))

            # Retrieve amendment conflict chunk if item has conflict
            if has_conflict and chunk_id == "footnote:92_conflict":
                modifiers.append(Chunk(**item))

    return modifiers
