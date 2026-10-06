import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    # -----------------------------
    # Agent execution limits
    # -----------------------------
    max_steps: int = int(
        os.getenv("MAX_STEPS", "10")
    )

    max_tool_calls: int = int(
        os.getenv("MAX_TOOL_CALLS", "8")
    )

    max_verification_retries: int = int(
        os.getenv("MAX_VERIFICATION_RETRIES", "2")
    )

    # -----------------------------
    # Timeout / retry configuration
    # -----------------------------
    llm_timeout_seconds: float = float(
        os.getenv("LLM_TIMEOUT_SECONDS", "10")
    )

    tool_timeout_seconds: float = float(
        os.getenv("TOOL_TIMEOUT_SECONDS", "10")
    )

    max_retries: int = int(
        os.getenv("MAX_RETRIES", "3")
    )

    # -----------------------------
    # LLM provider configuration
    # -----------------------------
    llm_provider: str = os.getenv(
        "LLM_PROVIDER",
        "stub"
    )

    llm_model: str = os.getenv(
        "LLM_MODEL",
        "stub-model"
    )

    llm_base_url: str = os.getenv(
        "LLM_BASE_URL",
        "http://localhost:8001"
    )

    llm_api_key: str = os.getenv(
        "LLM_API_KEY",
        ""
    )

    # -----------------------------
    # Prompt version
    # -----------------------------
    prompt_version: str = os.getenv(
        "PROMPT_VERSION",
        "v1"
    )


settings = Settings()