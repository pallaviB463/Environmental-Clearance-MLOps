import json
from pathlib import Path
from typing import Optional

from agent.state import Chunk


CORPUS_PATH = (
    Path(__file__).resolve().parent.parent
    / "stub_data"
    / "corpus.json"
)


def get_clause(clause_id: str) -> Optional[Chunk]:
    """
    Retrieve one exact corpus chunk using its chunk_id.

    Person 2 can later replace the JSON backend while
    preserving this function interface.
    """

    with open(CORPUS_PATH, "r", encoding="utf-8") as file:
        corpus = json.load(file)

    for item in corpus:

        if item["chunk_id"] == clause_id:
            return Chunk(**item)

    return None