import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent

# .env holds this machine's values (gitignored); .env.example supplies documented
# defaults for anything not set. No credentials, endpoints or model identifiers
# live in code (Requirement D4).
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR / ".env.example", override=False)


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    # -----------------------------
    # Agent execution limits (A1)
    # -----------------------------
    max_steps: int = int(os.getenv("MAX_STEPS", "10"))
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "8"))
    max_verification_retries: int = int(os.getenv("MAX_VERIFICATION_RETRIES", "2"))
    run_deadline_seconds: float = float(os.getenv("RUN_DEADLINE_SECONDS", "90"))

    # -----------------------------
    # Timeout / retry / breaker (A5)
    # -----------------------------
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    tool_timeout_seconds: float = float(os.getenv("TOOL_TIMEOUT_SECONDS", "10"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    breaker_failure_threshold: int = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
    breaker_reset_seconds: float = float(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"))

    # -----------------------------
    # LLM provider (behind an interface we control)
    # -----------------------------
    llm_provider: str = os.getenv("LLM_PROVIDER", "stub")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_price_input_per_1k: float = float(os.getenv("LLM_PRICE_INPUT_PER_1K", "0"))
    llm_price_output_per_1k: float = float(os.getenv("LLM_PRICE_OUTPUT_PER_1K", "0"))
    llm_max_output_tokens: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1200"))
    # Optional "low" / "medium" / "high" for reasoning models; empty = provider default
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "")

    # -----------------------------
    # Prompt version (L2)
    # -----------------------------
    prompt_version: str = os.getenv("PROMPT_VERSION", "v1")

    # -----------------------------
    # Retrieval / index (L1, D2)
    # -----------------------------
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    index_dir: Path = Path(os.getenv("INDEX_DIR", str(ROOT_DIR / "data" / "index")))
    corpus_manifest: Path = Path(os.getenv("CORPUS_MANIFEST", str(ROOT_DIR / "data" / "corpus_manifest.csv")))

    # -----------------------------
    # Services
    # -----------------------------
    redis_url: str = os.getenv("REDIS_URL", "")
    verifier_url: str = os.getenv("VERIFIER_URL", "")
    run_cache_ttl_seconds: int = int(os.getenv("RUN_CACHE_TTL_SECONDS", "86400"))
    cache_enabled: bool = _bool("CACHE_ENABLED", "true")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    live_eval_sample_rate: float = float(os.getenv("LIVE_EVAL_SAMPLE_RATE", "0.2"))

    # -----------------------------
    # Observability (D5)
    # -----------------------------
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    jaeger_ui_url: str = os.getenv("JAEGER_UI_URL", "")
    service_name: str = os.getenv("SERVICE_NAME", "eia-local")


settings = Settings()
