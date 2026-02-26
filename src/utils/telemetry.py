import os
from opentelemetry import trace
from ..config import get_traceloop_url
from ..utils.logger import get_logger

# Import APM initialization (Issue #42)
from ..utils.apm import init_apm, get_apm_manager

# Optional dependencies
try:
    from traceloop.sdk import Traceloop
    TRACELOOP_AVAILABLE = True
except ImportError:
    TRACELOOP_AVAILABLE = False

try:
    import phoenix as px
    PHOENIX_AVAILABLE = True
except ImportError:
    PHOENIX_AVAILABLE = False

logger = get_logger(__name__)


def get_tracer(name: str) -> trace.Tracer:
    """
    Get an OpenTelemetry tracer.

    Args:
        name: Name of the tracer (usually __name__)

    Returns:
        Tracer instance
    """
    return trace.get_tracer(name)


def init_observability():
    """
    Initializes comprehensive observability stack:
    1. APM infrastructure for production monitoring (Issue #42)
    2. Local tracing via Arize Phoenix and Traceloop
    3. OpenTelemetry context propagation for distributed tracing

    Captures LLM calls, token usage, latency, and application metrics automatically.

    Note: In production (ENVIRONMENT != "development"), Phoenix should be run
    as a standalone Docker container to avoid port conflicts with multiple workers.
    """
    logger.info("Initializing observability stack...")

    # 1. Initialize APM infrastructure (Issue #42)
    # Configures Jaeger, Prometheus metrics, trace sampling, and auto-instrumentation
    try:
        init_apm()
        logger.info("✓ APM infrastructure initialized")
    except Exception as e:
        logger.error(f"Failed to initialize APM: {e}", exc_info=True)

    # 2. Only launch Phoenix dashboard in development mode
    # In production, run Phoenix as a separate Docker container instead
    if PHOENIX_AVAILABLE and os.environ.get("ENVIRONMENT") == "development":
        try:
            session = px.launch_app()
            print(f"🔭 Phoenix Observability Dashboard running at: {session.url}")
        except Exception as e:
            logger.warning(f"Failed to launch Phoenix dashboard: {e}")
    elif not PHOENIX_AVAILABLE:
        logger.debug("Phoenix not available (optional dependency)")

    # 3. Tell OpenTelemetry to send traces to Phoenix
    if TRACELOOP_AVAILABLE:
        try:
            traceloop_url = get_traceloop_url()
            os.environ["TRACELOOP_BASE_URL"] = traceloop_url
            os.environ["TRACELOOP_HEADERS"] = ""

            # 4. Initialize Traceloop auto-instrumentation
            Traceloop.init(
                app_name="arbitrage_ai",
                disable_batch=True,  # Sends traces immediately for real-time debugging
            )
            logger.info("✓ Traceloop auto-instrumentation initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Traceloop: {e}")
    else:
        logger.debug("Traceloop not available (optional dependency)")

    logger.info("✓ Observability stack initialization complete")
