"""
Run recorder: an append-only event log per run (Requirement D5, "given a run id, the
entire run must be reconstructible").

Every step, tool call (with query and returned passages), LLM call (with prompt
version, tokens, cost and latency) and the verification outcome is appended here.
The worker plugs in a sink that writes to Redis, so GET /v1/screenings/{id}/trace
can replay the run from any service.
"""
import contextvars
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

from observability.tracing import get_tracer


Sink = Callable[[str, Dict[str, Any]], None]


class RunRecorder:

    def __init__(self, run_id: str, correlation_id: str, sink: Optional[Sink] = None):
        self.run_id = run_id
        self.correlation_id = correlation_id
        self.sink = sink
        self.events: List[Dict[str, Any]] = []
        self.started = time.time()
        self._seq = 0

    def event(self, kind: str, **data) -> Dict[str, Any]:
        self._seq += 1
        entry = {
            "seq": self._seq,
            "ts": round(time.time(), 4),
            "t_offset_ms": round((time.time() - self.started) * 1000, 1),
            "kind": kind,
            **data,
        }
        self.events.append(entry)
        if self.sink:
            try:
                self.sink(self.run_id, entry)
            except Exception:
                pass
        return entry

    @contextmanager
    def step(self, kind: str, agent: str, **attributes):
        """Time a unit of work as both a trace span and a recorded event."""
        tracer = get_tracer()
        started = time.time()
        with tracer.start_as_current_span(f"{agent}.{kind}") as span:
            span.set_attribute("run.id", self.run_id)
            span.set_attribute("correlation.id", self.correlation_id)
            span.set_attribute("agent", agent)
            for key, value in attributes.items():
                if isinstance(value, (str, int, float, bool)):
                    span.set_attribute(key, value)
            outcome: Dict[str, Any] = {}
            try:
                yield outcome
            except Exception as error:
                outcome.setdefault("error", f"{type(error).__name__}: {error}")
                span.record_exception(error)
                raise
            finally:
                latency_ms = round((time.time() - started) * 1000, 1)
                for key, value in outcome.items():
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(f"result.{key}", value)
                self.event(kind, agent=agent, latency_ms=latency_ms, **attributes, **outcome)


_current: contextvars.ContextVar[Optional[RunRecorder]] = contextvars.ContextVar("recorder", default=None)


def set_recorder(recorder: Optional[RunRecorder]):
    return _current.set(recorder)


def get_recorder() -> RunRecorder:
    recorder = _current.get()
    if recorder is None:
        recorder = RunRecorder(run_id="adhoc", correlation_id="adhoc")
        _current.set(recorder)
    return recorder
