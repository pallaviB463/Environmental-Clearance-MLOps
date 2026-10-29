import os

# Settings are read once at import, so pin the test environment before anything imports
# agent.config. Explicit values win over .env (python-dotenv never overrides set variables).
os.environ.update({
    "LLM_PROVIDER": "stub",
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_MODEL": "stub-model",
    "LLM_FALLBACK_MODEL": "",
    "REDIS_URL": "",
    "VERIFIER_URL": "",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    "STUB_LLM_DELAY_SECONDS": "0",
    "MAX_RETRIES": "1",
    "CACHE_ENABLED": "false",
    "RATE_LIMIT_PER_MINUTE": "1000",
})

import pytest  # noqa: E402

from agent.config import settings  # noqa: E402


def index_built() -> bool:
    return (settings.index_dir / "chunks.jsonl").exists() and (settings.index_dir / "faiss" / "index.faiss").exists()


needs_index = pytest.mark.skipif(not index_built(), reason="corpus index not built: run `python -m ingest build`")
