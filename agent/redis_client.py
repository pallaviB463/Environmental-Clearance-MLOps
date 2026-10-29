"""
Shared Redis connection. Redis is the only state shared between containers: the run
store, the queue, caches, rate-limit counters and the chaos switch all live here.
When REDIS_URL is empty (single-process local mode) every caller falls back to memory.
"""
import logging
import threading
import time
from typing import Optional

from agent.config import settings

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


logger = logging.getLogger("eia.redis")

_client = None
_last_failure = 0.0
_lock = threading.Lock()
RECONNECT_BACKOFF_SECONDS = 2.0


def get_redis() -> Optional["redis.Redis"]:
    """Return a live client, or None. A failed connection is retried after a short backoff."""
    global _client, _last_failure
    if not settings.redis_url or redis is None:
        return None
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        if time.time() - _last_failure < RECONNECT_BACKOFF_SECONDS:
            return None
        try:
            # socket_timeout must exceed the BLMOVE block time used by the worker
            client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=10,
                health_check_interval=15,
            )
            client.ping()
            _client = client
        except Exception as error:
            _last_failure = time.time()
            logger.warning(f"redis unavailable: {error}")
            return None
    return _client


def require_redis() -> "redis.Redis":
    client = get_redis()
    if client is None:
        raise RuntimeError("Redis is required but unreachable at REDIS_URL.")
    return client
