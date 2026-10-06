from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError
)
from typing import Callable, TypeVar

T = TypeVar("T")


class OperationTimeoutError(TimeoutError):
    """Raised when an operation exceeds its allowed time."""
    pass


def run_with_timeout(
    operation: Callable[[], T],
    timeout_seconds: float
) -> T:
    """
    Run an operation with a maximum allowed execution time.
    """

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(operation)

    try:
        result = future.result(timeout=timeout_seconds)

        executor.shutdown(wait=False)

        return result

    except FutureTimeoutError:

        executor.shutdown(
            wait=False,
            cancel_futures=True
        )

        raise OperationTimeoutError(
            f"Operation exceeded timeout of "
            f"{timeout_seconds} seconds."
        )