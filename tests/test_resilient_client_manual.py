from agent.llm.stub_client import StubLLMClient
from agent.llm.resilient_client import ResilientLLMClient
from agent.resilience.circuit_breaker import CircuitBreakerOpenError


print("\n=== TEST 1: NORMAL PROVIDER ===")

normal_stub = StubLLMClient(
    mode="normal"
)

normal_client = ResilientLLMClient(
    normal_stub
)

result = normal_client.complete(
    messages=[
        {
            "role": "user",
            "content": "Test message"
        }
    ],
    correlation_id="corr_normal",
    step="analyst"
)

print("SUCCESS")
print(result["text"])
print(
    "Circuit state:",
    normal_client.breaker.state
)


print("\n=== TEST 2: FAILING PROVIDER ===")

failing_stub = StubLLMClient(
    mode="error500"
)

failing_client = ResilientLLMClient(
    failing_stub
)

try:

    failing_client.complete(
        messages=[
            {
                "role": "user",
                "content": "Test failure"
            }
        ],
        correlation_id="corr_failure",
        step="analyst"
    )

except Exception as error:

    print("\nFAILURE HANDLED")
    print(
        "Error type:",
        type(error).__name__
    )
    print(
        "Circuit state:",
        failing_client.breaker.state
    )