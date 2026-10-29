"""
Fault injection for demonstrating A5 on request (demo item 8). When the switch is on,
every LLM call fails as an HTTP 503 before reaching the provider, so the retries, the
circuit breaker and the degraded path can be shown without waiting for a real outage.
Stored in Redis so one switch affects every worker replica.
"""
from agent.redis_client import get_redis


CHAOS_KEY = "eia:chaos:llm"
_local_flag = {"llm_down": False}


def set_llm_down(down: bool) -> None:
    client = get_redis()
    if client is not None:
        if down:
            client.set(CHAOS_KEY, "down")
        else:
            client.delete(CHAOS_KEY)
    _local_flag["llm_down"] = down


def llm_down() -> bool:
    client = get_redis()
    if client is not None:
        try:
            return client.get(CHAOS_KEY) == "down"
        except Exception:
            return _local_flag["llm_down"]
    return _local_flag["llm_down"]
