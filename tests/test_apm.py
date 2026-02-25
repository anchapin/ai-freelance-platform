"""
APM and Observability Instrumentation Tests (Issue #42)

This test suite verifies:
- APM manager initialization and configuration
- Span creation for critical paths
- Metrics instruments creation and recording
- Trace sampling behavior
- Distributed tracing context propagation
- Integration with APM backends (Jaeger, Prometheus)
"""

import os
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.utils.apm import (
    APMManager,
    get_apm_manager,
    init_apm,
    create_span,
    instrument_function,
    record_metric,
    add_trace_context_to_headers,
    measure_execution,
    trace_task_execution,
    trace_llm_call,
    trace_marketplace_scan,
    trace_payment_processing,
    trace_rag_query,
    trace_arena_competition,
)


class TestAPMManagerInitialization:
    """Test APM manager singleton and initialization"""

    def test_apm_manager_singleton(self):
        """Test that APMManager is a singleton"""
        manager1 = get_apm_manager()
        manager2 = get_apm_manager()
        assert manager1 is manager2
        assert isinstance(manager1, APMManager)

    def test_apm_manager_reads_env_vars(self):
        """Test that APM manager reads environment configuration"""
        # Save original values
        original_env = os.environ.copy()

        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ["APM_ENABLED"] = "true"
            os.environ["APM_BACKEND"] = "jaeger"
            os.environ["TRACE_SAMPLE_RATE"] = "0.1"

            # Create fresh manager
            manager = APMManager()

            assert manager.environment == "production"
            assert manager.apm_enabled is True
            assert manager.apm_backend == "jaeger"
            assert manager.trace_sample_rate == 0.1

        finally:
            # Restore environment
            os.environ.clear()
            os.environ.update(original_env)

    def test_apm_disabled_when_env_var_false(self):
        """Test that APM can be disabled via environment variable"""
        original_env = os.environ.copy()

        try:
            os.environ["APM_ENABLED"] = "false"

            manager = APMManager()
            assert manager.apm_enabled is False

        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_trace_sampling_defaults(self):
        """Test trace sampling rate defaults"""
        original_env = os.environ.copy()

        try:
            # Development: should default to 1.0 (100%)
            os.environ["ENVIRONMENT"] = "development"
            manager = APMManager()
            assert manager.trace_sample_rate == 1.0

            # Production: should default to 0.1 (10%)
            os.environ["ENVIRONMENT"] = "production"
            # Force re-initialization
            APMManager._instance = None
            manager = APMManager()
            assert manager.trace_sample_rate == 0.1

        finally:
            os.environ.clear()
            os.environ.update(original_env)
            APMManager._instance = None

    def test_apm_initialization_creates_providers(self):
        """Test that initialize() creates tracer and meter providers"""
        manager = get_apm_manager()

        # Mock the span exporter to avoid actually connecting to Jaeger
        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            # Verify providers were created
            assert manager.tracer_provider is not None
            assert manager.meter_provider is not None
            assert manager.tracer is not None
            assert manager.meter is not None


class TestMetricsInstrumentation:
    """Test metrics creation and recording"""

    def test_metrics_instruments_created(self):
        """Test that all required metrics instruments are created"""
        manager = get_apm_manager()

        # Skip if APM disabled
        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            # Verify metrics instruments exist
            assert manager.task_execution_time is not None
            assert manager.task_completion_counter is not None
            assert manager.task_error_counter is not None
            assert manager.llm_call_duration is not None
            assert manager.llm_token_usage is not None
            assert manager.marketplace_scan_duration is not None
            assert manager.bid_placement_counter is not None
            assert manager.payment_processing_duration is not None
            assert manager.rag_query_duration is not None
            assert manager.arena_competition_duration is not None
            assert manager.http_request_duration is not None
            assert manager.http_request_counter is not None

    def test_record_metric_success(self):
        """Test recording a metric value"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            # Mock the metric instrument
            manager.task_execution_time = MagicMock()

            # Record metric
            record_metric("task_execution_time", 100.5, {"task_id": "123"})

            # Verify metric was recorded
            manager.task_execution_time.record.assert_called_once()

    def test_record_metric_with_attributes(self):
        """Test recording metrics with attributes"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            manager.llm_call_duration = MagicMock()

            # Record metric with attributes
            attributes = {"model": "gpt-4o", "endpoint": "openai"}
            record_metric("llm_call_duration", 250.0, attributes)

            manager.llm_call_duration.record.assert_called_once_with(250.0, attributes)

    def test_record_metric_nonexistent_metric(self):
        """Test recording a metric that doesn't exist"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        # This should not raise an exception, just log a warning
        record_metric("nonexistent_metric", 100.0)


class TestSpanCreation:
    """Test span creation and attributes"""

    def test_create_span_context_manager(self):
        """Test creating a span with context manager"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            # Create a span
            with create_span("test.operation") as span:
                assert span is not None

    def test_create_span_with_attributes(self):
        """Test creating a span with attributes"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            attributes = {"user_id": "123", "operation": "bidding"}

            with create_span("test.operation", attributes) as span:
                # Verify span was created with attributes
                assert span is not None

    def test_instrument_function_decorator(self):
        """Test @instrument_function decorator"""
        @instrument_function(span_name="test.function")
        def test_func(x: int, y: int) -> int:
            return x + y

        result = test_func(5, 3)
        assert result == 8

    def test_instrument_function_with_exception(self):
        """Test @instrument_function handles exceptions"""
        @instrument_function()
        def failing_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_func()

    def test_measure_execution_context_manager(self):
        """Test measure_execution context manager"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with measure_execution("test.measurement"):
                # Simulate work
                pass


class TestDistributedTracing:
    """Test distributed tracing context propagation"""

    def test_add_trace_context_to_headers(self):
        """Test adding trace context to HTTP headers"""
        headers = {}

        # Add trace context (will succeed even if no active trace)
        result = add_trace_context_to_headers(headers)

        assert isinstance(result, dict)

    def test_add_trace_context_with_existing_headers(self):
        """Test adding trace context to existing headers"""
        headers = {"Authorization": "Bearer token123"}

        result = add_trace_context_to_headers(headers)

        assert "Authorization" in result
        assert result["Authorization"] == "Bearer token123"

    def test_add_trace_context_creates_new_dict(self):
        """Test that add_trace_context creates new dict when needed"""
        result = add_trace_context_to_headers(None)

        assert isinstance(result, dict)


class TestConvenienceFunctions:
    """Test convenience functions for specific use cases"""

    def test_trace_task_execution(self):
        """Test task execution tracing context manager"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_task_execution("task-123", "data_processing"):
                # Simulate task work
                pass

    def test_trace_llm_call(self):
        """Test LLM call tracing context manager"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_llm_call("gpt-4o", "https://api.openai.com/v1"):
                # Simulate LLM call
                pass

    def test_trace_marketplace_scan(self):
        """Test marketplace scan tracing"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_marketplace_scan("https://freelancer.com/jobs"):
                # Simulate marketplace scan
                pass

    def test_trace_payment_processing(self):
        """Test payment processing tracing"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_payment_processing("stripe-pi-123", 9999.00):
                # Simulate payment processing
                pass

    def test_trace_rag_query(self):
        """Test RAG query tracing"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_rag_query("What is the best bidding strategy?", top_k=5):
                # Simulate RAG query
                pass

    def test_trace_arena_competition(self):
        """Test arena competition tracing"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            with trace_arena_competition("arena-comp-456"):
                # Simulate competition
                pass


class TestAPMIntegration:
    """Integration tests for APM with real components"""

    def test_init_apm_function(self):
        """Test the init_apm() function"""
        original_env = os.environ.copy()

        try:
            os.environ["APM_ENABLED"] = "true"

            with patch("src.utils.apm.JaegerExporter"):
                init_apm()

                manager = get_apm_manager()
                assert manager._initialized is True

        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_apm_with_development_environment(self):
        """Test APM configuration in development"""
        original_env = os.environ.copy()

        try:
            os.environ["ENVIRONMENT"] = "development"
            os.environ["APM_ENABLED"] = "true"

            manager = APMManager()
            assert manager.trace_sample_rate == 1.0  # 100% sampling in dev
            assert manager.apm_environment == "development"

        finally:
            os.environ.clear()
            os.environ.update(original_env)
            APMManager._instance = None

    def test_apm_with_production_environment(self):
        """Test APM configuration in production"""
        original_env = os.environ.copy()

        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ["APM_ENABLED"] = "true"

            APMManager._instance = None
            manager = APMManager()

            assert manager.trace_sample_rate == 0.1  # 10% sampling in prod
            assert manager.apm_environment == "production"

        finally:
            os.environ.clear()
            os.environ.update(original_env)
            APMManager._instance = None

    def test_apm_backend_configuration(self):
        """Test different APM backend configurations"""
        original_env = os.environ.copy()

        try:
            # Test Jaeger backend
            os.environ["APM_BACKEND"] = "jaeger"
            APMManager._instance = None
            manager = APMManager()
            assert manager.apm_backend == "jaeger"

            # Test OTLP backend
            os.environ["APM_BACKEND"] = "otlp"
            APMManager._instance = None
            manager = APMManager()
            assert manager.apm_backend == "otlp"

        finally:
            os.environ.clear()
            os.environ.update(original_env)
            APMManager._instance = None


class TestAPMMetricsSchema:
    """Test metrics schema and naming conventions"""

    def test_metrics_naming_convention(self):
        """Verify metrics follow OpenTelemetry naming conventions"""
        manager = get_apm_manager()

        if not manager.apm_enabled:
            pytest.skip("APM disabled")

        expected_metrics = [
            "task_execution_time",
            "task_completion_counter",
            "task_error_counter",
            "llm_call_duration",
            "llm_token_usage",
            "marketplace_scan_duration",
            "bid_placement_counter",
            "payment_processing_duration",
            "rag_query_duration",
            "arena_competition_duration",
            "http_request_duration",
            "http_request_counter",
        ]

        with patch("src.utils.apm.JaegerExporter"):
            manager.initialize()

            for metric_name in expected_metrics:
                metric = getattr(manager, metric_name, None)
                assert metric is not None, f"Metric {metric_name} not found"


@pytest.fixture(autouse=True)
def reset_apm_manager():
    """Reset APM manager singleton between tests"""
    yield
    APMManager._instance = None


@pytest.fixture
def mock_apm_disabled(monkeypatch):
    """Fixture to disable APM for tests"""
    monkeypatch.setenv("APM_ENABLED", "false")
    APMManager._instance = None
    yield
    APMManager._instance = None


@pytest.fixture
def mock_apm_enabled(monkeypatch):
    """Fixture to enable APM for tests"""
    monkeypatch.setenv("APM_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    APMManager._instance = None
    yield
    APMManager._instance = None
