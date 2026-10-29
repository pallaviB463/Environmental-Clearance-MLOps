from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
    """
    The provider failed. `transient` errors (timeouts, 429, 5xx) are worth retrying;
    others (400, 401, 403) are not, but they still count against the circuit breaker.
    """

    def __init__(self, message: str, status: Optional[int] = None, transient: bool = True):
        super().__init__(message)
        self.status = status
        self.transient = transient


class RunDeadlineExceeded(Exception):
    """Not enough of the run's wall-clock budget is left to make (or retry) a model call."""


class LLMUnavailableError(RuntimeError):
    """Every model on the fallback path failed or has an open circuit breaker."""


class LLMClient(ABC):
    """
    Provider-independent interface for all LLM calls. The provider is chosen by
    configuration (LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL), never in code.
    """

    @abstractmethod
    def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        """
        Return a normalized response:

        {
            "content": "...",
            "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "raw_message": {...}   # assistant message to append to the conversation
        }
        """
