import time
from typing import Any, Dict, List, Optional

from agent.llm.client import LLMClient


class StubLLMClient(LLMClient):

    def __init__(
        self,
        mode: str = "normal",
        delay_seconds: float = 0.0
    ):
        self.mode = mode
        self.delay_seconds = delay_seconds

    def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        correlation_id: Optional[str] = None,
        step: Optional[str] = None
    ) -> Dict[str, Any]:

        # ---------------------------------------------
        # Simulated delay
        # ---------------------------------------------

        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        # ---------------------------------------------
        # Simulated provider failure
        # ---------------------------------------------

        if self.mode == "error500":
            raise RuntimeError(
                "Stub LLM simulated HTTP 500 error."
            )

        # ---------------------------------------------
        # Simulated timeout
        # ---------------------------------------------

        if self.mode == "timeout":
            raise TimeoutError(
                "Stub LLM simulated timeout."
            )

        # ---------------------------------------------
        # Simulated malformed model output
        # ---------------------------------------------

        if self.mode == "malformed":
            return {
                "unexpected_field": "bad response"
            }

        # ---------------------------------------------
        # Normal deterministic response
        # ---------------------------------------------

        return {
            "text": (
                "Stub LLM response. "
                "No external model was called."
            ),
            "tool_calls": [],
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "metadata": {
                "provider": "stub",
                "correlation_id": correlation_id,
                "step": step
            }
        }