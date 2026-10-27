import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from agent.state import Chunk


DATA_CORPUS = Path(__file__).resolve().parent.parent.parent / "data" / "corpus_chunks.json"
STUB_CORPUS = Path(__file__).resolve().parent.parent / "stub_data" / "corpus.json"


def _load_corpus() -> List[dict]:
    """
    Load corpus chunks, prioritizing confirmed data over stub.
    """
    if DATA_CORPUS.exists():
        with open(DATA_CORPUS, "r", encoding="utf-8") as file:
            return json.load(file)
    with open(STUB_CORPUS, "r", encoding="utf-8") as file:
        return json.load(file)


def _tokenize(text: str) -> set[str]:
    """
    Convert text into simple lowercase word tokens.
    """
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def search_corpus(
    query: str,
    k: int = 5,
    filters: Optional[Dict] = None
) -> List[Chunk]:
    """
    Search the corpus using token overlap and metadata filtering.
    """
    corpus = _load_corpus()
    query_tokens = _tokenize(query)

    results = []

    for item in corpus:
        # Apply optional filters
        if filters:
            skip_item = False
            for key, expected_value in filters.items():
                val = item.get(key)
                if val is None and isinstance(item.get("metadata"), dict):
                    val = item["metadata"].get(key)
                if val != expected_value:
                    # also allow case-insensitive match for strings
                    if isinstance(val, str) and isinstance(expected_value, str) and val.lower() == expected_value.lower():
                        continue
                    skip_item = True
                    break
            if skip_item:
                continue

        # Calculate token overlap
        searchable_text = " ".join([
            item.get("section", ""),
            item.get("clause", ""),
            item.get("text", "")
        ])

        document_tokens = _tokenize(searchable_text)
        overlap = query_tokens.intersection(document_tokens)

        if not overlap:
            continue

        score = len(overlap) / max(len(query_tokens), 1)

        results.append(
            Chunk(
                chunk_id=item["chunk_id"],
                doc=item.get("doc", ""),
                doc_version=item.get("doc_version", ""),
                section=item.get("section", ""),
                clause=item.get("clause", ""),
                text=item.get("text", ""),
                score=score
            )
        )

    results.sort(key=lambda chunk: chunk.score, reverse=True)
    return results[:k]