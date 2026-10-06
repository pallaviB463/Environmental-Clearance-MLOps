from agent.llm.stub_client import StubLLMClient
from agent.llm.resilient_client import ResilientLLMClient
from agent.llm.safe_call import safe_llm_call


print("\n=== NORMAL LLM ===")

normal_client = ResilientLLMClient(
    StubLLMClient(mode="normal")
)

normal_result = safe_llm_call(
    client=normal_client,
    messages=[
        {
            "role": "user",
            "content": "Hello"
        }
    ],
    correlation_id="corr_normal",
    step="analyst"
)

print(normal_result)


print("\n=== FAILED LLM ===")

failed_client = ResilientLLMClient(
    StubLLMClient(mode="error500")
)

failed_result = safe_llm_call(
    client=failed_client,
    messages=[
        {
            "role": "user",
            "content": "Hello"
        }
    ],
    correlation_id="corr_failed",
    step="analyst"
)

print(failed_result)