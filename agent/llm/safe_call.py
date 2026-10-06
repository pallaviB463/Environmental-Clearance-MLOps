from typing import Any, Dict, List, Optional

from agent.llm.resilient_client import ResilientLLMClient


def safe_llm_call(
    client: ResilientLLMClient,
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    correlation_id: Optional[str] = None,
    step: Optional[str] = None
) -> Dict[str, Any]:

    try:
        response = client.complete(
            messages=messages,
            tools=tools,
            correlation_id=correlation_id,
            step=step
        )

        return {
            "success": True,
            "response": response,
            "error_type": None,
            "error_message": None
        }

    except Exception as error:
        return {
            "success": False,
            "response": None,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }