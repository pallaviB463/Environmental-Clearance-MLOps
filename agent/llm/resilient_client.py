from typing import Any, Dict, List, Optional

from agent.config import settings
from agent.llm.client import LLMClient

from agent.resilience.retry import retry_with_backoff
from agent.resilience.timeouts import run_with_timeout
from agent.resilience.circuit_breaker import CircuitBreaker


class ResilientLLMClient:

    def __init__(self, client: LLMClient):
        self.client = client

        self.breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=10
        )

    def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        correlation_id: Optional[str] = None,
        step: Optional[str] = None
    ) -> Dict[str, Any]:

        def provider_call():

            return run_with_timeout(
                lambda: self.client.complete(
                    messages=messages,
                    tools=tools,
                    timeout=settings.llm_timeout_seconds,
                    correlation_id=correlation_id,
                    step=step
                ),
                timeout_seconds=settings.llm_timeout_seconds
            )

        def protected_call():

            return self.breaker.call(
                provider_call
            )

        return retry_with_backoff(
            protected_call,
            max_retries=settings.max_retries
        )