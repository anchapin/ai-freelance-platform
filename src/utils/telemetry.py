import os
from traceloop.sdk import Traceloop
import phoenix as px
from ..config import get_traceloop_url


def init_observability():
    """
    Initializes local tracing via Arize Phoenix and Traceloop.
    Captures LLM calls, token usage, and latency automatically.

    Note: In production (ENVIRONMENT != "development"), Phoenix should be run
    as a standalone Docker container to avoid port conflicts with multiple workers.
    """
    # 1. Only launch Phoenix dashboard in development mode
    # In production, run Phoenix as a separate Docker container instead
    if os.environ.get("ENVIRONMENT") == "development":
        session = px.launch_app()
        print(f"🔭 Phoenix Observability Dashboard running at: {session.url}")

    # 2. Tell OpenTelemetry to send traces to Phoenix
    traceloop_url = get_traceloop_url()
    os.environ["TRACELOOP_BASE_URL"] = traceloop_url
    os.environ["TRACELOOP_HEADERS"] = ""

    # 3. Initialize auto-instrumentation
    Traceloop.init(
        app_name="arbitrage_ai",
        disable_batch=True,  # Sends traces immediately for real-time debugging
    )
