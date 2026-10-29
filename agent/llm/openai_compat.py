import json
from typing import Any, Dict, List, Optional

import httpx

from agent.config import settings
from agent.llm.client import LLMClient, ProviderError


class OpenAICompatibleClient(LLMClient):
    """
    Chat Completions client for any OpenAI-compatible endpoint. The same code talks to
    NVIDIA NIM in production and to the stub LLM service under load test; only
    LLM_BASE_URL and LLM_API_KEY differ.

    Errors are raised, never swallowed: the circuit breaker can only protect the
    system if it sees the failures.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        if not self.base_url:
            raise ProviderError("LLM_BASE_URL is not configured.", transient=False)
        self.http = httpx.Client(timeout=settings.llm_timeout_seconds)

    def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": settings.llm_max_output_tokens,
        }
        if settings.llm_reasoning_effort:
            # Reasoning models otherwise spend most of the latency budget thinking
            payload["reasoning_effort"] = settings.llm_reasoning_effort
        if tools:
            payload["tools"] = tools
            # "none" keeps the tools declared (the conversation contains tool calls, which some
            # providers reject without them) while forbidding new calls: used to force a final answer
            payload["tool_choice"] = tool_choice

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.http.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout or settings.llm_timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ProviderError(f"timeout: {error}", transient=True) from error
        except httpx.HTTPError as error:
            raise ProviderError(f"connection error: {error}", transient=True) from error

        if response.status_code != 200:
            transient = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                status=response.status_code,
                transient=transient,
            )

        data = response.json()
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}

        tool_calls = []
        for call in message.get("tool_calls") or []:
            arguments = call["function"].get("arguments") or "{}"
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed = {"_unparseable": arguments}
            tool_calls.append({"id": call.get("id", ""), "name": call["function"]["name"], "arguments": parsed})

        raw_message: Dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            raw_message["tool_calls"] = message["tool_calls"]

        return {
            "content": message.get("content") or "",
            "tool_calls": tool_calls,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "raw_message": raw_message,
            "finish_reason": data["choices"][0].get("finish_reason"),
        }
