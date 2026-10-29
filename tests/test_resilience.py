import time

import pytest

from agent.llm.client import LLMClient, LLMUnavailableError, ProviderError
from agent.llm.gateway import LLMGateway
from agent.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from agent.resilience.retry import retry_with_backoff
from agent.resilience.timeouts import OperationTimeoutError, run_with_timeout


def failing():
    raise ProviderError("503", status=503)


def test_breaker_opens_after_threshold_then_half_opens_and_closes():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.2)
    for _ in range(2):
        with pytest.raises(ProviderError):
            breaker.call(failing)
    assert breaker.state == "OPEN"
    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(lambda: "never called")
    time.sleep(0.25)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == "CLOSED"


def test_failed_trial_call_reopens_the_breaker():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
    with pytest.raises(ProviderError):
        breaker.call(failing)
    time.sleep(0.15)
    with pytest.raises(ProviderError):
        breaker.call(failing)
    assert breaker.state == "OPEN"


def test_retry_only_transient_errors():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("timeout", transient=True)
        return "ok"

    assert retry_with_backoff(flaky, max_retries=3, base_delay=0.01) == "ok"

    calls["n"] = 0

    def auth_error():
        calls["n"] += 1
        raise ProviderError("401", status=401, transient=False)

    with pytest.raises(ProviderError):
        retry_with_backoff(auth_error, max_retries=3, base_delay=0.01)
    assert calls["n"] == 1


def test_timeout():
    with pytest.raises(OperationTimeoutError):
        run_with_timeout(lambda: time.sleep(1), timeout_seconds=0.05)


class _Client(LLMClient):
    def __init__(self, fail_models):
        self.fail_models = fail_models
        self.calls = []

    def complete(self, model, messages, tools=None, timeout=None, tool_choice="auto"):
        self.calls.append(model)
        if model in self.fail_models:
            raise ProviderError(f"{model} down", status=503)
        return {"content": "{}", "tool_calls": [], "prompt_tokens": 10, "completion_tokens": 5,
                "raw_message": {"role": "assistant", "content": "{}"}}


def _gateway(client, models):
    gateway = LLMGateway(client=client)
    gateway.models = models
    gateway.breakers = {m: CircuitBreaker(failure_threshold=2, recovery_timeout=60, name=m) for m in models}
    return gateway


def test_gateway_falls_back_to_the_second_model():
    client = _Client(fail_models={"primary"})
    response = _gateway(client, ["primary", "fallback"]).complete([], None, "screener", "t", "v1")
    assert response["model"] == "fallback"


def test_gateway_raises_when_every_model_is_down():
    client = _Client(fail_models={"primary", "fallback"})
    with pytest.raises(LLMUnavailableError):
        _gateway(client, ["primary", "fallback"]).complete([], None, "screener", "t", "v1")


def test_no_call_starts_past_the_run_deadline_and_the_breaker_is_untouched():
    from agent.llm.client import RunDeadlineExceeded
    client = _Client(fail_models=set())
    gateway = _gateway(client, ["primary"])
    with pytest.raises(RunDeadlineExceeded):
        gateway.complete([], None, "screener", "t", "v1", deadline=time.time() + 1)
    assert client.calls == [] and gateway.breakers["primary"].failure_count == 0
