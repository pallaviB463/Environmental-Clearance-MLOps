from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMClient(ABC):
    """
    Provider-independent interface for all LLM calls.

    Agents should depend on this interface instead of directly
    depending on OpenAI, Gemini, etc.
    """

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        correlation_id: Optional[str] = None,
        step: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Return a normalized response.

        Expected format:

        {
            "text": "...",
            "tool_calls": [],
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
        """
        pass