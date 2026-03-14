"""
OpenTelemetry tracing — enabled when ENABLE_TRACING=true in .env.
Jaeger receives traces via OTLP (HTTP) on JAEGER_ENDPOINT.

Deferred: wire this up when running `docker compose --profile observability up`.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(endpoint: str) -> None:
    """Configure OTLP exporter pointing at Jaeger."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
