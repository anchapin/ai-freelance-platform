"""
APM (Application Performance Monitoring) and OpenTelemetry Integration

This module provides comprehensive APM instrumentation for production monitoring
using OpenTelemetry for vendor-neutral observability. It instruments critical paths:
- Task execution and lifecycle
- LLM API calls and performance
- Marketplace scanning and bid placement
- Payment processing and Stripe webhooks
- Arena competitions and model comparisons
- RAG queries and vector database operations

Features:
- Automatic span creation for instrumented functions
- Custom metrics: latency, error rates, task completion times
- Trace sampling (configurable, default 10% in production)
- APM context propagation for distributed tracing
- Integration with multiple APM backends (Jaeger, Datadog, etc.)
"""

import os
import time
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Exporters for various APM backends
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Instrumentation auto-loaders
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# Optional HTTPX instrumentation (may not be available)
try:
    from opentelemetry.instrumentation.httpx import HTTPXInstrumentor
except (ImportError, AttributeError):
    HTTPXInstrumentor = None

# Trace context propagation
from opentelemetry.propagate import inject as inject_context

# Optional: propagators (may not be installed)
try:
    from opentelemetry.propagators.jaeger.jaeger import JaegerPropagator
except ImportError:
    JaegerPropagator = None

try:
    from opentelemetry.propagators.composite import CompositePropagator
except ImportError:
    CompositePropagator = None

try:
    from opentelemetry.propagators.b3 import B3MultiFormat
except ImportError:
    B3MultiFormat = None

from ..utils.logger import get_logger

logger = get_logger(__name__)




    def initialize(self) -> None:
        """Initialize APM infrastructure"""
        if not self.apm_enabled:
            logger.info("APM disabled via APM_ENABLED=false")
            return

        logger.info(
            f"Initializing APM: backend={self.apm_backend}, "
            f"sample_rate={self.trace_sample_rate}, environment={self.apm_environment}"
        )

        try:
            self._setup_tracer_provider()
            self._setup_meter_provider()
            self._setup_span_processors()
            self._create_metrics()
            self._setup_instrumentation()
            self._setup_propagators()
            logger.info("✓ APM initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize APM: {e}", exc_info=True)
            self.apm_enabled = False

    def _setup_tracer_provider(self) -> None:
        """Initialize TracerProvider with sampling"""
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        resource = Resource.create({
            "service.name": self.apm_service_name,
            "service.version": self.apm_version,
            "deployment.environment": self.apm_environment,
            "host.name": os.environ.get("HOSTNAME", "unknown"),
        })

        self.tracer_provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(self.trace_sample_rate),
        )

        trace.set_tracer_provider(self.tracer_provider)
        self.tracer = trace.get_tracer(__name__)
        logger.info(f"✓ TracerProvider initialized with {self.trace_sample_rate*100}% sampling")

    def _setup_meter_provider(self) -> None:
        """Initialize MeterProvider for metrics"""
        resource = Resource.create({
            "service.name": self.apm_service_name,
            "service.version": self.apm_version,
        })

        # Use Prometheus reader for local/production scraping
        prometheus_reader = PrometheusMetricReader()

        self.meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[prometheus_reader],
        )

        metrics.set_meter_provider(self.meter_provider)
        self.meter = metrics.get_meter(__name__)
        logger.info("✓ MeterProvider initialized with Prometheus reader")

    def _setup_span_processors(self) -> None:
        """Setup span processors based on configured backend"""
        if not self.tracer_provider:
            return

        if self.apm_backend == "jaeger":
            exporter = JaegerExporter(
                agent_host_name=self.jaeger_endpoint.split("://")[1].split(":")[0]
                if "://" in self.jaeger_endpoint
                else "localhost",
                agent_port=int(
                    self.jaeger_endpoint.split(":")[-1]
                    if ":" in self.jaeger_endpoint
                    else "6831"
                ),
            )
            self.tracer_provider.add_span_processor(
                BatchSpanProcessor(exporter)
            )
            logger.info(f"✓ Jaeger span processor configured: {self.jaeger_endpoint}")

        elif self.apm_backend == "otlp":
            exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint)
            self.tracer_provider.add_span_processor(
                BatchSpanProcessor(exporter)
            )
            logger.info(f"✓ OTLP span processor configured: {self.otlp_endpoint}")

        else:
            logger.warning(f"Unknown APM backend: {self.apm_backend}")

    def _create_metrics(self) -> None:
        """Create metrics instruments"""
        if not self.meter:
            return

        # Task execution metrics
        self.task_execution_time = self.meter.create_histogram(
            "task.execution.time",
            unit="ms",
            description="Task execution time in milliseconds",
        )
        self.task_completion_counter = self.meter.create_counter(
            "task.completion.total",
            unit="1",
            description="Total completed tasks",
        )
        self.task_error_counter = self.meter.create_counter(
            "task.error.total",
            unit="1",
            description="Total task errors",
        )

        # LLM metrics
        self.llm_call_duration = self.meter.create_histogram(
            "llm.call.duration",
            unit="ms",
            description="LLM API call duration in milliseconds",
        )
        self.llm_token_usage = self.meter.create_histogram(
            "llm.token.usage",
            unit="1",
            description="LLM token usage per call",
        )

        # Marketplace scanning metrics
        self.marketplace_scan_duration = self.meter.create_histogram(
            "marketplace.scan.duration",
            unit="ms",
            description="Marketplace scan duration in milliseconds",
        )

        # Bid placement metrics
        self.bid_placement_counter = self.meter.create_counter(
            "bid.placement.total",
            unit="1",
            description="Total bids placed",
        )

        # Payment metrics
        self.payment_processing_duration = self.meter.create_histogram(
            "payment.processing.duration",
            unit="ms",
            description="Payment processing duration in milliseconds",
        )

        # RAG query metrics
        self.rag_query_duration = self.meter.create_histogram(
            "rag.query.duration",
            unit="ms",
            description="RAG query duration in milliseconds",
        )

        # Arena competition metrics
        self.arena_competition_duration = self.meter.create_histogram(
            "arena.competition.duration",
            unit="ms",
            description="Arena competition duration in milliseconds",
        )

        # HTTP request metrics
        self.http_request_duration = self.meter.create_histogram(
            "http.request.duration",
            unit="ms",
            description="HTTP request duration in milliseconds",
        )
        self.http_request_counter = self.meter.create_counter(
            "http.request.total",
            unit="1",
            description="Total HTTP requests",
        )

        logger.info("✓ Created 11 metrics instruments")

    def _setup_instrumentation(self) -> None:
        """Auto-instrument framework libraries"""
        try:
            # FastAPI instrumentation
            FastAPIInstrumentor.instrument()
            logger.info("✓ FastAPI instrumented")
        except Exception as e:
            logger.debug(f"Failed to instrument FastAPI: {e}")

        try:
            # SQLAlchemy instrumentation
            SQLAlchemyInstrumentor().instrument()
            logger.info("✓ SQLAlchemy instrumented")
        except Exception as e:
            logger.debug(f"Failed to instrument SQLAlchemy: {e}")

        try:
            # HTTP client instrumentation
            if HTTPXInstrumentor:
                HTTPXInstrumentor().instrument()
            RequestsInstrumentor().instrument()
            logger.info("✓ HTTP clients instrumented")
        except Exception as e:
            logger.debug(f"Failed to instrument HTTP clients: {e}")

    def _setup_propagators(self) -> None:
        """Setup context propagators for distributed tracing"""
        # Build list of available propagators
        propagators = []

        if JaegerPropagator:
            propagators.append(JaegerPropagator())

        if B3MultiFormat:
            propagators.append(B3MultiFormat())

        if propagators and CompositePropagator:
            propagator = CompositePropagator(propagators)
            logger.info(f"✓ Configured {len(propagators)} trace context propagators")
        elif propagators:
            logger.info(f"✓ Available {len(propagators)} propagators")
        else:
            logger.warning("No trace context propagators available")


# Global singleton
_apm_manager: Optional[APMManager] = None


def get_apm_manager() -> APMManager:
    """Get or create APM manager singleton"""
    global _apm_manager
    if _apm_manager is None:
        _apm_manager = APMManager()
    return _apm_manager


def init_apm() -> None:
    """Initialize APM infrastructure"""
    manager = get_apm_manager()
    manager.initialize()


# Decorators and context managers for instrumentation

def create_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Any:
    """
    Create a new span with optional attributes.

    Args:
        name: Span name
        attributes: Optional span attributes

    Returns:
        Context manager for the span
    """
    manager = get_apm_manager()
    if not manager.apm_enabled or not manager.tracer:
        @contextmanager
        def noop():
            yield
        return noop()

    span = manager.tracer.start_span(name)
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    @contextmanager
    def span_context():
        try:
            yield span
        finally:
            span.end()

    return span_context()


def instrument_function(
    span_name: Optional[str] = None,
    record_result: bool = True,
):
    """
    Decorator to instrument a function with span creation and metric recording.

    Args:
        span_name: Custom span name (defaults to function name)
        record_result: Whether to record result/error in span attributes
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            manager = get_apm_manager()
            if not manager.apm_enabled or not manager.tracer:
                return func(*args, **kwargs)

            name = span_name or func.__name__
            start_time = time.time()

            with manager.tracer.start_as_current_span(name) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)

                try:
                    result = func(*args, **kwargs)
                    if record_result:
                        span.set_attribute("function.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("function.success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    raise
                finally:
                    duration_ms = (time.time() - start_time) * 1000
                    span.set_attribute("function.duration_ms", duration_ms)

        return wrapper

    return decorator


def record_metric(
    metric_name: str,
    value: float,
    attributes: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a metric value.

    Args:
        metric_name: Metric name (must exist in APM manager)
        value: Metric value
        attributes: Optional attributes/labels
    """
    manager = get_apm_manager()
    if not manager.apm_enabled or not manager.meter:
        return

    # Get metric instrument if it exists
    metric = getattr(manager, metric_name.replace(".", "_"), None)
    if metric is None:
        logger.warning(f"Metric not found: {metric_name}")
        return

    # Record with attributes if provided
    if attributes:
        metric.record(value, attributes)
    else:
        metric.record(value)


def add_trace_context_to_headers(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Add trace context to headers for distributed tracing.

    Args:
        headers: Optional existing headers dict

    Returns:
        Headers dict with trace context injected
    """
    if headers is None:
        headers = {}

    try:
        inject_context(headers)
    except Exception as e:
        logger.debug(f"Failed to inject trace context: {e}")

    return headers


# Convenience functions for specific use cases

def measure_execution(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager to measure execution time and create a span.

    Args:
        name: Span/metric name
        attributes: Optional attributes

    Returns:
        Context manager yielding duration tracking
    """
    manager = get_apm_manager()
    start_time = time.time()

    with create_span(name, attributes) as span:
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            if span:
                span.set_attribute("duration_ms", duration_ms)
            logger.debug(f"{name} took {duration_ms:.2f}ms")


def trace_task_execution(task_id: str, task_type: str):
    """Context manager for task execution tracing"""
    return measure_execution(
        "task.execution",
        {"task.id": task_id, "task.type": task_type},
    )


def trace_llm_call(model: str, endpoint: str):
    """Context manager for LLM call tracing"""
    return measure_execution(
        "llm.call",
        {"llm.model": model, "llm.endpoint": endpoint},
    )


def trace_marketplace_scan(marketplace_url: str):
    """Context manager for marketplace scan tracing"""
    return measure_execution(
        "marketplace.scan",
        {"marketplace.url": marketplace_url},
    )


def trace_payment_processing(payment_id: str, amount: float):
    """Context manager for payment processing tracing"""
    return measure_execution(
        "payment.processing",
        {"payment.id": payment_id, "payment.amount": amount},
    )


def trace_rag_query(query: str, top_k: int = 5):
    """Context manager for RAG query tracing"""
    return measure_execution(
        "rag.query",
        {"rag.query_length": len(query), "rag.top_k": top_k},
    )


def trace_arena_competition(competition_id: str):
    """Context manager for arena competition tracing"""
    return measure_execution(
        "arena.competition",
        {"arena.competition_id": competition_id},
    )
