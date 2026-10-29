import json
import os
import random
import time
from typing import Any, Dict, List, Optional

from agent.llm.client import LLMClient
from stub_llm import policy


class InProcessStubClient(LLMClient):
    """
    The stub policy called directly, for local runs and tests where the stub service
    is not running (LLM_PROVIDER=stub with no LLM_BASE_URL).
    """

    def __init__(self):
        self.delay = float(os.getenv("STUB_LLM_DELAY_SECONDS", "0.0"))

    def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        from agent.retrieval.store import get_store

        if self.delay:
            time.sleep(self.delay * random.uniform(0.8, 1.2))

        message, prompt_tokens, completion_tokens = policy.respond(messages, get_store(), tools, tool_choice)
        tool_calls = [
            {"id": call["id"], "name": call["function"]["name"], "arguments": json.loads(call["function"]["arguments"])}
            for call in message.get("tool_calls") or []
        ]
        return {
            "content": message.get("content") or "",
            "tool_calls": tool_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "raw_message": message,
        }
