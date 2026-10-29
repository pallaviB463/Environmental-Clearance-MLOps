import threading
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is blocked because the circuit is open."""
    pass


STATE_VALUES = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}


class CircuitBreaker:
    """
    CLOSED    calls pass through; consecutive failures are counted
    OPEN      calls fail immediately for `recovery_timeout` seconds
    HALF_OPEN one trial call is allowed; success closes, failure re-opens
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        name: str = "provider",
        on_state_change: Optional[Callable[[str, str], None]] = None
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self.on_state_change = on_state_change

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"
        self._lock = threading.Lock()

    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            if self.on_state_change:
                self.on_state_change(self.name, state)

    def call(
        self,
        operation: Callable[[], T]
    ) -> T:

        with self._lock:
            if self.state == "OPEN":
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._set_state("HALF_OPEN")
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker for {self.name} is OPEN "
                        f"({self.recovery_timeout - elapsed:.0f}s until a trial call)."
                    )

        try:
            result = operation()
        except Exception:
            with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.state == "HALF_OPEN" or self.failure_count >= self.failure_threshold:
                    self._set_state("OPEN")
            raise

        with self._lock:
            self.failure_count = 0
            self._set_state("CLOSED")
        return result
