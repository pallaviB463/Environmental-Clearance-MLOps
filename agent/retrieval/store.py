"""
Read side of the corpus index: semantic search over FAISS, exact lookup by chunk id,
and the cross-reference graph used to find provisions that modify a given one.
Loaded once per process.
"""
import json
import re
import threading
from typing import Dict, List, Optional, Tuple

from agent.config import settings
from agent.state import Chunk


INDEX_DIR = settings.index_dir


class IndexNotBuiltError(RuntimeError):
    pass


class CorpusStore:

    def __init__(self):
        chunks_file = INDEX_DIR / "chunks.jsonl"
        if not chunks_file.exists() or not (INDEX_DIR / "faiss" / "index.faiss").exists():
            raise IndexNotBuiltError(
                f"No index at {INDEX_DIR}. Build it with: python -m ingest build"
            )

        self.raw: Dict[str, Dict] = {}
        with open(chunks_file, encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                self.raw[item["chunk_id"]] = item

        manifest_file = INDEX_DIR / "manifest.json"
        self.manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
        self.index_version = f"{self.manifest.get('built_at_unix', 0):.0f}"
        self._vectors = None
        self._vectors_lock = threading.Lock()

    @property
    def vectors(self):
        """FAISS + embedding model, loaded on first search (exact lookups do not need it)."""
        if self._vectors is None:
            with self._vectors_lock:
                if self._vectors is None:
                    from langchain_community.vectorstores import FAISS
                    from ingest.pipeline import get_embeddings

                    self._vectors = FAISS.load_local(
                        str(INDEX_DIR / "faiss"), get_embeddings(), allow_dangerous_deserialization=True
                    )
        return self._vectors

    # -----------------------------------------------------
    # Lookups
    # -----------------------------------------------------

    def to_chunk(self, chunk_id: str, score: float = 0.0) -> Optional[Chunk]:
        item = self.raw.get(chunk_id)
        if item is None:
            return None
        return Chunk(
            chunk_id=item["chunk_id"],
            doc=item["doc"],
            doc_version=item["doc_version"],
            section=item["section"],
            clause=item["clause"],
            text=item["text"],
            score=round(score, 4),
            metadata={
                key: item.get(key)
                for key in ("doc_id", "doc_type", "page_start", "page_end", "references",
                            "footnote_refs", "gc_applies", "sc_applies", "in_force")
            },
        )

    def get(self, chunk_id: str) -> Optional[Chunk]:
        return self.to_chunk(chunk_id.strip())

    def search(
        self,
        query: str,
        k: int = 5,
        section: Optional[str] = None,
    ) -> List[Chunk]:
        """
        Semantic search. Scores are cosine similarity (embeddings are L2-normalised,
        so cosine = 1 - squared_L2 / 2).
        """
        def keep(metadata: Dict) -> bool:
            if section is None:
                return True
            item = self.raw.get(metadata["chunk_id"], {})
            return item.get("section", "").lower() == section.lower()

        hits: List[Tuple] = self.vectors.similarity_search_with_score(
            query, k=k, filter=keep, fetch_k=max(50, k * 10)
        )
        results = []
        for document, distance in hits:
            chunk = self.to_chunk(document.metadata["chunk_id"], score=1.0 - float(distance) / 2.0)
            if chunk:
                results.append(chunk)
        return results

    def modifiers(self, chunk_id: str) -> List[Tuple[Chunk, str]]:
        """
        Provisions that can change how `chunk_id` applies, following links recorded at
        ingestion time rather than a hand-written table:
          * the General / Specific Condition, when the row's text says it applies
          * the amendment footnotes attached to the row, with whether each is in force
          * the notification paragraphs that refer back to the General Condition
          * later gazette notifications and office memoranda that cite the same item
        """
        item = self.raw.get(chunk_id.strip())
        if item is None:
            return []

        found: List[Tuple[Chunk, str]] = []
        item_id = chunk_id.split(":", 1)[1] if chunk_id.startswith("schedule:") else None

        if item.get("gc_applies"):
            gc = self.raw.get("schedule:gc", {})
            relation = "general_condition_applies (row says 'General Condition shall apply')"
            if item_id and item_id in gc.get("references", []):
                relation += "; this item is named in the GC's 10 km proviso"
            found.append((self.to_chunk("schedule:gc"), relation))
        elif item.get("gc_applies") is False:
            found.append((self.to_chunk("schedule:gc"), "general_condition_excluded (row says it shall not apply)"))

        if item.get("sc_applies"):
            found.append((self.to_chunk("schedule:sc"), "specific_condition_applies"))

        for number in item.get("footnote_refs", []):
            footnote = self.raw.get(f"footnote:{number}")
            if footnote:
                state = "in force" if footnote.get("in_force", True) else "NOT IN FORCE / QUASHED"
                found.append((self.to_chunk(f"footnote:{number}"), f"amendment_footnote ({state})"))

        if chunk_id in ("schedule:gc", "schedule:sc") or item.get("gc_applies"):
            for para_id in ("para:4(iii)", "para:4(ii)"):
                if para_id in self.raw:
                    found.append((self.to_chunk(para_id), "routing_paragraph (who appraises Category A / B)"))

        if item_id:
            later = [
                c for c in self.raw.values()
                if c["doc_type"] not in ("consolidated",) and item_id in c.get("references", [])
            ]
            later.sort(key=lambda c: re.search(r"\((\d{4}-\d{2}-\d{2})\)", c["doc_version"]).group(1)
                       if re.search(r"\((\d{4}-\d{2}-\d{2})\)", c["doc_version"]) else "", reverse=True)
            for c in later[:3]:
                found.append((self.to_chunk(c["chunk_id"]), "later_notification_or_om_citing_item"))

        return [(chunk, relation) for chunk, relation in found if chunk is not None]


_store: Optional[CorpusStore] = None
_lock = threading.Lock()


def get_store() -> CorpusStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = CorpusStore()
    return _store


def warm_up() -> float:
    """
    Load FAISS and the embedding model before the first run. A cold first search takes
    several seconds and would otherwise hit the tool timeout inside a run.
    """
    import time
    started = time.time()
    get_store().search("warm-up query", k=1)
    return time.time() - started
