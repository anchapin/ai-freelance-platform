"""
Tests for Vector DB Decoupling

Tests for Issue #6: Decouple Experience Vector Database from task execution flow

Coverage:
- Async RAG service
- Circuit breaker pattern
- Query caching
- Background job queue
- Non-blocking operation
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from src.async_rag_service import (
    AsyncRAGService,
    AsyncRAGCircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
)
from src.background_job_queue import (
    BackgroundJobQueue,
    JobStatus,
)
from src.experience_vector_db import FewShotExample


class TestCircuitBreaker:
    """Tests for circuit breaker pattern."""
    
    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in CLOSED state."""
        breaker = AsyncRAGCircuitBreaker()
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_circuit_breaker_allowed_in_closed_state(self):
        """Test requests allowed in CLOSED state."""
        breaker = AsyncRAGCircuitBreaker()
        assert breaker.is_allowed() is True
    
    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = AsyncRAGCircuitBreaker(config)
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.is_allowed() is False
    
    def test_circuit_breaker_transitions_to_half_open(self):
        """Test circuit breaker transitions to HALF_OPEN after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0
        )
        breaker = AsyncRAGCircuitBreaker(config)
        
        # Open the circuit
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait and check half-open
        import time
        time.sleep(0.1)
        assert breaker.is_allowed() is True
        assert breaker.state == CircuitBreakerState.HALF_OPEN
    
    def test_circuit_breaker_closes_after_success_threshold(self):
        """Test circuit breaker closes after success threshold in HALF_OPEN."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout_seconds=0
        )
        breaker = AsyncRAGCircuitBreaker(config)
        
        # Open circuit
        breaker.record_failure()
        
        # Transition to half-open
        import time
        time.sleep(0.1)
        assert breaker.is_allowed()
        
        # Record successes to close
        breaker.record_success()
        breaker.record_success()
        
        assert breaker.state == CircuitBreakerState.CLOSED


class TestAsyncRAGService:
    """Tests for AsyncRAGService."""
    
    @pytest.fixture
    def mock_vector_db(self):
        """Create a mock ExperienceVectorDB."""
        db = MagicMock()
        db.query_similar_tasks = MagicMock(return_value=[
            FewShotExample(
                user_request="Create a chart",
                generated_code="import matplotlib",
                similarity_score=0.9
            )
        ])
        db.build_few_shot_system_prompt = MagicMock(
            return_value="System prompt with examples"
        )
        return db
    
    @pytest.mark.asyncio
    async def test_get_few_shot_examples_success(self, mock_vector_db):
        """Test successful few-shot example retrieval."""
        service = AsyncRAGService(vector_db=mock_vector_db)
        
        examples = await service.get_few_shot_examples(
            user_request="Create a chart",
            domain="data_analysis"
        )
        
        assert len(examples) == 1
        assert service.queries_succeeded == 1
    
    @pytest.mark.asyncio
    async def test_get_few_shot_examples_circuit_breaker_open(self, mock_vector_db):
        """Test that open circuit breaker prevents queries."""
        service = AsyncRAGService(vector_db=mock_vector_db)
        
        # Open the circuit
        service.circuit_breaker.state = CircuitBreakerState.OPEN
        service.circuit_breaker.open_at = 0  # Ensure it stays open
        
        examples = await service.get_few_shot_examples(
            user_request="Create a chart",
            domain="data_analysis"
        )
        
        assert examples == []
        assert service.fallback_count == 1
    
    @pytest.mark.asyncio
    async def test_query_caching(self, mock_vector_db):
        """Test that queries are cached."""
        service = AsyncRAGService(vector_db=mock_vector_db)
        
        # First query
        examples1 = await service.get_few_shot_examples(
            user_request="Create a chart",
            domain="data_analysis"
        )
        
        # Second query (same parameters)
        examples2 = await service.get_few_shot_examples(
            user_request="Create a chart",
            domain="data_analysis"
        )
        
        assert examples1 == examples2
        assert service.cache_hits == 1
        # Vector DB should only be called once due to caching
        assert mock_vector_db.query_similar_tasks.call_count == 1
    
    @pytest.mark.asyncio
    async def test_enrich_system_prompt_success(self, mock_vector_db):
        """Test enriching system prompt with few-shot examples."""
        service = AsyncRAGService(vector_db=mock_vector_db)
        
        enriched = await service.enrich_system_prompt(
            base_prompt="Zero-shot prompt",
            user_request="Create a chart",
            domain="data_analysis"
        )
        
        assert enriched == "System prompt with examples"
        mock_vector_db.build_few_shot_system_prompt.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_enrich_system_prompt_timeout_fallback(self, mock_vector_db):
        """Test fallback to zero-shot on RAG timeout."""
        # Make query_similar_tasks slow
        async def slow_query(*args, **kwargs):
            await asyncio.sleep(5)
            return []
        
        mock_vector_db.query_similar_tasks = AsyncMock(side_effect=slow_query)
        service = AsyncRAGService(vector_db=mock_vector_db)
        
        enriched = await service.enrich_system_prompt(
            base_prompt="Zero-shot prompt",
            user_request="Create a chart",
            domain="data_analysis",
            timeout_seconds=0.1
        )
        
        # Should return base prompt on timeout
        assert enriched == "Zero-shot prompt"
        assert service.fallback_count == 1
    
    def test_get_metrics(self, mock_vector_db):
        """Test metrics collection."""
        service = AsyncRAGService(vector_db=mock_vector_db)
        service.queries_attempted = 10
        service.queries_succeeded = 8
        service.cache_hits = 3
        service.fallback_count = 2
        
        metrics = service.get_metrics()
        
        assert metrics["queries_attempted"] == 10
        assert metrics["queries_succeeded"] == 8
        assert metrics["success_rate_percent"] == 80.0
        assert metrics["cache_hits"] == 3
        assert metrics["fallback_count"] == 2


class TestBackgroundJobQueue:
    """Tests for BackgroundJobQueue."""
    
    @pytest.mark.asyncio
    async def test_queue_job_success(self):
        """Test queuing and executing a successful job."""
        queue = BackgroundJobQueue(max_workers=1)
        await queue.start()
        
        executed = []
        
        async def test_task(value):
            executed.append(value)
        
        job_id = _ = await queue.queue_job(
            job_type="test",
            task_func=test_task,
            task_args=(42,)
        )
        
        # Wait for job to execute
        await asyncio.sleep(0.1)
        
        assert job_id in queue.completed_jobs
        assert queue.completed_jobs[job_id].status == JobStatus.SUCCEEDED
        assert executed == [42]
        
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_queue_job_failure_with_retry(self):
        """Test job failure and retry."""
        queue = BackgroundJobQueue(max_workers=1)
        await queue.start()
        
        call_count = [0]
        
        async def failing_task():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("First attempt fails")
        
        job_id = _ = await queue.queue_job(
            job_type="test",
            task_func=failing_task,
            max_retries=2
        )
        
        # Wait for retries
        await asyncio.sleep(0.5)
        
        # Should eventually succeed after retry
        assert queue.jobs_retried >= 1
        
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_multiple_workers(self):
        """Test multiple workers processing jobs concurrently."""
        queue = BackgroundJobQueue(max_workers=3)
        await queue.start()
        
        results = []
        
        async def slow_task(value):
            await asyncio.sleep(0.1)
            results.append(value)
        
        # Queue multiple jobs
        job_ids = []
        for i in range(5):
            job_id = _ = await queue.queue_job(
                job_type="test",
                task_func=slow_task,
                task_args=(i,)
            )
            job_ids.append(job_id)
        
        # Wait for completion
        await asyncio.sleep(0.3)
        
        assert len(results) == 5
        assert sorted(results) == [0, 1, 2, 3, 4]
        assert queue.jobs_succeeded == 5
        
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_queue_full(self):
        """Test behavior when queue is full."""
        queue = BackgroundJobQueue(max_queue_size=2)
        await queue.start()
        
        async def dummy_task():
            await asyncio.sleep(1)
        
        # Queue max jobs
        _ = await queue.queue_job(job_type="test", task_func=dummy_task)
        _ = await queue.queue_job(job_type="test", task_func=dummy_task)
        
        # This should raise QueueFull
        with pytest.raises(asyncio.QueueFull):
            _ = await queue.queue_job(job_type="test", task_func=dummy_task)
        
        await queue.stop()
    
    def test_get_metrics(self):
        """Test job queue metrics."""
        queue = BackgroundJobQueue()
        queue.jobs_queued = 10
        queue.jobs_succeeded = 8
        queue.jobs_failed = 2
        queue.jobs_retried = 1
        
        metrics = queue.get_metrics()
        
        assert metrics["jobs_queued"] == 10
        assert metrics["jobs_succeeded"] == 8
        assert metrics["jobs_failed"] == 2
        assert metrics["jobs_retried"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
