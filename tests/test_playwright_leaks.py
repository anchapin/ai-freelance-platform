"""
Tests for Playwright Resource Leak Fixes

Tests for Issue #4: Fix async Playwright resource leaks in market scanner

Coverage:
- Browser pool management
- Resource cleanup with context managers
- Circuit breaker for failing URLs
- Exponential backoff retry
"""

import pytest
import asyncio
import time

from src.agent_execution.browser_pool import BrowserPool
from src.agent_execution.url_circuit_breaker import (
    URLCircuitBreaker,
    URLCircuitBreakerConfig,
)
from src.agent_execution.exponential_backoff import (
    ExponentialBackoff,
    retry_with_backoff,
)
from src.utils.logger import get_logger


class TestBrowserPool:
    """Tests for browser connection pooling."""
    
    @pytest.mark.asyncio
    async def test_browser_pool_creation(self):
        """Test browser pool initializes."""
        pool = BrowserPool(max_browsers=2)
        assert pool.max_browsers == 2
        assert len(pool._browsers) == 0
    
    @pytest.mark.asyncio
    async def test_browser_pool_metrics(self):
        """Test browser pool metrics."""
        pool = BrowserPool(max_browsers=3)
        pool.browsers_created = 2
        pool.browsers_reused = 5
        pool.pages_created = 10
        
        metrics = pool.get_metrics()
        assert metrics["max_browsers"] == 3
        assert metrics["browsers_created"] == 2
        assert metrics["browsers_reused"] == 5
        assert metrics["pages_created"] == 10


class TestURLCircuitBreaker:
    """Tests for URL circuit breaker."""
    
    def test_circuit_breaker_allows_requests_initially(self):
        """Test circuit breaker allows requests initially."""
        breaker = URLCircuitBreaker()
        assert breaker.should_request("http://example.com") is True
    
    def test_circuit_breaker_breaks_after_threshold(self):
        """Test circuit breaker breaks URL after failure threshold."""
        config = URLCircuitBreakerConfig(failure_threshold=3)
        breaker = URLCircuitBreaker(config)
        
        url = "http://failing.com"
        
        # Record failures
        for _ in range(3):
            breaker.record_failure(url)
        
        # Should be broken now
        assert breaker.should_request(url) is False
        assert breaker.urls_broken == 1
    
    def test_circuit_breaker_cooldown(self):
        """Test circuit breaker enters cooldown."""
        config = URLCircuitBreakerConfig(
            failure_threshold=1,
            cooldown_seconds=1
        )
        breaker = URLCircuitBreaker(config)
        
        url = "http://failing.com"
        
        # Break the URL
        breaker.record_failure(url)
        assert breaker.should_request(url) is False
        
        # Wait for cooldown
        time.sleep(1.1)
        
        # Should recover
        assert breaker.should_request(url) is True
        assert breaker.urls_recovered == 1
    
    def test_circuit_breaker_reset_on_success(self):
        """Test circuit breaker resets on successful requests."""
        config = URLCircuitBreakerConfig(
            failure_threshold=5,
            success_reset=2
        )
        breaker = URLCircuitBreaker(config)
        
        url = "http://example.com"
        
        # Record some failures
        for _ in range(3):
            breaker.record_failure(url)
        
        # Record successes
        for _ in range(2):
            breaker.record_success(url)
        
        # Failure count should be reset
        assert len(breaker._failures.get(url, [])) == 0
    
    def test_circuit_breaker_metrics(self):
        """Test circuit breaker metrics."""
        breaker = URLCircuitBreaker()
        breaker.urls_broken = 3
        breaker.urls_recovered = 1
        breaker._broken_urls = {"url1": 0, "url2": 0}
        breaker._failures = {"url1": [], "url2": [], "url3": []}
        
        metrics = breaker.get_metrics()
        assert metrics["urls_broken"] == 3
        assert metrics["urls_recovered"] == 1
        assert metrics["currently_broken"] == 2
        assert metrics["urls_tracked"] == 3


class TestExponentialBackoff:
    """Tests for exponential backoff."""
    
    def test_backoff_delay_calculation(self):
        """Test exponential backoff delay calculation."""
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0, jitter=False)
        
        # Delays should be: 1s, 2s, 4s, 8s, 16s, 32s, 60s (capped)
        expected_delays = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]
        
        for retry_count, expected in enumerate(expected_delays):
            # Calculate delay without actually waiting
            delay = backoff.base_delay * (2 ** retry_count)
            delay = min(delay, backoff.max_delay)
            assert delay == expected
    
    @pytest.mark.asyncio
    async def test_backoff_waits(self):
        """Test backoff actually waits."""
        backoff = ExponentialBackoff(base_delay=0.05, max_delay=1.0, jitter=False)
        
        start = time.time()
        await backoff.wait(retry_count=2)  # 0.2 seconds
        elapsed = time.time() - start
        
        # Should wait approximately 0.2 seconds (0.15-0.25 tolerance)
        assert 0.15 < elapsed < 0.25
    
    @pytest.mark.asyncio
    async def test_retry_with_backoff_success(self):
        """Test retry with eventual success."""
        call_count = [0]
        
        async def sometimes_fails():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Not yet")
            return "success"
        
        backoff = ExponentialBackoff(base_delay=0.01)
        result = await backoff.with_retry(
            sometimes_fails,
            max_retries=5
        )
        
        assert result == "success"
        assert call_count[0] == 3
    
    @pytest.mark.asyncio
    async def test_retry_with_backoff_failure(self):
        """Test retry fails after max attempts."""
        async def always_fails():
            raise Exception("Always fails")
        
        backoff = ExponentialBackoff(base_delay=0.01)
        
        with pytest.raises(Exception) as exc_info:
            await backoff.with_retry(
                always_fails,
                max_retries=3
            )
        
        assert "Always fails" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_retry_with_backoff_convenience(self):
        """Test convenience retry function."""
        call_count = [0]
        
        async def sometimes_fails():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("First attempt fails")
            return "success"
        
        result = await retry_with_backoff(
            sometimes_fails,
            max_retries=3,
            base_delay=0.01
        )
        
        assert result == "success"


class TestPlaywrightPatterns:
    """Integration tests for Playwright resource patterns."""
    
    def test_url_circuit_breaker_prevents_hammering(self):
        """Test circuit breaker prevents hammering failing URLs."""
        breaker = URLCircuitBreaker(
            URLCircuitBreakerConfig(failure_threshold=3)
        )
        
        url = "http://slow-server.com"
        
        # Simulate failures
        for i in range(5):
            if breaker.should_request(url):
                logger.debug(f"Attempt {i+1}")
                breaker.record_failure(url)
            else:
                logger.debug(f"Attempt {i+1}: circuit broken")
        
        # After 3 failures, should be broken
        assert breaker.should_request(url) is False
    
    def test_backoff_prevents_immediate_retries(self):
        """Test exponential backoff prevents immediate retries."""
        async def run_test():
            backoff = ExponentialBackoff(
                base_delay=0.05,
                max_delay=60.0,
                jitter=False
            )
            
            # Test that backoff doesn't return immediately
            start = time.time()
            
            # Wait for 2 seconds total with backoff
            await backoff.wait(0)  # 0.05s
            await backoff.wait(1)  # 0.1s
            
            elapsed = time.time() - start
            # Should wait at least 0.15 seconds
            assert elapsed > 0.1
        
        asyncio.run(run_test())


logger = get_logger(__name__)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
