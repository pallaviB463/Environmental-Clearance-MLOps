from agent.llm.stub_client import StubLLMClient
from agent.resilience.circuit_breaker import CircuitBreaker


client = StubLLMClient(mode="error500")

breaker = CircuitBreaker(
    failure_threshold=2
)


for i in range(3):

    try:
        breaker.call(
            lambda: client.complete([])
        )

    except Exception as error:
        print(
            "Call",
            i + 1,
            "->",
            type(error).__name__,
            "| State:",
            breaker.state
        )