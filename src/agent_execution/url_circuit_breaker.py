"""
URL Circuit Breaker for Market Scanner

Prevents repeated requests to failing marketplace URLs.

Issue #4: Fix async Playwright resource leaks in market scanner
"""

import time
from typing import Dict, Set, Optional
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class URLCircuitBreakerConfig:
    """Configuration for URL circuit breaker."""
    failure_threshold: int = 5  # Failures before breaking
    success_reset: int = 2  # Successes to reset after failure
    cooldown_seconds: int = 300  # Cool down time before retry


class URLCircuitBreaker:
    """
    Circuit breaker pattern for marketplace URLs.
    
    Prevents hammering failing URLs by tracking failures and
    pausing requests after threshold is exceeded.
    """
    
    def __init__(self, config: URLCircuitBreakerConfig = None):
        self.config = config or URLCircuitBreakerConfig()
        
        # Track failures per URL
        self._failures: Dict[str, list] = {}  # url -> [timestamp, ...]
        self._broken_urls: Dict[str, float] = {}  # url -> unbreak_time
        self._successes: Dict[str, int] = {}  # url -> success_count
        
        # Metrics
        self.urls_broken = 0
        self.urls_recovered = 0
    
    def should_request(self, url: str) -> bool:
        """
        Check if a request should be attempted for a URL.
        
        Args:
            url: URL to check
            
        Returns:
            True if request should be attempted, False if broken
        """
        now = time.time()
        
        # Check if URL is in cooldown
        if url in self._broken_urls:
            unbreak_time = self._broken_urls[url]
            if now < unbreak_time:
                return False
            else:
                # Cooldown expired, try again
                del self._broken_urls[url]
                self._failures[url] = []
                self._successes[url] = 0
                self.urls_recovered += 1
                logger.info(f"Circuit breaker: URL {url} recovered from cooldown")
        
        return True
    
    def record_failure(self, url: str):
        """
        Record a failed request for a URL.
        
        Args:
            url: URL that failed
        """
        now = time.time()
        
        # Initialize failure list if needed
        if url not in self._failures:
            self._failures[url] = []
        
        # Clean old failures (outside observation window)
        self._failures[url] = [
            t for t in self._failures[url]
            if now - t < 600  # 10 minute observation window
        ]
        
        # Record this failure
        self._failures[url].append(now)
        
        # Check if threshold exceeded
        if len(self._failures[url]) >= self.config.failure_threshold:
            self._broken_urls[url] = now + self.config.cooldown_seconds
            self.urls_broken += 1
            logger.warning(
                f"Circuit breaker: {url} broken after "
                f"{len(self._failures[url])} failures, "
                f"cooldown for {self.config.cooldown_seconds}s"
            )
        
        # Reset success counter on failure
        self._successes[url] = 0
    
    def record_success(self, url: str):
        """
        Record a successful request for a URL.
        
        Args:
            url: URL that succeeded
        """
        if url not in self._successes:
            self._successes[url] = 0
        
        self._successes[url] += 1
        
        # Reset failure count on consecutive successes
        if self._successes[url] >= self.config.success_reset:
            if url in self._failures:
                self._failures[url] = []
            self._successes[url] = 0
            logger.debug(f"Circuit breaker: {url} failure count reset")
    
    def get_metrics(self) -> Dict[str, int]:
        """Get circuit breaker metrics."""
        return {
            "urls_broken": self.urls_broken,
            "urls_recovered": self.urls_recovered,
            "currently_broken": len(self._broken_urls),
            "urls_tracked": len(self._failures),
        }


# Global instance
_url_circuit_breaker: Optional[URLCircuitBreaker] = None


def get_url_circuit_breaker() -> URLCircuitBreaker:
    """Get or create the global URLCircuitBreaker instance."""
    global _url_circuit_breaker
    if _url_circuit_breaker is None:
        _url_circuit_breaker = URLCircuitBreaker()
    return _url_circuit_breaker
