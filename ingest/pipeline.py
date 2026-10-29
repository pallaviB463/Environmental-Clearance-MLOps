"""
Idempotent corpus -> FAISS pipeline (Requirements L1 / D2).

Idempotency and partial re-embedding:
  * Parsed chunks are cached per document, keyed on the PDF's sha256 and the chunker
    version, so an unchanged PDF is never re-parsed.
  * Every chunk has a content hash. On each run the index is diffed against the
    previous state: only new or changed chunks are embedded and added, removed
    chunks are deleted. Running `build` twice in a row embeds nothing the second time.
  * Embeddings are cached on disk (LangChain CacheBackedEmbeddings), namespaced by
    embedding model, so re-embedding after a chunking change only pays for the text
    that actually changed, and switching models does not destroy the old vectors.

The manifest records data freshness: when the index was built, from which document
versions (gazette number, date, sha256), how many chunks, and pipeline throughput.
"""
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from agent.config import ROOT_DIR, settings
from ingest.chunking import CHUNKER_VERSION, chunk_consolidated, chunk_generic
from ingest.pdf_text import has_text_layer, read_pages


INDEX_DIR = settings.index_dir
PARSED_DIR = INDEX_DIR / "parsed"
FAISS_DIR = INDEX_DIR / "faiss"
EMBED_CACHE_DIR = INDEX_DIR / "embedding_cache"
CHUNKS_FILE = INDEX_DIR / "chunks.jsonl"
STATE_FILE = INDEX_DIR / "index_state.json"
MANIFEST_FILE = INDEX_DIR / "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest_rows() -> List[Dict]:
    with open(settings.corpus_manifest, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _embedding_text(chunk: Dict) -> str:
    # The clause label carries the item number and title, which is what queries match on
    return f"{chunk['clause']}\n{chunk['text']}"


def get_embeddings():
    """Local sentence-transformers model, wrapped in an on-disk cache keyed by text hash."""
    from langchain_classic.embeddings import CacheBackedEmbeddings
    from langchain_classic.storage import LocalFileStore
    from langchain_huggingface import HuggingFaceEmbeddings

    if not settings.embedding_model:
        raise RuntimeError("EMBEDDING_MODEL is not set (see .env.example).")

    base = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        encode_kwargs={"normalize_embeddings": True},
    )
    store = LocalFileStore(str(EMBED_CACHE_DIR))
    return CacheBackedEmbeddings.from_bytes_store(
        base, store, namespace=settings.embedding_model, key_encoder="sha256"
    )


def parse_corpus(log=print) -> Dict:
    """Read and chunk every PDF in the manifest, reusing cached parses for unchanged files."""
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    chunks: List[Dict] = []
    documents, skipped = [], []
    parsed_now = 0

    for row in _load_manifest_rows():
        path = ROOT_DIR / row["local_path"]
        if not path.exists():
            skipped.append({"doc_id": row["doc_id"], "reason": "file_missing"})
            continue

        sha = _sha256(path)
        cache_file = PARSED_DIR / f"{row['doc_id']}.json"
        cached = json.loads(cache_file.read_text()) if cache_file.exists() else None

        if cached and cached["sha256"] == sha and cached["chunker_version"] == CHUNKER_VERSION:
            doc_chunks, text_layer = cached["chunks"], cached["text_layer"]
        else:
            try:
                pages = read_pages(path)
            except Exception as error:
                skipped.append({"doc_id": row["doc_id"], "reason": f"unreadable_pdf ({error})"})
                log(f"[parse] skipped {row['doc_id']}: {error}")
                continue
            text_layer = has_text_layer(pages)
            meta = {
                "doc_id": row["doc_id"],
                "title": row["title"],
                "number": row["number"],
                "date": row["date"],
                "doc_type": row["doc_type"],
            }
            if not text_layer:
                doc_chunks = []
            elif row["doc_type"] == "consolidated":
                doc_chunks = chunk_consolidated(pages, meta)
            else:
                doc_chunks = chunk_generic(pages, meta)
            cache_file.write_text(json.dumps({
                "sha256": sha, "chunker_version": CHUNKER_VERSION,
                "text_layer": text_layer, "chunks": doc_chunks,
            }))
            parsed_now += 1

        if not text_layer:
            skipped.append({"doc_id": row["doc_id"], "reason": "no_text_layer (scanned; OCR out of scope)"})
            continue

        chunks.extend(doc_chunks)
        documents.append({
            "doc_id": row["doc_id"], "doc_type": row["doc_type"], "number": row["number"],
            "date": row["date"], "sha256": sha, "chunks": len(doc_chunks),
        })

    log(f"[parse] {len(documents)} documents indexed, {len(skipped)} skipped, {parsed_now} parsed this run")
    return {"chunks": chunks, "documents": documents, "skipped": skipped, "parsed_now": parsed_now}


def build_index(force: bool = False, log=print) -> Dict:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document

    started = time.time()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    parsed = parse_corpus(log)
    chunks = parsed["chunks"]
    parse_seconds = time.time() - started

    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        for chunk in sorted(chunks, key=lambda c: c["chunk_id"]):
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    previous = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    same_model = previous.get("embedding_model") == settings.embedding_model
    old_hashes: Dict[str, str] = previous.get("hashes", {}) if (same_model and not force) else {}
    new_hashes = {c["chunk_id"]: c["content_hash"] for c in chunks}

    to_remove = [cid for cid, h in old_hashes.items() if new_hashes.get(cid) != h]
    to_add = [c for c in chunks if old_hashes.get(c["chunk_id"]) != c["content_hash"]]
    unchanged = len(chunks) - len(to_add)

    embeddings = get_embeddings()
    embed_started = time.time()
    index_exists = (FAISS_DIR / "index.faiss").exists() and bool(old_hashes)

    if not to_add and not to_remove and index_exists:
        log("[index] no changes - index already up to date")
    else:
        documents = [
            Document(page_content=_embedding_text(c), metadata={"chunk_id": c["chunk_id"]})
            for c in to_add
        ]
        ids = [c["chunk_id"] for c in to_add]
        if index_exists:
            store = FAISS.load_local(str(FAISS_DIR), embeddings, allow_dangerous_deserialization=True)
            if to_remove:
                store.delete(ids=to_remove)
            if documents:
                store.add_documents(documents, ids=ids)
        else:
            store = FAISS.from_documents(documents, embeddings, ids=ids)
        store.save_local(str(FAISS_DIR))
        log(f"[index] embedded {len(to_add)} chunks, removed {len(to_remove)}, unchanged {unchanged}")

    embed_seconds = time.time() - embed_started
    total_seconds = time.time() - started

    STATE_FILE.write_text(json.dumps({
        "embedding_model": settings.embedding_model,
        "hashes": new_hashes,
    }))

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "built_at_unix": time.time(),
        "embedding_model": settings.embedding_model,
        "chunker_version": CHUNKER_VERSION,
        "chunk_count": len(chunks),
        "chunks_added": len(to_add),
        "chunks_removed": len(to_remove),
        "chunks_unchanged": unchanged,
        "documents_indexed": len(parsed["documents"]),
        "documents_skipped": parsed["skipped"],
        "documents": parsed["documents"],
        "timings_seconds": {
            "parse": round(parse_seconds, 2),
            "embed_and_index": round(embed_seconds, 2),
            "total": round(total_seconds, 2),
        },
        "throughput_chunks_per_sec": round(len(chunks) / total_seconds, 2) if total_seconds else 0.0,
        "embedding_throughput_chunks_per_sec": round(len(to_add) / embed_seconds, 2) if to_add and embed_seconds else 0.0,
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
    log(f"[done] {len(chunks)} chunks in {total_seconds:.1f}s -> {MANIFEST_FILE}")
    return manifest


def read_manifest() -> Dict:
    return json.loads(MANIFEST_FILE.read_text()) if MANIFEST_FILE.exists() else {}
