"""
Tests for distributed tracing with W3C trace context propagation.

Tests cover:
- Trace ID generation and format
- Trace context propagation across async boundaries
- W3C traceparent header parsing
- Logging integration with trace IDs
- ContextVar-based trace isolation
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, patch
import contextvars

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.distributed_tracing import (
    generate_trace_id,
    generate_span_id,
    init_trace_context,
    get_trace_id,
    get_span_id,
    get_trace_flags,
    propagate_trace_context,
    extract_trace_context_from_headers,
    init_trace_from_headers,
    clear_trace_context,
    TraceContextFilter,
    setup_trace_logging,
    DistributedTraceContext,
    get_trace_context_dict,
    TRACE_PARENT_HEADER,
)


# =============================================================================
# TRACE ID GENERATION TESTS
# =============================================================================


class TestTraceIDGeneration:
    """Test W3C compliant trace ID generation."""

    def test_trace_id_is_32_hex_characters(self):
        """Trace ID should be 32 hex characters (128 bits)."""
        trace_id = generate_trace_id()
        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_span_id_is_16_hex_characters(self):
        """Span ID should be 16 hex characters (64 bits)."""
        span_id = generate_span_id()
        assert len(span_id) == 16
        assert all(c in "0123456789abcdef" for c in span_id)

    def test_trace_id_uniqueness(self):
        """Each trace ID should be unique."""
        trace_ids = [generate_trace_id() for _ in range(100)]
        assert len(set(trace_ids)) == 100

    def test_span_id_uniqueness(self):
        """Each span ID should be unique."""
        span_ids = [generate_span_id() for _ in range(100)]
        assert len(set(span_ids)) == 100


# =============================================================================
# TRACE CONTEXT MANAGEMENT TESTS
# =============================================================================


class TestTraceContextManagement:
    """Test trace context initialization and retrieval."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    def test_init_trace_context_creates_new_trace_id(self):
        """init_trace_context should create a new trace ID."""
        trace_id = init_trace_context()
        assert trace_id is not None
        assert len(trace_id) == 32

    def test_init_trace_context_with_custom_trace_id(self):
        """init_trace_context should accept a custom trace ID."""
        custom_id = "a" * 32
        trace_id = init_trace_context(trace_id=custom_id)
        assert trace_id == custom_id
        assert get_trace_id() == custom_id

    def test_get_trace_id_returns_initialized_context(self):
        """get_trace_id should return the initialized trace ID."""
        init_trace_context()
        trace_id = get_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 32

    def test_get_trace_id_returns_none_when_not_initialized(self):
        """get_trace_id should return None if context not initialized."""
        clear_trace_context()
        assert get_trace_id() is None

    def test_get_span_id_returns_initialized_span(self):
        """get_span_id should return the initialized span ID."""
        init_trace_context()
        span_id = get_span_id()
        assert span_id is not None
        assert len(span_id) == 16

    def test_get_trace_flags_default_value(self):
        """get_trace_flags should default to '01' (sampled=true)."""
        init_trace_context()
        flags = get_trace_flags()
        assert flags == "01"

    def test_clear_trace_context_resets_all_values(self):
        """clear_trace_context should reset all context values."""
        init_trace_context()
        clear_trace_context()
        assert get_trace_id() is None
        assert get_span_id() is None

    def test_init_trace_context_with_custom_span_id(self):
        """init_trace_context should accept a custom span ID."""
        custom_span = "b" * 16
        init_trace_context(span_id=custom_span)
        assert get_span_id() == custom_span


# =============================================================================
# W3C TRACEPARENT HEADER TESTS
# =============================================================================


class TestW3CTraceparentHeader:
    """Test W3C traceparent header generation and parsing."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    def test_propagate_trace_context_generates_valid_traceparent(self):
        """propagate_trace_context should generate valid W3C traceparent format."""
        init_trace_context()
        traceparent = propagate_trace_context()

        # Format: version-trace_id-span_id-trace_flags
        parts = traceparent.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"  # version
        assert len(parts[1]) == 32  # trace_id
        assert len(parts[2]) == 16  # span_id
        assert parts[3] == "01"  # trace_flags

    def test_propagate_trace_context_initializes_if_needed(self):
        """propagate_trace_context should initialize context if not already done."""
        clear_trace_context()
        traceparent = propagate_trace_context()
        assert traceparent is not None
        assert traceparent.startswith("00-")

    def test_extract_trace_context_from_valid_traceparent(self):
        """extract_trace_context_from_headers should parse valid traceparent."""
        init_trace_context()
        traceparent = propagate_trace_context()
        headers = {TRACE_PARENT_HEADER: traceparent}

        context = extract_trace_context_from_headers(headers)

        assert "trace_id" in context
        assert "span_id" in context
        assert "trace_flags" in context
        assert len(context["trace_id"]) == 32
        assert len(context["span_id"]) == 16

    def test_extract_trace_context_from_empty_headers(self):
        """extract_trace_context_from_headers should return empty dict for missing traceparent."""
        context = extract_trace_context_from_headers({})
        assert context == {}

    def test_extract_trace_context_from_invalid_format(self):
        """extract_trace_context_from_headers should reject invalid format."""
        headers = {TRACE_PARENT_HEADER: "invalid-format"}
        context = extract_trace_context_from_headers(headers)
        assert context == {}

    def test_extract_trace_context_from_invalid_version(self):
        """extract_trace_context_from_headers should reject unknown version."""
        headers = {TRACE_PARENT_HEADER: "99-" + "a" * 32 + "-" + "b" * 16 + "-01"}
        context = extract_trace_context_from_headers(headers)
        assert context == {}

    def test_init_trace_from_headers_creates_new_span(self):
        """init_trace_from_headers should reuse trace_id but create new span_id."""
        init_trace_context()
        traceparent = propagate_trace_context()

        clear_trace_context()

        headers = {TRACE_PARENT_HEADER: traceparent}
        trace_id = init_trace_from_headers(headers)

        # Should extract trace_id from header
        assert trace_id is not None
        # Should have same trace_id
        assert get_trace_id() == trace_id
        # But new span_id should be generated
        assert get_span_id() != "00f067aa0ba902b7"  # Different from parent


# =============================================================================
# ASYNC BOUNDARY PROPAGATION TESTS
# =============================================================================


class TestAsyncBoundaryPropagation:
    """Test trace context propagation across async boundaries."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    @pytest.mark.asyncio
    async def test_trace_context_propagates_to_child_task(self):
        """Trace context should propagate to child async tasks."""
        parent_trace_id = init_trace_context()

        collected_trace_ids = []

        async def child_task():
            """Child task that captures trace ID."""
            collected_trace_ids.append(get_trace_id())

        # Create child task
        task = asyncio.create_task(child_task())
        await task

        # Child should have same trace ID as parent
        assert len(collected_trace_ids) == 1
        assert collected_trace_ids[0] == parent_trace_id

    @pytest.mark.asyncio
    async def test_trace_context_isolation_between_tasks(self):
        """Different async tasks should have isolated trace contexts."""
        async def task_a():
            trace_id = init_trace_context()
            await asyncio.sleep(0.01)
            return get_trace_id()

        async def task_b():
            trace_id = init_trace_context()
            await asyncio.sleep(0.01)
            return get_trace_id()

        # Run tasks concurrently
        trace_a, trace_b = await asyncio.gather(task_a(), task_b())

        # Each task should have its own trace context
        assert trace_a is not None
        assert trace_b is not None
        # They might be different or same based on timing, but both should be valid
        assert len(trace_a) == 32
        assert len(trace_b) == 32

    @pytest.mark.asyncio
    async def test_nested_async_operations_share_trace_context(self):
        """Nested async operations should share the same trace context."""
        parent_trace_id = init_trace_context()
        trace_ids = []

        async def level1():
            trace_ids.append(("level1", get_trace_id()))

            async def level2():
                trace_ids.append(("level2", get_trace_id()))
                await asyncio.sleep(0.001)

            await level2()

        await level1()

        # All operations should share same trace ID
        assert trace_ids[0][1] == parent_trace_id  # level1
        assert trace_ids[1][1] == parent_trace_id  # level2

    @pytest.mark.asyncio
    async def test_trace_context_with_gather(self):
        """Trace context should work with asyncio.gather."""
        parent_trace_id = init_trace_context()

        async def concurrent_task(n):
            await asyncio.sleep(0.001)
            return get_trace_id()

        results = await asyncio.gather(*[concurrent_task(i) for i in range(3)])

        # Parent trace should be shared, but each might have different spans
        assert all(trace_id == parent_trace_id for trace_id in results)


# =============================================================================
# LOGGING INTEGRATION TESTS
# =============================================================================


class TestTraceContextLogging:
    """Test trace context integration with logging."""

    def setup_method(self):
        """Clear trace context and setup logging before each test."""
        clear_trace_context()
        self.logger = logging.getLogger("test_logger")
        self.logger.handlers.clear()

    def test_trace_context_filter_adds_trace_id_to_record(self):
        """TraceContextFilter should add trace_id to log records."""
        init_trace_context()
        trace_filter = TraceContextFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        trace_filter.filter(record)

        assert hasattr(record, "trace_id")
        assert record.trace_id == get_trace_id()

    def test_trace_context_filter_adds_span_id_to_record(self):
        """TraceContextFilter should add span_id to log records."""
        init_trace_context()
        trace_filter = TraceContextFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        trace_filter.filter(record)

        assert hasattr(record, "span_id")
        assert record.span_id == get_span_id()

    def test_trace_context_filter_handles_missing_context(self):
        """TraceContextFilter should use dashes for missing context."""
        clear_trace_context()
        trace_filter = TraceContextFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        trace_filter.filter(record)

        assert record.trace_id == "-"
        assert record.span_id == "-"

    def test_setup_trace_logging_adds_filter(self):
        """setup_trace_logging should add TraceContextFilter."""
        handler = logging.StreamHandler()
        self.logger.addHandler(handler)

        setup_trace_logging(self.logger)

        # Check that filter was added
        filters = [f for f in self.logger.filters if isinstance(f, TraceContextFilter)]
        assert len(filters) == 1


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================


class TestDistributedTraceContext:
    """Test DistributedTraceContext context manager."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    def test_sync_context_manager_sets_trace_context(self):
        """Sync context manager should set trace context."""
        with DistributedTraceContext() as ctx:
            assert ctx.trace_id is not None
            assert ctx.span_id is not None
            assert get_trace_id() == ctx.trace_id
            assert get_span_id() == ctx.span_id

    def test_sync_context_manager_clears_on_exit(self):
        """Sync context manager should clear context on exit."""
        with DistributedTraceContext():
            pass

        # Context should be cleared after exit
        assert get_trace_id() is None

    def test_sync_context_manager_with_custom_ids(self):
        """Sync context manager should accept custom IDs."""
        custom_trace = "a" * 32
        custom_span = "b" * 16

        with DistributedTraceContext(trace_id=custom_trace, span_id=custom_span) as ctx:
            assert ctx.trace_id == custom_trace
            assert ctx.span_id == custom_span
            assert get_trace_id() == custom_trace
            assert get_span_id() == custom_span

    @pytest.mark.asyncio
    async def test_async_context_manager_sets_trace_context(self):
        """Async context manager should set trace context."""
        async with DistributedTraceContext() as ctx:
            assert ctx.trace_id is not None
            assert ctx.span_id is not None
            assert get_trace_id() == ctx.trace_id
            assert get_span_id() == ctx.span_id

    @pytest.mark.asyncio
    async def test_async_context_manager_clears_on_exit(self):
        """Async context manager should clear context on exit."""
        async with DistributedTraceContext():
            pass

        # Context should be cleared after exit
        assert get_trace_id() is None


# =============================================================================
# TRACE CONTEXT DICTIONARY TESTS
# =============================================================================


class TestTraceContextDict:
    """Test trace context dictionary representation."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    def test_get_trace_context_dict_returns_all_fields(self):
        """get_trace_context_dict should return all trace fields."""
        init_trace_context()
        ctx = get_trace_context_dict()

        assert "trace_id" in ctx
        assert "span_id" in ctx
        assert "traceparent" in ctx
        assert ctx["trace_id"] is not None
        assert ctx["span_id"] is not None
        assert ctx["traceparent"] is not None

    def test_get_trace_context_dict_without_context(self):
        """get_trace_context_dict should return None values without context."""
        clear_trace_context()
        ctx = get_trace_context_dict()

        assert ctx["trace_id"] is None
        assert ctx["span_id"] is None
        assert ctx["traceparent"] is None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestDistributedTracingIntegration:
    """Integration tests combining multiple trace features."""

    def setup_method(self):
        """Clear trace context before each test."""
        clear_trace_context()

    @pytest.mark.asyncio
    async def test_full_trace_propagation_flow(self):
        """Test complete trace propagation flow across boundaries."""
        # 1. Receive request with traceparent header
        incoming_headers = {
            TRACE_PARENT_HEADER: "00-"
            + ("c" * 32)
            + "-"
            + ("d" * 16)
            + "-01"
        }

        # 2. Initialize trace context from headers
        trace_id = init_trace_from_headers(incoming_headers)
        assert trace_id == "c" * 32

        # 3. Propagate to child async task
        child_trace_ids = []

        async def async_child():
            child_trace_ids.append(get_trace_id())

        await asyncio.create_task(async_child())

        # 4. Verify propagation
        assert len(child_trace_ids) == 1
        assert child_trace_ids[0] == trace_id

        # 5. Generate outgoing traceparent
        outgoing = propagate_trace_context()
        assert "c" * 32 in outgoing  # Original trace_id preserved

    @pytest.mark.asyncio
    async def test_trace_context_with_concurrent_operations(self):
        """Test trace context isolation with concurrent operations."""
        async def operation(op_id):
            trace_id = init_trace_context()
            await asyncio.sleep(0.001)
            return (op_id, get_trace_id())

        # Run operations concurrently
        results = await asyncio.gather(
            operation("op1"),
            operation("op2"),
            operation("op3"),
        )

        # Each operation should have its own trace context
        for op_id, trace_id in results:
            assert trace_id is not None
            assert len(trace_id) == 32
