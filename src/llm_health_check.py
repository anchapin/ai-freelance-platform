"""
LLM Service Health Check & Circuit Breaker

Implements active health checks and circuit breaker pattern for LLM routing.
This prevents wasting 90+ seconds on unavailable Ollama instances.

Features:
- Periodic health checks every 30 seconds
- Circuit breaker with configurable failure thresholds
- Exponential backoff for retries
- Health state caching
- Metrics for observability

Pillar 2.6 - Ollama Circuit Breaker (Issue #7)
"""

import asyncio
import threading
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    """States for the circuit breaker pattern."""

    CLOSED = "closed"  # Service is healthy, requests pass through
    OPEN = "open"  # Service is unhealthy, requests fast-fail
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class HealthMetrics:
    """Metrics for an LLM service endpoint."""

    endpoint: str
    state: CircuitState = CircuitState.CLOSED

    # Health check tracking
    last_health_check_at: Optional[datetime] = None
    last_healthy_at: Optional[datetime] = None
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0

    # Circuit breaker state
    opened_at: Optional[datetime] = None
    failure_threshold: int = 3  # Open after 3 consecutive failures
    recovery_timeout_seconds: int = 60  # Try recovery after 60 seconds

    # Metrics
    response_times: list = field(default_factory=list)  # For latency tracking
    max_response_time_history = 100  # Keep last 100 response times


@dataclass
class ExponentialBackoff:
    """Exponential backoff with jitter for retries."""

    initial_delay_ms: int = 100
    max_delay_ms: int = 10000
    base: float = 2.0
    jitter_factor: float = 0.1

    def _calculate_jitter(self, delay_ms: int) -> int:
        """Add random jitter to prevent thundering herd."""
        import random

        jitter = random.uniform(-self.jitter_factor, self.jitter_factor)
        jittered = delay_ms * (1 + jitter)
        return max(1, int(jittered))

    def get_delay_ms(self, attempt: int) -> int:
        """Calculate delay for given attempt number (0-indexed)."""
        if attempt < 0:
            return 0

        # Exponential: initial_delay * (base ^ attempt)
        delay = self.initial_delay_ms * (self.base**attempt)
        # Cap at max
        delay = min(delay, self.max_delay_ms)
        # Add jitter
        return self._calculate_jitter(int(delay))

    async def wait(self, attempt: int):
        """Async wait for the calculated delay."""
        delay_ms = self.get_delay_ms(attempt)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)


class LLMHealthChecker:
    """
    Active health checker for LLM service endpoints.

    Performs periodic health checks to determine if endpoints are available,
    preventing expensive timeout waits.
    """

    def __init__(self, check_interval_seconds: int = 30):
        self.check_interval_seconds = check_interval_seconds
        self.health_status: Dict[str, HealthMetrics] = {}
        self._check_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    def register_endpoint(
        self,
        endpoint: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: int = 60,
    ) -> HealthMetrics:
        """Register an endpoint to monitor."""
        with self._lock:
            if endpoint not in self.health_status:
                self.health_status[endpoint] = HealthMetrics(
                    endpoint=endpoint,
                    failure_threshold=failure_threshold,
                    recovery_timeout_seconds=recovery_timeout_seconds,
                )
                logger.info(f"[HEALTH] Registered endpoint: {endpoint}")
            return self.health_status[endpoint]

    def get_health_status(self, endpoint: str) -> HealthMetrics:
        """Get current health status for endpoint."""
        with self._lock:
            if endpoint not in self.health_status:
                # Don't call register_endpoint (which also uses lock), just create directly
                self.health_status[endpoint] = HealthMetrics(endpoint=endpoint)
            return self.health_status[endpoint]

    def record_success(self, endpoint: str, response_time_ms: float = 0):
        """Record successful request."""
        metrics = self.get_health_status(endpoint)
        with self._lock:
            metrics.consecutive_failures = 0
            metrics.total_requests += 1
            metrics.last_healthy_at = datetime.now(timezone.utc)

            # Track response time
            if response_time_ms > 0:
                metrics.response_times.append(response_time_ms)
                if len(metrics.response_times) > metrics.max_response_time_history:
                    metrics.response_times.pop(0)

            # Transition from HALF_OPEN to CLOSED
            if metrics.state == CircuitState.HALF_OPEN:
                metrics.state = CircuitState.CLOSED
                metrics.opened_at = None
                logger.info(f"[CIRCUIT] {endpoint} recovered - CLOSED")

    def record_failure(self, endpoint: str, error: str = ""):
        """Record failed request."""
        metrics = self.get_health_status(endpoint)
        with self._lock:
            metrics.consecutive_failures += 1
            metrics.total_requests += 1
            metrics.total_failures += 1

            # Transition to OPEN after threshold
            if (
                metrics.consecutive_failures >= metrics.failure_threshold
                and metrics.state == CircuitState.CLOSED
            ):
                metrics.state = CircuitState.OPEN
                metrics.opened_at = datetime.now(timezone.utc)
                logger.warning(
                    f"[CIRCUIT] {endpoint} OPEN after {metrics.consecutive_failures} failures. "
                    f"Last error: {error[:100]}"
                )

    def should_allow_request(self, endpoint: str) -> bool:
        """Check if circuit breaker should allow request."""
        metrics = self.get_health_status(endpoint)

        if metrics.state == CircuitState.CLOSED:
            # Always allow
            return True
        elif metrics.state == CircuitState.OPEN:
            # Check if we should try recovery (half-open)
            if metrics.opened_at:
                elapsed = datetime.now(timezone.utc) - metrics.opened_at
                if elapsed.total_seconds() >= metrics.recovery_timeout_seconds:
                    with self._lock:
                        metrics.state = CircuitState.HALF_OPEN
                        metrics.consecutive_failures = 0
                    logger.info(f"[CIRCUIT] {endpoint} HALF_OPEN - testing recovery")
                    return True
            return False
        elif metrics.state == CircuitState.HALF_OPEN:
            # Allow one test request
            return True

        return True

    def get_metrics_summary(self, endpoint: str) -> Dict[str, Any]:
        """Get human-readable metrics summary."""
        metrics = self.get_health_status(endpoint)

        avg_response_time = 0
        if metrics.response_times:
            avg_response_time = sum(metrics.response_times) / len(
                metrics.response_times
            )

        return {
            "endpoint": endpoint,
            "state": metrics.state.value,
            "consecutive_failures": metrics.consecutive_failures,
            "total_requests": metrics.total_requests,
            "total_failures": metrics.total_failures,
            "failure_rate": (
                metrics.total_failures / metrics.total_requests
                if metrics.total_requests > 0
                else 0
            ),
            "avg_response_time_ms": round(avg_response_time, 2),
            "last_health_check": (
                metrics.last_health_check_at.isoformat()
                if metrics.last_health_check_at
                else None
            ),
            "last_healthy_at": (
                metrics.last_healthy_at.isoformat() if metrics.last_healthy_at else None
            ),
        }

    async def health_check(
        self, endpoint: str, timeout_seconds: int = 5
    ) -> bool:
        """
        Perform health check on Ollama endpoint.

        Checks the /api/health endpoint to verify service availability.

        Args:
            endpoint: The endpoint URL (e.g., http://localhost:11434/v1)
            timeout_seconds: Timeout for health check request

        Returns:
            True if healthy (status 200), False otherwise
        """
        metrics = self.get_health_status(endpoint)

        try:
            import httpx

            # Convert endpoint URL to health check URL
            # http://localhost:11434/v1 -> http://localhost:11434/api/health
            base_url = endpoint.rsplit("/v1", 1)[0]
            health_url = f"{base_url}/api/health"

            logger.debug(f"[HEALTH] Checking {health_url}...")

            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(health_url)

                with self._lock:
                    metrics.last_health_check_at = datetime.now(timezone.utc)

                if response.status_code == 200:
                    logger.debug(f"[HEALTH] {endpoint} is healthy")
                    return True
                else:
                    logger.warning(
                        f"[HEALTH] {endpoint} returned status {response.status_code}"
                    )
                    return False

        except asyncio.TimeoutError:
            logger.warning(f"[HEALTH] Health check timeout for {endpoint}")
            return False
        except Exception as e:
            logger.error(f"[HEALTH] Check failed for {endpoint}: {e}")
            return False


# Global health checker instance
_global_health_checker: Optional[LLMHealthChecker] = None


def get_health_checker() -> LLMHealthChecker:
    """Get or create global health checker."""
    global _global_health_checker
    if _global_health_checker is None:
        _global_health_checker = LLMHealthChecker(check_interval_seconds=30)
    return _global_health_checker


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    pass
