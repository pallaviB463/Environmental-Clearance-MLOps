"""
LLM gateway: the only way agents reach a model (Requirement A5).

For each call, per model on the fallback path (LLM_MODEL, then LLM_FALLBACK_MODEL):

    circuit breaker  ->  retry with exponential backoff (transient errors only)  ->  timeout  ->  provider

If every model fails or has an open breaker, LLMUnavailableError is raised and the
graph takes the degraded path (rule-engine provisional opinion + escalation). A run
that did not complete is never returned as a confident answer.

Tokens and cost are recorded at the time of the call, attributed to agent and step (L5).
"""
import logging
import time
from typing import Any, Dict, List, Optional

from agent import chaos
from agent.config import settings
from agent.llm.client import LLMClient, LLMUnavailableError, ProviderError, RunDeadlineExceeded
from agent.resilience.circuit_breaker import STATE_VALUES, CircuitBreaker, CircuitBreakerOpenError
from agent.resilience.retry import retry_with_backoff
from agent.resilience.timeouts import run_with_timeout
from observability.metrics import (
    AGENT_STEP_SECONDS,
    CIRCUIT_BREAKER_STATE,
    LLM_CALLS_TOTAL,
    LLM_COST_USD_TOTAL,
    LLM_RETRIES_TOTAL,
    LLM_TOKENS_TOTAL,
)
from observability.recorder import get_recorder
from observability.tracing import get_tracer


logger = logging.getLogger("eia.llm")


def _make_client() -> LLMClient:
    if settings.llm_provider == "stub" and not settings.llm_base_url:
        from stub_llm.inprocess import InProcessStubClient
        return InProcessStubClient()
    from agent.llm.openai_compat import OpenAICompatibleClient
    return OpenAICompatibleClient()


def _on_breaker_change(model: str, state: str) -> None:
    CIRCUIT_BREAKER_STATE.labels(model=model).set(STATE_VALUES[state])
    logger.warning(f"circuit breaker for {model} -> {state}")


MIN_CALL_SECONDS = 5.0


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens / 1000 * settings.llm_price_input_per_1k
        + completion_tokens / 1000 * settings.llm_price_output_per_1k,
        6,
    )


class LLMGateway:

    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client
        self.models = [m for m in (settings.llm_model, settings.llm_fallback_model) if m] or ["stub-model"]
        self.breakers = {
            model: CircuitBreaker(
                failure_threshold=settings.breaker_failure_threshold,
                recovery_timeout=settings.breaker_reset_seconds,
                name=model,
                on_state_change=_on_breaker_change,
            )
            for model in self.models
        }
        for model in self.models:
            CIRCUIT_BREAKER_STATE.labels(model=model).set(0)

    def _client(self) -> LLMClient:
        if self.client is None:
            self.client = _make_client()
        return self.client

    def breaker_states(self) -> Dict[str, str]:
        return {model: breaker.state for model, breaker in self.breakers.items()}

    def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        agent: str,
        step: str,
        prompt_version: str,
        tool_choice: str = "auto",
        deadline: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        `deadline` is the run's wall-clock limit: each call's timeout shrinks to the time left,
        and no call or retry starts once too little is left (RunDeadlineExceeded). Without
        this, retries on a slow provider can run far past the run's budget.
        """
        recorder = get_recorder()
        errors = []

        for position, model in enumerate(self.models):
            breaker = self.breakers[model]
            retries = 0

            def on_retry(attempt: int, error: Exception):
                nonlocal retries
                retries = attempt
                LLM_RETRIES_TOTAL.labels(agent=agent).inc()

            def attempt():
                if chaos.llm_down():
                    raise ProviderError("simulated provider outage (HTTP 503, chaos switch on)", status=503)
                timeout = settings.llm_timeout_seconds
                if deadline is not None:
                    timeout = min(timeout, deadline - time.time())
                return run_with_timeout(
                    lambda: self._client().complete(model, messages, tools, timeout, tool_choice),
                    timeout_seconds=timeout + 2,
                )

            def guarded():
                # Checked outside the breaker: running out of run time is not a provider failure
                if deadline is not None and deadline - time.time() < MIN_CALL_SECONDS:
                    raise RunDeadlineExceeded(f"less than {MIN_CALL_SECONDS:g}s of the run deadline left")
                return breaker.call(attempt)

            started = time.time()
            with get_tracer().start_as_current_span(f"{agent}.llm_call") as span:
                span.set_attribute("llm.model", model)
                span.set_attribute("llm.step", step)
                span.set_attribute("prompt.version", prompt_version)
                try:
                    response = retry_with_backoff(
                        guarded,
                        max_retries=settings.max_retries,
                        on_retry=on_retry,
                    )
                except RunDeadlineExceeded:
                    recorder.event("llm_call", agent=agent, step=step, model=model, prompt_version=prompt_version,
                                   outcome="deadline", retries=retries, latency_ms=round((time.time() - started) * 1000, 1))
                    raise
                except Exception as error:
                    latency = time.time() - started
                    outcome = "breaker_open" if isinstance(error, CircuitBreakerOpenError) else "error"
                    LLM_CALLS_TOTAL.labels(agent=agent, model=model, outcome=outcome).inc()
                    span.set_attribute("llm.outcome", outcome)
                    recorder.event(
                        "llm_call", agent=agent, step=step, model=model, prompt_version=prompt_version,
                        outcome=outcome, error=str(error)[:300], retries=retries,
                        latency_ms=round(latency * 1000, 1), breaker_state=breaker.state,
                        fallback_position=position,
                    )
                    errors.append(f"{model}: {error}")
                    continue

                latency = time.time() - started
                cost = estimate_cost(response["prompt_tokens"], response["completion_tokens"])
                span.set_attribute("llm.outcome", "ok")
                span.set_attribute("llm.prompt_tokens", response["prompt_tokens"])
                span.set_attribute("llm.completion_tokens", response["completion_tokens"])
                span.set_attribute("llm.cost_usd", cost)

            LLM_CALLS_TOTAL.labels(agent=agent, model=model, outcome="ok").inc()
            LLM_TOKENS_TOTAL.labels(agent=agent, direction="prompt").inc(response["prompt_tokens"])
            LLM_TOKENS_TOTAL.labels(agent=agent, direction="completion").inc(response["completion_tokens"])
            LLM_COST_USD_TOTAL.labels(agent=agent).inc(cost)
            AGENT_STEP_SECONDS.labels(agent=agent, kind="llm_call").observe(latency)

            recorder.event(
                "llm_call", agent=agent, step=step, model=model, prompt_version=prompt_version,
                outcome="ok", retries=retries, latency_ms=round(latency * 1000, 1),
                prompt_tokens=response["prompt_tokens"], completion_tokens=response["completion_tokens"],
                cost_usd=cost, fallback_position=position,
                requested_tools=[call["name"] for call in response["tool_calls"]],
                tool_choice=tool_choice, finish_reason=response.get("finish_reason"),
                content_preview=(response["content"] or "")[:400],
            )

            response.update(model=model, cost_usd=cost, latency_ms=round(latency * 1000, 1), retries=retries)
            return response

        raise LLMUnavailableError("; ".join(errors) or "no model configured")


_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
