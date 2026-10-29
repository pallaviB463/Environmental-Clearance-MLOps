"""
Corpus ingestion pipeline (Requirements L1 / D2).

read PDFs -> parse text -> structure-aware chunking -> local embeddings -> FAISS index

Invoke from the command line:
    python -m ingest build        # idempotent: only new or changed chunks are embedded
    python -m ingest status       # print the index manifest (freshness, versions, counts)
"""
