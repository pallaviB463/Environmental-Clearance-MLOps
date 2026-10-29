import logging
import random
import time
from typing import Callable, Optional, TypeVar

from agent.llm.client import ProviderError

T = TypeVar("T")

logger = logging.getLogger("eia.retry")


def is_transient(error: Exception) -> bool:
    if isinstance(error, ProviderError):
        return error.transient
    return isinstance(error, TimeoutError)


def retry_with_backoff(
    operation: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None
) -> T:
    """
    Retry transient failures with exponential backoff (0.5s, 1s, 2s, ...) plus jitter.
    Permanent failures (bad request, auth) and an open circuit breaker are not retried.
    """

    attempt = 0

    while True:
        try:
            return operation()

        except Exception as error:

            if not is_transient(error):
                raise

            attempt += 1

            if attempt > max_retries:
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            sleep_time = delay + random.uniform(0, 0.2)

            logger.warning(f"attempt {attempt} failed ({error}); retrying in {sleep_time:.2f}s")
            if on_retry:
                on_retry(attempt, error)

            time.sleep(sleep_time)
