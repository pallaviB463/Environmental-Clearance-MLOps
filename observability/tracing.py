"""
OpenTelemetry tracing exported over OTLP/HTTP to Jaeger (Requirement D5).

The trace context travels with the run: the API injects it into the queue message,
the worker continues it, and the worker injects it into the HTTP call to the
verifier service, so one run is one trace across all three services.
"""
from typing import Dict, Optional

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agent.config import settings


_configured = False


def setup_tracing(service: str) -> None:
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        # Short timeouts: if Jaeger is gone (e.g. during `compose down`) a service must still
        # stop within Docker's 10 s grace period instead of hanging on a final flush
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint.rstrip("/") + "/v1/traces", timeout=2)
        provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=2000))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str = "eia"):
    return trace.get_tracer(name)


def inject_context() -> Dict[str, str]:
    carrier: Dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_context(carrier: Optional[Dict[str, str]]):
    return propagate.extract(carrier or {})


def current_trace_id() -> Optional[str]:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
