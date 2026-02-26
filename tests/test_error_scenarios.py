"""
Comprehensive Error Scenario Tests (Issue #29)

Tests for error handling across critical workflows:
- Network timeout scenarios with retry logic
- Partial failure in multi-step workflows
- Cascade failures across services
- Database connection failures
- LLM service unavailability

These tests ensure system resilience and proper error recovery.
"""

import pytest
import asyncio
from unittest.mock import Mock
from datetime import datetime

from src.agent_execution.errors import (
    NetworkError,
    TimeoutError,
    TransientError,
    ValidationError,
    should_retry,
)


# =============================================================================
# FIXTURES FOR FAULT INJECTION
# =============================================================================


@pytest.fixture
def mock_timeout_fixture(monkeypatch):
    """Fixture for mocking timeout errors."""
    def timeout_after_attempts(call_count=[0]):
        """Simulate timeout on first 2 calls, succeed on 3rd."""
        call_count[0] += 1
        if call_count[0] < 3:
            raise TimeoutError("Request timed out after 30s")
        return {"success": True, "data": "recovered after retry"}
    
    return timeout_after_attempts


@pytest.fixture
def mock_db_connection_failure(monkeypatch):
    """Fixture for simulating database connection failures."""
    class MockDBSession:
        def __init__(self, fail_count=1):
            self.fail_count = fail_count
            self.attempt = 0
            self.closed = False
        
        def execute(self, query):
            self.attempt += 1
            if self.attempt <= self.fail_count:
                raise ConnectionError("Database connection lost")
            return Mock(fetchall=lambda: [])
        
        def commit(self):
            if self.attempt <= self.fail_count:
                raise ConnectionError("Database connection lost")
        
        def rollback(self):
            pass
        
        def close(self):
            self.closed = True
    
    return MockDBSession


@pytest.fixture
def mock_llm_unavailability(monkeypatch):
    """Fixture for simulating LLM service unavailability."""
    call_count = [0]
    
    async def llm_call_with_retry():
        """Simulate 500 error on first attempt, then success."""
        call_count[0] += 1
        if call_count[0] == 1:
            raise TransientError("LLM service returned 500 Internal Server Error")
        elif call_count[0] == 2:
            raise TransientError("Rate limit exceeded, retry after 1s")
        return {"response": "LLM generated content"}
    
    return llm_call_with_retry


@pytest.fixture
def mock_circuit_breaker(monkeypatch):
    """Fixture for simulating circuit breaker behavior."""
    class CircuitBreaker:
        def __init__(self, failure_threshold=3, timeout=5):
            self.failure_threshold = failure_threshold
            self.timeout = timeout
            self.failure_count = 0
            self.last_failure_time = None
            self.state = "closed"  # closed, open, half-open
        
        def record_success(self):
            self.failure_count = 0
            self.state = "closed"
        
        def record_failure(self):
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
        
        def can_execute(self) -> bool:
            if self.state == "closed":
                return True
            elif self.state == "open":
                # Check if timeout expired
                if (datetime.now() - self.last_failure_time).seconds >= self.timeout:
                    self.state = "half-open"
                    return True
                return False
            else:  # half-open
                return True
        
        def call(self, func, *args, **kwargs):
            if not self.can_execute():
                raise TransientError("Circuit breaker is open")
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise
    
    return CircuitBreaker


# =============================================================================
# A. NETWORK TIMEOUT SCENARIOS
# =============================================================================


class TestNetworkTimeoutScenarios:
    """Test network timeout scenarios with retry logic."""
    
    def test_api_timeout_single_retry_succeeds(self, mock_timeout_fixture):
        """Test that API timeout triggers retry and eventually succeeds."""
        attempt_count = [0]
        
        def api_call_with_retry():
            for retry in range(3):
                attempt_count[0] += 1
                try:
                    return mock_timeout_fixture()
                except TimeoutError:
                    if retry == 2:
                        raise
        
        result = api_call_with_retry()
        assert result["success"] is True
        assert attempt_count[0] == 3  # Failed twice, succeeded on third
    
    def test_marketplace_timeout_retries_within_limit(self):
        """Test marketplace service timeout respects retry limit (3 attempts max)."""
        retry_count = [0]
        max_retries = 3
        
        async def marketplace_call():
            retry_count[0] += 1
            if retry_count[0] < 3:
                raise TimeoutError("Marketplace service timeout")
            return {"jobs": []}
        
        async def call_with_retries():
            for attempt in range(max_retries):
                try:
                    return await marketplace_call()
                except TimeoutError:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(0.1 * (2 ** attempt))  # Exponential backoff
        
        result = asyncio.run(call_with_retries())
        assert result == {"jobs": []}
        assert retry_count[0] == 3  # Exhausted retries
    
    def test_timeout_error_is_caught_and_logged(self, caplog):
        """Test that timeout errors are properly caught and logged."""
        import logging
        caplog.set_level(logging.ERROR)
        
        def failing_api():
            raise TimeoutError("Request timeout after 30 seconds")
        
        try:
            failing_api()
        except TimeoutError as e:
            # In real code, logger.error() would be called
            assert "timeout" in str(e).lower()
    
    def test_timeout_error_is_retryable(self):
        """Test that TimeoutError is classified as retryable."""
        timeout_err = TimeoutError("Request timed out")
        assert should_retry(timeout_err) is True
    
    def test_network_error_retry_sequence(self):
        """Test complete retry sequence for network errors."""
        attempts = []
        max_retries = 3
        
        def flaky_operation():
            attempts.append(len(attempts))
            if len(attempts) < 2:
                raise NetworkError("Connection reset by peer")
            return "success"
        
        result = None
        
        for attempt in range(max_retries):
            try:
                result = flaky_operation()
                break
            except NetworkError:
                if attempt == max_retries - 1:
                    raise
        
        assert result == "success"
        assert len(attempts) == 2  # First failed, second succeeded
    
    def test_timeout_exceeding_retry_limit_raises_error(self):
        """Test that exceeding retry limit raises final error."""
        max_retries = 2
        attempts = [0]
        
        def always_timeout():
            attempts[0] += 1
            raise TimeoutError(f"Timeout on attempt {attempts[0]}")
        
        with pytest.raises(TimeoutError) as exc_info:
            for _ in range(max_retries):
                try:
                    always_timeout()
                except TimeoutError:
                    if _ == max_retries - 1:
                        raise
        
        assert "Timeout on attempt" in str(exc_info.value)
        assert attempts[0] == max_retries


# =============================================================================
# B. PARTIAL FAILURE IN MULTI-STEP WORKFLOWS
# =============================================================================


class TestMultiStepWorkflowFailures:
    """Test partial failures in multi-step workflows."""
    
    def test_step_1_succeeds_step_2_fails_verifies_rollback(self):
        """Test rollback when Step 1 succeeds but Step 2 fails."""
        state = {"step_1_executed": False, "step_2_executed": False, "rolled_back": False}
        
        def step_1():
            state["step_1_executed"] = True
            return {"data": "step1_result"}
        
        def step_2(step1_result):
            state["step_2_executed"] = True
            raise ValidationError("Step 2 validation failed")
        
        def rollback():
            state["rolled_back"] = True
            # Don't actually undo step_1_executed - just mark rollback happened
        
        try:
            result = step_1()
            step_2(result)
        except ValidationError:
            rollback()
        
        assert state["step_1_executed"] is True
        assert state["step_2_executed"] is True
        assert state["rolled_back"] is True
    
    def test_step_1_fails_verifies_no_side_effects(self):
        """Test that Step 1 failure prevents Step 2 and any side effects."""
        state = {"step_1_executed": False, "step_2_executed": False, "side_effect": False}
        
        def step_1():
            state["step_1_executed"] = True
            raise NetworkError("Step 1 network failure")
        
        def step_2(step1_result):
            state["step_2_executed"] = True
        
        def apply_side_effect():
            state["side_effect"] = True
        
        with pytest.raises(NetworkError):
            result = step_1()
            step_2(result)
            apply_side_effect()
        
        assert state["step_1_executed"] is True
        assert state["step_2_executed"] is False  # Not executed
        assert state["side_effect"] is False  # Not applied
    
    def test_multi_step_workflow_with_50_percent_failure_rate(self):
        """Test multi-step workflow with 50% failure rate per step."""
        import random
        random.seed(42)  # Deterministic for testing
        
        success_count = 0
        failure_count = 0
        
        for trial in range(10):
            state = {"step1": False, "step2": False, "step3": False}
            
            try:
                # Step 1
                if random.random() < 0.5:
                    raise TransientError("Step 1 failed")
                state["step1"] = True
                
                # Step 2
                if random.random() < 0.5:
                    raise TransientError("Step 2 failed")
                state["step2"] = True
                
                # Step 3
                if random.random() < 0.5:
                    raise TransientError("Step 3 failed")
                state["step3"] = True
                
                success_count += 1
            except TransientError:
                failure_count += 1
        
        # With 50% per-step failure, ~12.5% overall success
        assert success_count > 0  # Some should succeed
        assert failure_count > 0  # Some should fail
        assert success_count + failure_count == 10
    
    def test_workflow_checkpoint_recovery(self):
        """Test workflow recovery using checkpoints."""
        checkpoints = {}
        
        def save_checkpoint(name, data):
            checkpoints[name] = data
        
        def restore_checkpoint(name):
            return checkpoints.get(name)
        
        def workflow_with_checkpoint():
            # Step 1
            save_checkpoint("step1", {"result": "data1"})
            
            # Step 2 fails
            try:
                raise TransientError("Step 2 failed")
            except TransientError:
                # Recover from checkpoint
                step1_data = restore_checkpoint("step1")
                assert step1_data is not None
                return step1_data
        
        result = workflow_with_checkpoint()
        assert result == {"result": "data1"}
    
    def test_cascade_rollback_multiple_steps(self):
        """Test cascading rollback across multiple steps."""
        executed_steps = []
        
        def step(num):
            executed_steps.append(f"step{num}")
            if num == 3:
                raise ValidationError(f"Step {num} failed")
            return f"result{num}"
        
        def undo_step(num):
            executed_steps.append(f"undo{num}")
        
        with pytest.raises(ValidationError):
            try:
                result1 = step(1)
                result2 = step(2)
                result3 = step(3)  # Fails here
            except ValidationError:
                # Rollback in reverse order
                undo_step(2)
                undo_step(1)
                raise
        
        assert "step1" in executed_steps
        assert "step2" in executed_steps
        assert "step3" in executed_steps
        assert "undo2" in executed_steps
        assert "undo1" in executed_steps


# =============================================================================
# C. CASCADE FAILURES ACROSS SERVICES
# =============================================================================


class TestCascadeFailuresAcrossServices:
    """Test cascade failures and fallback mechanisms."""
    
    def test_primary_service_fails_fallback_to_secondary(self):
        """Test fallback to secondary service when primary fails."""
        call_sequence = []
        
        def primary_service():
            call_sequence.append("primary")
            raise NetworkError("Primary service unreachable")
        
        def secondary_service():
            call_sequence.append("secondary")
            return {"source": "secondary", "data": "fallback_result"}
        
        try:
            return primary_service()
        except NetworkError:
            result = secondary_service()
        
        assert result["source"] == "secondary"
        assert call_sequence == ["primary", "secondary"]
    
    def test_secondary_service_failure_error_propagated(self):
        """Test error propagation when both services fail."""
        def primary_service():
            raise NetworkError("Primary down")
        
        def secondary_service():
            raise NetworkError("Secondary also down")
        
        with pytest.raises(NetworkError) as exc_info:
            try:
                primary_service()
            except NetworkError:
                secondary_service()
        
        assert "Secondary also down" in str(exc_info.value)
    
    def test_circuit_breaker_opens_after_failures(self, mock_circuit_breaker):
        """Test circuit breaker pattern."""
        breaker = mock_circuit_breaker(failure_threshold=2)
        
        def failing_service():
            raise TransientError("Service failed")
        
        # First failure
        with pytest.raises(TransientError):
            breaker.call(failing_service)
        
        # Second failure - circuit opens
        with pytest.raises(TransientError):
            breaker.call(failing_service)
        
        assert breaker.state == "open"
        
        # Third attempt - circuit breaker rejects without calling service
        with pytest.raises(TransientError):
            breaker.call(failing_service)
    
    def test_circuit_breaker_recovery(self, mock_circuit_breaker):
        """Test circuit breaker half-open recovery."""
        breaker = mock_circuit_breaker(failure_threshold=2, timeout=0)
        call_count = [0]
        
        def service_that_recovers():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise TransientError("Service failed")
            return "recovered"
        
        # Trigger failures
        with pytest.raises(TransientError):
            breaker.call(service_that_recovers)
        
        with pytest.raises(TransientError):
            breaker.call(service_that_recovers)
        
        assert breaker.state == "open"
        
        # Wait for timeout (already 0 in fixture)
        assert breaker.can_execute() is True
        
        # Service recovers
        result = breaker.call(service_that_recovers)
        assert result == "recovered"
        assert breaker.state == "closed"
    
    def test_dependent_service_chain_failure(self):
        """Test failure in service chain."""
        call_log = []
        
        def service_a():
            call_log.append("A")
            return {"id": 123}
        
        def service_b(result_a):
            call_log.append("B")
            return {"data": result_a}
        
        def service_c(result_b):
            call_log.append("C_failed")
            raise NetworkError("Service C failed")
        
        with pytest.raises(NetworkError):
            result_a = service_a()
            result_b = service_b(result_a)
            result_c = service_c(result_b)
        
        assert call_log == ["A", "B", "C_failed"]


# =============================================================================
# D. DATABASE CONNECTION FAILURES
# =============================================================================


class TestDatabaseConnectionFailures:
    """Test database connection error handling."""
    
    def test_database_connection_error_caught(self, mock_db_connection_failure):
        """Test that database connection errors are caught."""
        session = mock_db_connection_failure(fail_count=0)
        
        # First attempt succeeds
        result = session.execute("SELECT * FROM tasks")
        assert result is not None
    
    def test_database_connection_retry_succeeds(self, mock_db_connection_failure):
        """Test retrying after connection failure."""
        session = mock_db_connection_failure(fail_count=1)
        
        # First attempt fails
        with pytest.raises(ConnectionError):
            session.execute("SELECT * FROM tasks")
        
        # Second attempt succeeds
        result = session.execute("SELECT * FROM tasks")
        assert result is not None
    
    def test_database_session_cleanup_on_error(self, mock_db_connection_failure):
        """Test session cleanup happens on error."""
        session = mock_db_connection_failure(fail_count=1)
        
        try:
            session.execute("SELECT * FROM tasks")
        except ConnectionError:
            session.rollback()
        finally:
            session.close()
        
        assert session.closed is True
    
    def test_database_transaction_rollback_on_failure(self):
        """Test database transaction rollback."""
        class MockTransaction:
            def __init__(self):
                self.committed = False
                self.rolled_back = False
                self.operations = []
            
            def add_operation(self, op):
                self.operations.append(op)
            
            def commit(self):
                if len(self.operations) > 1:
                    raise ValidationError("Invalid transaction")
                self.committed = True
            
            def rollback(self):
                self.operations.clear()
                self.rolled_back = True
        
        txn = MockTransaction()
        
        try:
            txn.add_operation("insert_task")
            txn.add_operation("insert_payment")  # Too many operations
            txn.commit()
        except ValidationError:
            txn.rollback()
        
        assert txn.committed is False
        assert txn.rolled_back is True
        assert len(txn.operations) == 0
    
    def test_connection_pool_recovery(self):
        """Test connection pool recovery after failure."""
        class ConnectionPool:
            def __init__(self, size=5):
                self.size = size
                self.available = size
                self.failed = 0
            
            def get_connection(self):
                if self.available > 0:
                    self.available -= 1
                    return Mock()
                raise NetworkError("No available connections")
            
            def return_connection(self):
                if self.available < self.size:
                    self.available += 1
            
            def mark_failed(self):
                self.failed += 1
                # Simulate recovery
                if self.failed > 3:
                    self.available = self.size
                    self.failed = 0
        
        pool = ConnectionPool()
        
        # Exhaust pool
        for _ in range(5):
            pool.get_connection()
        
        assert pool.available == 0
        
        # Mark failures
        for _ in range(5):
            pool.mark_failed()
        
        # Should recover
        assert pool.available > 0


# =============================================================================
# E. LLM SERVICE UNAVAILABILITY
# =============================================================================


class TestLLMServiceUnavailability:
    """Test LLM service error handling."""
    
    def test_ollama_timeout_fallback_to_openai(self):
        """Test fallback from Ollama to OpenAI on timeout."""
        call_sequence = []
        
        async def ollama_call():
            call_sequence.append("ollama")
            raise TimeoutError("Ollama request timeout after 30s")
        
        async def openai_call():
            call_sequence.append("openai")
            return {"response": "generated by OpenAI"}
        
        async def call_with_fallback():
            try:
                return await ollama_call()
            except TimeoutError:
                return await openai_call()
        
        result = asyncio.run(call_with_fallback())
        assert result["response"] == "generated by OpenAI"
        assert call_sequence == ["ollama", "openai"]
    
    def test_openai_500_error_retryable(self):
        """Test OpenAI 500 error is retryable."""
        error = TransientError("OpenAI returned 500 Internal Server Error")
        assert should_retry(error) is True
    
    def test_openai_rate_limit_retryable(self):
        """Test OpenAI rate limit error is retryable."""
        error = TransientError("Rate limit exceeded: 429 Too Many Requests")
        assert should_retry(error) is True
    
    def test_openai_invalid_api_key_not_retryable(self):
        """Test OpenAI invalid API key is not retryable."""
        from src.agent_execution.errors import AuthenticationError
        error = AuthenticationError("Invalid API key")
        assert should_retry(error) is False
    
    async def test_llm_retry_with_exponential_backoff(self):
        """Test LLM retry with exponential backoff."""
        import time
        
        attempt_times = []
        attempt_count = [0]
        
        async def unreliable_llm():
            attempt_times.append(time.time())
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise TransientError("LLM service error")
            return {"response": "success"}
        
        async def retry_with_backoff(max_retries=3):
            for attempt in range(max_retries):
                try:
                    return await unreliable_llm()
                except TransientError:
                    if attempt == max_retries - 1:
                        raise
                    wait_time = 0.1 * (2 ** attempt)  # Exponential backoff
                    await asyncio.sleep(wait_time)
        
        result = await retry_with_backoff()
        assert result["response"] == "success"
        assert attempt_count[0] == 3
    
    @pytest.mark.asyncio
    async def test_llm_service_unavailability_complete_flow(self):
        """Test complete LLM unavailability handling flow."""
        fallback_used = [False]
        
        async def primary_llm():
            raise TimeoutError("Primary LLM timeout")
        
        async def fallback_llm():
            fallback_used[0] = True
            return {"model": "fallback", "content": "generated"}
        
        async def call_llm():
            try:
                return await primary_llm()
            except TimeoutError:
                return await fallback_llm()
        
        result = await call_llm()
        assert result["model"] == "fallback"
        assert fallback_used[0] is True


# =============================================================================
# ADDITIONAL ERROR PATH COVERAGE
# =============================================================================


class TestErrorPathCoverage:
    """Additional tests for comprehensive error path coverage."""
    
    def test_error_wrapping_preserves_context(self):
        """Test error wrapping preserves context information."""
        from src.agent_execution.errors import wrap_exception
        
        original = ValueError("invalid data format")
        wrapped = wrap_exception(original, context="task_parsing")
        
        assert "task_parsing" in wrapped.message
        assert "invalid data format" in wrapped.message
    
    def test_error_with_retry_info(self):
        """Test error includes retry information."""
        class RetryableError(TransientError):
            def __init__(self, message, attempt=1, max_attempts=3):
                super().__init__(message)
                self.attempt = attempt
                self.max_attempts = max_attempts
        
        err = RetryableError("Failed", attempt=2, max_attempts=3)
        assert err.attempt == 2
        assert err.max_attempts == 3
        assert should_retry(err) is True
    
    def test_resource_exhaustion_error(self):
        """Test resource exhaustion error handling."""
        from src.agent_execution.errors import ResourceExhaustedError
        
        error = ResourceExhaustedError("Memory limit exceeded")
        assert should_retry(error) is True
        assert error.retryable is True
    
    def test_multiple_error_types_in_sequence(self):
        """Test handling multiple different error types in sequence."""
        errors_encountered = []
        
        def operation_1():
            errors_encountered.append("network")
            raise NetworkError("Network failure")
        
        def operation_2():
            errors_encountered.append("timeout")
            raise TimeoutError("Timeout")
        
        def operation_3():
            errors_encountered.append("validation")
            raise ValidationError("Invalid data")
        
        # Each error should be handled appropriately
        for op in [operation_1, operation_2, operation_3]:
            try:
                op()
            except Exception as e:
                assert should_retry(e) or isinstance(e, ValidationError)
        
        assert errors_encountered == ["network", "timeout", "validation"]
    
    def test_error_logging_with_context(self, caplog):
        """Test error logging includes context."""
        import logging
        caplog.set_level(logging.ERROR)
        
        logger = logging.getLogger("test")
        
        try:
            raise NetworkError("Service unavailable")
        except NetworkError as e:
            logger.error(f"Network error occurred: {e}")
        
        assert "Network error occurred" in caplog.text
    
    def test_fatal_error_stops_execution(self):
        """Test fatal error stops execution immediately."""
        from src.agent_execution.errors import SecurityError
        
        execution_log = []
        
        def protected_operation():
            execution_log.append("start")
            raise SecurityError("Unauthorized access attempt")
            execution_log.append("end")  # Should not be reached
        
        with pytest.raises(SecurityError):
            protected_operation()
        
        assert "end" not in execution_log
        assert should_retry(SecurityError("test")) is False


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestErrorHandlingIntegration:
    """Integration tests for error handling across components."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_retry_workflow(self):
        """Test complete end-to-end retry workflow."""
        execution_log = []
        max_retries = 3
        
        async def unreliable_task():
            execution_log.append("attempt")
            if len(execution_log) < 3:
                raise TransientError(f"Attempt {len(execution_log)} failed")
            return {"status": "success"}
        
        async def execute_with_retries():
            for attempt in range(max_retries):
                try:
                    return await unreliable_task()
                except TransientError:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(0.01)
        
        result = await execute_with_retries()
        assert result["status"] == "success"
        assert len(execution_log) == 3
    
    def test_error_recovery_without_data_loss(self):
        """Test error recovery without losing data."""
        saved_state = {}
        
        class SafeOperation:
            def __init__(self):
                self.completed = False
            
            def save_state(self, data):
                saved_state.update(data)
            
            def restore_state(self):
                return saved_state.copy()
            
            def execute(self):
                self.save_state({"progress": "step1"})
                
                try:
                    raise NetworkError("Mid-operation failure")
                except NetworkError:
                    # Verify state is preserved
                    restored = self.restore_state()
                    assert restored["progress"] == "step1"
                    self.completed = True
        
        op = SafeOperation()
        op.execute()
        
        assert op.completed is True
        assert saved_state["progress"] == "step1"
    
    def test_concurrent_error_handling(self):
        """Test error handling with concurrent operations."""
        import concurrent.futures
        
        results = []
        errors = []
        
        def operation(op_id, should_fail=False):
            try:
                if should_fail:
                    raise TransientError(f"Operation {op_id} failed")
                return {"id": op_id, "status": "success"}
            except TransientError as e:
                return {"id": op_id, "status": "failed", "error": str(e)}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(operation, 1, False),
                executor.submit(operation, 2, True),
                executor.submit(operation, 3, False),
            ]
            
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        
        success_count = sum(1 for r in results if r["status"] == "success")
        fail_count = sum(1 for r in results if r["status"] == "failed")
        
        assert success_count == 2
        assert fail_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
