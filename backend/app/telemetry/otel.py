"""
otel.py — OpenTelemetry instrumentation stubs.

Production TODO: replace these stubs with real OTel spans.

Suggested setup:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    pip install opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-sqlalchemy

Wiring (in main.py lifespan):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)

Span suggestions per component:
    - POST /incidents          → span: "incident.create"
    - run_investigation()      → span: "investigation.run"  (root span for full agent loop)
    - BaseTool.run()           → span: "tool.{tool_name}"   (child span, tag: cache_hit)
    - OpenAI API call          → span: "openai.chat"        (tag: model, iteration)
    - repo.log_tool_call()     → span: "db.log_tool_call"   (child of tool span)

Useful tags to attach:
    run_id, incident_id, tool_name, cache_hit, latency_ms, model, iteration, status
"""


def get_tracer(name: str):
    """
    Return a no-op tracer. Replace with:
        from opentelemetry import trace
        return trace.get_tracer(name)
    """
    return _NoOpTracer()


class _NoOpTracer:
    """Tracer stub — all methods are no-ops so calling code works unchanged today."""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpanContext()


class _NoOpSpanContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key: str, value) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, status) -> None:
        pass
