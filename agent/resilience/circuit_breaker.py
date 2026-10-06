import time
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is blocked because the circuit is open."""
    pass


class CircuitBreaker:

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.failure_count = 0
        self.last_failure_time = None

        # CLOSED = calls allowed normally
        # OPEN = calls blocked
        # HALF_OPEN = one test call allowed
        self.state = "CLOSED"

    def call(
        self,
        operation: Callable[[], T]
    ) -> T:

        # ---------------------------------------------
        # If OPEN, check whether recovery time passed
        # ---------------------------------------------

        if self.state == "OPEN":

            elapsed = (
                time.time() - self.last_failure_time
            )

            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError(
                    "Circuit breaker is OPEN. "
                    "Provider call blocked."
                )

        # ---------------------------------------------
        # Try provider operation
        # ---------------------------------------------

        try:
            result = operation()

            # Successful call resets breaker
            self.failure_count = 0
            self.state = "CLOSED"

            return result

        except Exception:

            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

            raise