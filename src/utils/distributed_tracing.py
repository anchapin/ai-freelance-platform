"""
Distributed Tracing with W3C Trace Context support.

Provides:
- W3C standard trace ID generation and propagation
- ContextVar-based propagation across async boundaries
- Logging integration to include trace IDs in all logs
- Request/response header management for distributed tracing

Usage:
    from src.utils.distributed_tracing import (
        init_trace_context,
        get_trace_id,
        propagate_trace_context,
    )

    # At the start of a request/task
    trace_id = init_trace_context()

    # Access in nested async operations (automatically propagated)
    current_trace_id = get_trace_id()

    # For HTTP requests, propagate trace ID in headers
    headers = {"traceparent": propagate_trace_context()}
"""

import contextvars
import uuid
import logging
from typing import Optional, Dict, Any


# W3C Trace Context specification constants
TRACE_PARENT_HEADER = "traceparent"
TRACE_STATE_HEADER = "tracestate"

# ContextVar for storing the current trace ID across async boundaries
_trace_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=None
)

# ContextVar for storing the parent span ID
_span_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "span_id", default=None
)

# ContextVar for storing the trace flags (sampled flag)
_trace_flags_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_flags", default="01"  # Default: sampled=true
)


def generate_trace_id() -> str:
    """
    Generate a W3C-compliant trace ID (128-bit, 32 hex characters).

    Returns:
        A 32-character hexadecimal string (128-bit random value)
    """
    # W3C trace ID format: 32 hex characters representing 128 bits
    trace_id = uuid.uuid4().hex  # 32 hex chars
    return trace_id


def generate_span_id() -> str:
    """
    Generate a W3C-compliant span ID (64-bit, 16 hex characters).

    Returns:
        A 16-character hexadecimal string (64-bit random value)
    """
    # W3C span ID format: 16 hex characters representing 64 bits
    # We use the first 16 characters of a UUID hex
    span_id = uuid.uuid4().hex[:16]
    return span_id


def init_trace_context(trace_id: Optional[str] = None, span_id: Optional[str] = None) -> str:
    """
    Initialize a new trace context for the current async task.

    This should be called at the start of request handling to establish
    a distributed trace ID that will be propagated across async boundaries.

    Args:
        trace_id: Optional pre-generated trace ID. If not provided, generates a new one.
        span_id: Optional pre-generated span ID. If not provided, generates a new one.

    Returns:
        The initialized trace ID
    """
    if not trace_id:
        trace_id = generate_trace_id()
    if not span_id:
        span_id = generate_span_id()

    _trace_id_context.set(trace_id)
    _span_id_context.set(span_id)
    _trace_flags_context.set("01")  # sampled=true

    return trace_id


def get_trace_id() -> Optional[str]:
    """
    Get the current trace ID for the async context.

    This is automatically propagated across async boundaries via contextvars.
    If no trace context has been initialized, returns None.

    Returns:
        The current trace ID or None if no context exists
    """
    return _trace_id_context.get()


def get_span_id() -> Optional[str]:
    """Get the current span ID for the async context."""
    return _span_id_context.get()


def get_trace_flags() -> str:
    """Get the current trace flags (sampling decision)."""
    return _trace_flags_context.get()


def propagate_trace_context() -> str:
    """
    Generate a W3C traceparent header value from the current context.

    Format: traceparent = version-trace_id-span_id-trace_flags
    Example: "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    Returns:
        A traceparent header value suitable for HTTP headers
    """
    trace_id = get_trace_id()
    span_id = get_span_id()
    trace_flags = get_trace_flags()

    if not trace_id or not span_id:
        # If no context, initialize one
        trace_id = generate_trace_id()
        span_id = generate_span_id()

    # W3C traceparent format: version (2 hex) - trace_id (32 hex) - span_id (16 hex) - flags (2 hex)
    return f"00-{trace_id}-{span_id}-{trace_flags}"


def extract_trace_context_from_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Extract trace context from request headers (W3C traceparent format).

    Args:
        headers: Dictionary of HTTP headers

    Returns:
        Dictionary with 'trace_id', 'span_id', and 'trace_flags' extracted from traceparent header
    """
    traceparent = headers.get(TRACE_PARENT_HEADER)
    if not traceparent:
        return {}

    try:
        # Parse W3C traceparent format: version-trace_id-span_id-trace_flags
        parts = traceparent.split("-")
        if len(parts) != 4:
            return {}

        version, trace_id, parent_span_id, trace_flags = parts

        # Validate format
        if version != "00":  # Only support version 0
            return {}
        if len(trace_id) != 32 or len(parent_span_id) != 16 or len(trace_flags) != 2:
            return {}

        return {
            "trace_id": trace_id,
            "span_id": parent_span_id,
            "trace_flags": trace_flags,
        }
    except (ValueError, IndexError):
        return {}


def init_trace_from_headers(headers: Dict[str, str]) -> str:
    """
    Initialize trace context from request headers (for propagating from upstream services).

    Args:
        headers: Dictionary of HTTP headers

    Returns:
        The trace ID (either extracted or newly generated)
    """
    context = extract_trace_context_from_headers(headers)

    if context:
        # Propagate existing trace context and generate new span
        trace_id = context["trace_id"]
        new_span_id = generate_span_id()
        trace_flags = context.get("trace_flags", "01")

        _trace_id_context.set(trace_id)
        _span_id_context.set(new_span_id)
        _trace_flags_context.set(trace_flags)

        return trace_id
    else:
        # No incoming trace context, initialize new
        return init_trace_context()


def clear_trace_context() -> None:
    """Clear the current trace context."""
    _trace_id_context.set(None)
    _span_id_context.set(None)
    _trace_flags_context.set("01")


class TraceContextFilter(logging.Filter):
    """
    Logging filter that adds trace ID and span ID to all log records.

    This filter automatically injects the current distributed trace context
    into all log messages, enabling correlation of logs across service boundaries.

    Usage:
        logger = logging.getLogger(__name__)
        logger.addFilter(TraceContextFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add trace context to log record.

        Args:
            record: The log record to filter

        Returns:
            True to allow the record to be logged
        """
        trace_id = get_trace_id()
        span_id = get_span_id()

        # Add trace context to the record
        record.trace_id = trace_id or "-"
        record.span_id = span_id or "-"

        return True


def setup_trace_logging(logger: logging.Logger, pattern: str = "[%(trace_id)s] [%(span_id)s]") -> None:
    """
    Setup a logger with trace context logging.

    Adds the TraceContextFilter and updates the formatter to include trace IDs.

    Args:
        logger: The logger to configure
        pattern: Format pattern for trace context (default: "[%(trace_id)s] [%(span_id)s]")
    """
    # Add the trace context filter
    trace_filter = TraceContextFilter()
    logger.addFilter(trace_filter)

    # Update all handlers to include trace context in their format
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            current_format = handler.formatter._fmt if handler.formatter else ""
            # Insert trace pattern at the beginning
            if pattern not in current_format:
                new_format = f"{pattern} {current_format}"
                handler.setFormatter(
                    logging.Formatter(new_format, datefmt="%Y-%m-%d %H:%M:%S")
                )


class DistributedTraceContext:
    """
    Context manager for managing distributed trace scope.

    Useful for explicit trace context management in sync-to-async transitions.

    Usage:
        async def handle_request():
            with DistributedTraceContext() as ctx:
                print(ctx.trace_id)  # Auto-generated trace ID
                # Perform async work...
    """

    def __init__(self, trace_id: Optional[str] = None, span_id: Optional[str] = None):
        """
        Initialize trace context.

        Args:
            trace_id: Optional pre-generated trace ID
            span_id: Optional pre-generated span ID
        """
        self.trace_id = trace_id or generate_trace_id()
        self.span_id = span_id or generate_span_id()
        self._token = None

    def __enter__(self):
        """Enter the trace context."""
        self._token = _trace_id_context.set(self.trace_id)
        _span_id_context.set(self.span_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the trace context."""
        if self._token:
            _trace_id_context.reset(self._token)

    async def __aenter__(self):
        """Async enter the trace context."""
        self._token = _trace_id_context.set(self.trace_id)
        _span_id_context.set(self.span_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async exit the trace context."""
        if self._token:
            _trace_id_context.reset(self._token)


def get_trace_context_dict() -> Dict[str, Any]:
    """
    Get the current trace context as a dictionary.

    Useful for logging, debugging, or passing context to other systems.

    Returns:
        Dictionary with 'trace_id', 'span_id', and 'traceparent' keys
    """
    trace_id = get_trace_id()
    span_id = get_span_id()

    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "traceparent": propagate_trace_context() if trace_id else None,
    }
