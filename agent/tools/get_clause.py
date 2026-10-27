import json
from pathlib import Path
from typing import Optional

from agent.state import Chunk


DATA_CORPUS = Path(__file__).resolve().parent.parent.parent / "data" / "corpus_chunks.json"
STUB_CORPUS = Path(__file__).resolve().parent.parent / "stub_data" / "corpus.json"


def get_clause(clause_id: str) -> Optional[Chunk]:
    """
    Retrieve one exact corpus chunk using its chunk_id.
    Prioritizes confirmed corpus chunks, falls back to stub data.
    """
    paths_to_check = [DATA_CORPUS, STUB_CORPUS]

    for path in paths_to_check:
        if path.exists():
            with open(path, "r", encoding="utf-8") as file:
                corpus = json.load(file)
            for item in corpus:
                if item["chunk_id"] == clause_id:
                    return Chunk(
                        chunk_id=item["chunk_id"],
                        doc=item.get("doc", ""),
                        doc_version=item.get("doc_version", ""),
                        section=item.get("section", ""),
                        clause=item.get("clause", ""),
                        text=item.get("text", ""),
                        score=float(item.get("score", 0.0))
                    )

    return None