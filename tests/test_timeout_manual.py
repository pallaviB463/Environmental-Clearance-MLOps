from agent.llm.stub_client import StubLLMClient
from agent.resilience.timeouts import (
    run_with_timeout,
    OperationTimeoutError
)


client = StubLLMClient(
    mode="normal",
    delay_seconds=3
)


try:

    result = run_with_timeout(
        lambda: client.complete(
            [
                {
                    "role": "user",
                    "content": "hello"
                }
            ]
        ),
        timeout_seconds=1
    )

    print("LLM result:", result)

except OperationTimeoutError as error:

    print("TIMEOUT CAUGHT SUCCESSFULLY")
    print(error)