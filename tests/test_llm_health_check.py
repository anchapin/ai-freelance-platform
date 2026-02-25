"""
LLM Health Check & Circuit Breaker Tests

Tests for circuit breaker and health check functionality.
Coverage includes:
- Circuit state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Health metrics tracking
- Exponential backoff calculations
- Request rate limiting based on health
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.llm_health_check import (
    LLMHealthChecker,
    CircuitState,
    ExponentialBackoff,
    get_health_checker
)


# =============================================================================
# CIRCUIT BREAKER TESTS
# =============================================================================

class TestCircuitBreakerStateMachine:
    """Test circuit breaker state transitions."""
    
    def test_initial_state_is_closed(self):
        """Test that new endpoints start in CLOSED state."""
        checker = LLMHealthChecker()
        metrics = checker.register_endpoint("http://test-llm:11434/v1")
        
        assert metrics.state == CircuitState.CLOSED
        assert metrics.consecutive_failures == 0
    
    def test_closed_to_open_transition(self):
        """Test transition from CLOSED to OPEN after failures."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(
            endpoint,
            failure_threshold=3
        )
        
        # Record 3 failures
        for _ in range(3):
            checker.record_failure(endpoint, "Connection timeout")
        
        # Should transition to OPEN
        assert metrics.state == CircuitState.OPEN
        assert metrics.consecutive_failures == 3
    
    def test_open_to_half_open_transition(self):
        """Test transition from OPEN to HALF_OPEN after timeout."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(
            endpoint,
            failure_threshold=2,
            recovery_timeout_seconds=1
        )
        
        # Record 2 failures -> OPEN
        for _ in range(2):
            checker.record_failure(endpoint, "Failed")
        assert metrics.state == CircuitState.OPEN
        
        # Immediately: not allowed
        assert checker.should_allow_request(endpoint) is False
        
        # Simulate waiting
        metrics.opened_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        
        # After timeout: should allow (transition to HALF_OPEN)
        assert checker.should_allow_request(endpoint) is True
        assert metrics.state == CircuitState.HALF_OPEN
    
    def test_half_open_to_closed_on_success(self):
        """Test recovery from HALF_OPEN to CLOSED on success."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint, failure_threshold=1)
        
        # Fail to go to OPEN
        checker.record_failure(endpoint, "Failed")
        assert metrics.state == CircuitState.OPEN
        
        # Manually transition to HALF_OPEN (bypassing timeout check for test)
        metrics.state = CircuitState.HALF_OPEN
        metrics.consecutive_failures = 0
        
        # Record success -> should go back to CLOSED
        checker.record_success(endpoint)
        assert metrics.state == CircuitState.CLOSED
        assert metrics.consecutive_failures == 0
    
    def test_should_allow_request_open_state(self):
        """Test that OPEN state blocks requests."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint, failure_threshold=1)
        
        # Go to OPEN
        checker.record_failure(endpoint, "Failed")
        assert metrics.state == CircuitState.OPEN
        
        # Immediately block
        assert checker.should_allow_request(endpoint) is False


# =============================================================================
# HEALTH METRICS TESTS
# =============================================================================

class TestHealthMetrics:
    """Test health metrics tracking."""
    
    def test_record_success_increments_requests(self):
        """Test that success increments total_requests and resets failures."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint)
        
        # Record a failure first
        checker.record_failure(endpoint, "error")
        assert metrics.consecutive_failures == 1
        assert metrics.total_requests == 1
        
        # Record success
        checker.record_success(endpoint, response_time_ms=150)
        assert metrics.consecutive_failures == 0
        assert metrics.total_requests == 2
    
    def test_record_failure_increments_counts(self):
        """Test that failures increment counters."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint)
        
        checker.record_failure(endpoint, "Connection error")
        assert metrics.consecutive_failures == 1
        assert metrics.total_failures == 1
        assert metrics.total_requests == 1
        
        checker.record_failure(endpoint, "Another error")
        assert metrics.consecutive_failures == 2
        assert metrics.total_failures == 2
        assert metrics.total_requests == 2
    
    def test_response_time_tracking(self):
        """Test that response times are tracked."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint)
        
        # Record some successful requests with different response times
        for response_time in [100, 150, 120, 200, 110]:
            checker.record_success(endpoint, response_time_ms=response_time)
        
        assert len(metrics.response_times) == 5
        assert metrics.response_times == [100, 150, 120, 200, 110]
    
    def test_response_time_history_limit(self):
        """Test that response time history is capped."""
        checker = LLMHealthChecker()
        endpoint = "http://test-llm:11434/v1"
        metrics = checker.register_endpoint(endpoint)
        metrics.max_response_time_history = 5
        
        # Record 10 responses
        for i in range(10):
            checker.record_success(endpoint, response_time_ms=100 + i)
        
        # Should only have last 5
        assert len(metrics.response_times) == 5
        assert metrics.response_times == [105, 106, 107, 108, 109]


# =============================================================================
# EXPONENTIAL BACKOFF TESTS
# =============================================================================

class TestExponentialBackoff:
    """Test exponential backoff calculation."""
    
    def test_backoff_progression(self):
        """Test that backoff increases exponentially."""
        backoff = ExponentialBackoff(
            initial_delay_ms=100,
            base=2.0,
            jitter_factor=0  # Disable jitter for deterministic test
        )
        
        # Attempt 0: 100ms
        assert backoff.get_delay_ms(0) == 100
        
        # Attempt 1: 200ms
        assert backoff.get_delay_ms(1) == 200
        
        # Attempt 2: 400ms
        assert backoff.get_delay_ms(2) == 400
        
        # Attempt 3: 800ms
        assert backoff.get_delay_ms(3) == 800
    
    def test_backoff_max_delay_cap(self):
        """Test that backoff is capped at max_delay."""
        backoff = ExponentialBackoff(
            initial_delay_ms=100,
            max_delay_ms=500,
            base=2.0,
            jitter_factor=0
        )
        
        # Should cap at max_delay
        assert backoff.get_delay_ms(10) == 500
    
    def test_backoff_with_jitter(self):
        """Test that jitter adds randomness."""
        backoff = ExponentialBackoff(
            initial_delay_ms=1000,
            jitter_factor=0.1
        )
        
        # Run multiple times to verify jitter adds variance
        delays = [backoff.get_delay_ms(0) for _ in range(10)]
        
        # Should have variety (but all around 1000)
        assert min(delays) < 1000
        assert max(delays) > 900
        # Jitter should be within bounds (±10%)
        for delay in delays:
            assert 900 <= delay <= 1100
    
    @pytest.mark.asyncio
    async def test_async_wait(self):
        """Test async wait functionality."""
        backoff = ExponentialBackoff(
            initial_delay_ms=10,  # Shorter delay for fast test
            jitter_factor=0  # Deterministic for test
        )
        
        import time
        start = time.time()
        await backoff.wait(0)  # Should wait 10ms
        elapsed = (time.time() - start) * 1000
        
        # Allow some variance due to system scheduling
        assert elapsed >= 5  # At least minimal wait


# =============================================================================
# HEALTH CHECKER LIFECYCLE TESTS
# =============================================================================

class TestHealthCheckerLifecycle:
    """Test health checker registration and lifecycle."""
    
    def test_register_endpoint(self):
        """Test endpoint registration."""
        checker = LLMHealthChecker()
        
        metrics1 = checker.register_endpoint("http://endpoint1:11434/v1")
        metrics2 = checker.register_endpoint("http://endpoint2:11434/v1")
        
        assert metrics1.endpoint == "http://endpoint1:11434/v1"
        assert metrics2.endpoint == "http://endpoint2:11434/v1"
        assert metrics1 != metrics2
    
    def test_get_health_status(self):
        """Test getting health status."""
        checker = LLMHealthChecker()
        endpoint = "http://test:11434/v1"
        
        # Register
        checker.register_endpoint(endpoint)
        
        # Retrieve
        metrics = checker.get_health_status(endpoint)
        assert metrics.endpoint == endpoint
    
    def test_get_health_status_auto_registers(self):
        """Test that get_health_status auto-registers unknown endpoints."""
        checker = LLMHealthChecker()
        endpoint = "http://auto:11434/v1"
        
        # Get without explicit register
        metrics = checker.get_health_status(endpoint)
        assert metrics.endpoint == endpoint
    
    def test_get_metrics_summary(self):
        """Test metrics summary generation."""
        checker = LLMHealthChecker()
        endpoint = "http://test:11434/v1"
        
        # Set up some activity
        for _ in range(10):
            checker.record_success(endpoint, response_time_ms=100)
        checker.record_failure(endpoint, "error")
        
        summary = checker.get_metrics_summary(endpoint)
        
        assert summary["endpoint"] == endpoint
        assert summary["state"] == "closed"
        assert summary["total_requests"] == 11
        assert summary["total_failures"] == 1
        assert pytest.approx(summary["failure_rate"], abs=0.05) == 1/11


# =============================================================================
# CONCURRENCY TESTS
# =============================================================================

class TestConcurrency:
    """Test thread safety of health checker."""
    
    def test_concurrent_record_success(self):
        """Test that concurrent success records are thread-safe."""
        import threading
        
        checker = LLMHealthChecker()
        endpoint = "http://test:11434/v1"
        checker.register_endpoint(endpoint)
        
        def record_successes(n):
            for _ in range(n):
                checker.record_success(endpoint)
        
        # Run 10 threads recording 100 successes each
        threads = [threading.Thread(target=record_successes, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        metrics = checker.get_health_status(endpoint)
        assert metrics.total_requests == 1000
    
    def test_concurrent_state_transitions(self):
        """Test concurrent state transitions are safe."""
        import threading
        
        checker = LLMHealthChecker()
        endpoint = "http://test:11434/v1"
        checker.register_endpoint(endpoint, failure_threshold=50)
        
        def record_failures(n):
            for _ in range(n):
                checker.record_failure(endpoint, "error")
        
        # Run threads concurrently
        threads = [threading.Thread(target=record_failures, args=(25,)) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        metrics = checker.get_health_status(endpoint)
        # All 75 failures should be recorded
        assert metrics.total_failures == 75


# =============================================================================
# GLOBAL INSTANCE TESTS
# =============================================================================

class TestGlobalHealthChecker:
    """Test global health checker singleton."""
    
    def test_get_health_checker_singleton(self):
        """Test that get_health_checker returns same instance."""
        checker1 = get_health_checker()
        checker2 = get_health_checker()
        
        assert checker1 is checker2
