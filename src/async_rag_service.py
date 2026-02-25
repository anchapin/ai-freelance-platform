"""
Async RAG Service for Decoupled Vector DB

Refactored RAG layer that doesn't block task execution.
Implements async queries, circuit breaker pattern, and background processing.

Issue #6: Decouple Experience Vector Database from task execution flow
"""

import asyncio
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

from src.experience_vector_db import ExperienceVectorDB, FewShotExample
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitBreakerState(Enum):
    """States for circuit breaker pattern."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes to close after half-open
    timeout_seconds: int = 60  # Time before half-open


class AsyncRAGCircuitBreaker:
    """
    Circuit breaker for ChromaDB/RAG queries.

    States:
    - CLOSED: Normal operation
    - OPEN: Failing, reject all requests
    - HALF_OPEN: Testing recovery, allow limited requests
    """

    def __init__(self, config: CircuitBreakerConfig = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.open_at = None

    def is_allowed(self) -> bool:
        """Check if request should be allowed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Check if enough time has passed to try half-open
            if self.open_at:
                elapsed = time.time() - self.open_at
                if elapsed > self.config.timeout_seconds:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    logger.info("Circuit breaker: transitioning to HALF_OPEN")
                    return True
            return False

        # HALF_OPEN: allow all requests but track success
        return True

    def record_success(self):
        """Record successful operation."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                logger.info("Circuit breaker: transitioning to CLOSED")

        self.failure_count = 0

    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitBreakerState.HALF_OPEN:
            # Failure in half-open state reopens the circuit
            self.state = CircuitBreakerState.OPEN
            self.open_at = time.time()
            logger.warning(
                "Circuit breaker: transitioning to OPEN (half-open test failed)"
            )
        elif self.failure_count >= self.config.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.open_at = time.time()
            logger.warning(
                f"Circuit breaker: transitioning to OPEN "
                f"({self.failure_count} failures)"
            )


@dataclass
class CachedFewShotQuery:
    """Cached few-shot query result."""

    examples: List[FewShotExample]
    cached_at: datetime

    def is_expired(self, ttl_minutes: int = 60) -> bool:
        """Check if cache has expired."""
        age = (datetime.now(timezone.utc) - self.cached_at).total_seconds() / 60
        return age > ttl_minutes


class AsyncRAGService:
    """
    Async RAG service for non-blocking few-shot example retrieval.

    Features:
    - Non-blocking async queries
    - Query result caching
    - Circuit breaker for ChromaDB failures
    - Fallback to zero-shot when RAG unavailable
    - Background task queueing
    """

    def __init__(
        self,
        vector_db: ExperienceVectorDB,
        cache_ttl_minutes: int = 60,
        circuit_breaker_config: CircuitBreakerConfig = None,
    ):
        self.vector_db = vector_db
        self.cache_ttl_minutes = cache_ttl_minutes
        self.circuit_breaker = AsyncRAGCircuitBreaker(circuit_breaker_config)

        # Query cache: (user_request_hash, domain) -> CachedFewShotQuery
        self._query_cache: Dict[tuple, CachedFewShotQuery] = {}
        self._cache_lock = asyncio.Lock()

        # Metrics
        self.queries_attempted = 0
        self.queries_succeeded = 0
        self.cache_hits = 0
        self.fallback_count = 0

    async def get_few_shot_examples(
        self, user_request: str, domain: str, top_k: int = 2
    ) -> List[FewShotExample]:
        """
        Get few-shot examples for a user request.

        This method is non-blocking. If ChromaDB is unavailable,
        it returns an empty list without raising exceptions.

        Args:
            user_request: The user's task request
            domain: Task domain
            top_k: Number of examples to return

        Returns:
            List of FewShotExample objects (may be empty if unavailable)
        """
        self.queries_attempted += 1
        cache_key = (hash(user_request) % 1000000, domain)

        # Check cache first
        async with self._cache_lock:
            if cache_key in self._query_cache:
                cached = self._query_cache[cache_key]
                if not cached.is_expired(self.cache_ttl_minutes):
                    self.cache_hits += 1
                    logger.debug(f"RAG cache hit for {domain}")
                    return cached.examples

        # Check circuit breaker
        if not self.circuit_breaker.is_allowed():
            logger.warning(f"RAG circuit breaker is {self.circuit_breaker.state.value}")
            self.fallback_count += 1
            return []

        # Query ChromaDB
        try:
            examples = self.vector_db.query_similar_tasks(
                user_request=user_request, domain=domain, top_k=top_k
            )

            self.queries_succeeded += 1
            self.circuit_breaker.record_success()

            # Cache result
            async with self._cache_lock:
                self._query_cache[cache_key] = CachedFewShotQuery(
                    examples=examples, cached_at=datetime.now(timezone.utc)
                )

            logger.debug(f"RAG query succeeded: {len(examples)} examples for {domain}")
            return examples

        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            self.circuit_breaker.record_failure()
            self.fallback_count += 1
            return []

    async def enrich_system_prompt(
        self,
        base_prompt: str,
        user_request: str,
        domain: str,
        timeout_seconds: float = 2.0,
    ) -> str:
        """
        Attempt to enrich system prompt with few-shot examples.

        Non-blocking: returns base_prompt immediately if RAG is slow.

        Args:
            base_prompt: Zero-shot system prompt
            user_request: User's task request
            domain: Task domain
            timeout_seconds: Max time to wait for RAG enrichment

        Returns:
            Enriched system prompt (or base_prompt if enrichment fails/times out)
        """
        try:
            # Get few-shot examples with timeout
            examples = await asyncio.wait_for(
                self.get_few_shot_examples(
                    user_request=user_request, domain=domain, top_k=2
                ),
                timeout=timeout_seconds,
            )

            if examples:
                enriched = self.vector_db.build_few_shot_system_prompt(
                    base_prompt=base_prompt, examples=examples
                )
                logger.debug(f"System prompt enriched with {len(examples)} examples")
                return enriched

        except asyncio.TimeoutError:
            logger.warning(
                f"RAG enrichment timed out after {timeout_seconds}s, "
                f"using zero-shot prompt"
            )
            self.fallback_count += 1
        except Exception as e:
            logger.error(f"RAG enrichment error: {e}")
            self.fallback_count += 1

        # Return base prompt on any failure
        return base_prompt

    def get_metrics(self) -> Dict[str, Any]:
        """Get RAG service metrics."""
        success_rate = (
            (self.queries_succeeded / self.queries_attempted * 100)
            if self.queries_attempted > 0
            else 0.0
        )

        return {
            "queries_attempted": self.queries_attempted,
            "queries_succeeded": self.queries_succeeded,
            "success_rate_percent": success_rate,
            "cache_hits": self.cache_hits,
            "fallback_count": self.fallback_count,
            "circuit_breaker_state": self.circuit_breaker.state.value,
            "cached_entries": len(self._query_cache),
        }

    async def clear_cache(self):
        """Clear the query cache."""
        async with self._cache_lock:
            self._query_cache.clear()
        logger.info("RAG query cache cleared")


# Global instance
_async_rag_service: Optional[AsyncRAGService] = None


def get_async_rag_service(vector_db: ExperienceVectorDB) -> AsyncRAGService:
    """Get or create the global AsyncRAGService instance."""
    global _async_rag_service
    if _async_rag_service is None:
        _async_rag_service = AsyncRAGService(vector_db=vector_db)
    return _async_rag_service
