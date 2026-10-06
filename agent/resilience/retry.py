import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_with_backoff(
    operation: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0
) -> T:
    """
    Retry transient failures using exponential backoff
    with a small amount of jitter.
    """

    attempt = 0

    while True:
        try:
            return operation()

        except (TimeoutError, RuntimeError) as error:

            attempt += 1

            if attempt > max_retries:
                raise error

            delay = min(
                base_delay * (2 ** (attempt - 1)),
                max_delay
            )

            jitter = random.uniform(0, 0.2)

            sleep_time = delay + jitter

            print(
                f"Attempt {attempt} failed: {error}. "
                f"Retrying in {sleep_time:.2f}s..."
            )

            time.sleep(sleep_time)