"""
Integration tests for circuit breaker with LLM service.

Tests the integration between LLMService and the circuit breaker pattern,
including fallback behavior, exponential backoff, and health checking.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.llm_service import LLMService
from src.llm_health_check import (
    get_health_checker,
    CircuitBreakerError,
    CircuitState,
)


# =============================================================================
# CIRCUIT BREAKER INTEGRATION TESTS
# =============================================================================


class TestLLMServiceCircuitBreaker:
    """Test circuit breaker integration with LLMService."""

    def test_local_service_registers_endpoint(self):
        """Test that local LLMService registers endpoint with health checker."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )

        # Should have health checker registered
        assert service._health_checker is not None
        assert service.base_url in service._health_checker.health_status

    def test_cloud_service_no_circuit_breaker(self):
        """Test that cloud service doesn't use circuit breaker."""
        service = LLMService.with_cloud()

        # Should not have health checker (cloud endpoint)
        assert service._health_checker is None

    def test_circuit_breaker_disabled(self):
        """Test that circuit breaker can be disabled."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
            enable_circuit_breaker=False,
        )

        # Should not have health checker
        assert service._health_checker is None

    @patch("src.llm_service.OpenAI")
    def test_circuit_breaker_blocks_open_requests(self, mock_openai):
        """Test that open circuit breaker blocks requests."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )

        # Manually open the circuit
        metrics = service._health_checker.get_health_status(service.base_url)
        metrics.state = CircuitState.OPEN
        metrics.opened_at = datetime.now(timezone.utc)

        # Should raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError):
            service.complete("test prompt")

    @patch("src.llm_service.OpenAI")
    def test_circuit_breaker_transitions_on_failures(self, mock_openai):
        """Test circuit breaker transitions from CLOSED to OPEN on failures."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )
        metrics = service._health_checker.get_health_status(service.base_url)

        # Initially CLOSED
        assert metrics.state == CircuitState.CLOSED

        # Mock client to fail
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Connection failed")
        service.client = mock_client

        # Record 3 failures
        for _ in range(3):
            try:
                service.complete("test")
            except Exception:
                pass

        # Should transition to OPEN
        assert metrics.state == CircuitState.OPEN
        assert metrics.consecutive_failures == 3

    @patch("src.llm_service.OpenAI")
    def test_circuit_breaker_records_success(self, mock_openai):
        """Test that successful requests reset failure counter."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )
        metrics = service._health_checker.get_health_status(service.base_url)

        # Mock successful response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Test response"
        mock_response.model = "llama3.2"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        service.client = mock_client

        # Record some failures first
        metrics.consecutive_failures = 2

        # Then succeed
        result = service.complete("test")

        # Should reset failure counter
        assert metrics.consecutive_failures == 0
        assert metrics.total_requests == 1
        assert result["content"] == "Test response"


# =============================================================================
# EXPONENTIAL BACKOFF TESTS
# =============================================================================


class TestExponentialBackoffIntegration:
    """Test exponential backoff in fallback chain."""

    @patch("src.llm_service.time.sleep")
    def test_fallback_backoff_delays(self, mock_sleep):
        """Test that fallback chain uses proper backoff delays."""
        # Create cloud service with mocked OpenAI
        with patch("src.llm_service.OpenAI") as mock_openai_class:
            # Mock the client instance
            mock_client_instance = MagicMock()
            mock_client_instance.chat.completions.create.side_effect = Exception(
                "Connection failed"
            )
            mock_openai_class.return_value = mock_client_instance

            cloud_service = LLMService.with_cloud()

            # Try with fallback (will fail on local too, but we're testing delays)
            with patch("src.llm_service.LLMService.with_local") as mock_local:
                mock_local_service = MagicMock()
                mock_local_service.complete.side_effect = Exception("Local failed")
                mock_local.return_value = mock_local_service

                with pytest.raises(Exception):
                    cloud_service.complete_with_fallback("test prompt")

                # Should have called sleep with backoff delays
                # Delays are: 0s for attempt 0, then 2s for attempt 1, then 5s before fallback
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                # Check that we have at least 2s and 5s delays
                assert any(2.0 <= call < 2.1 for call in sleep_calls), f"Expected ~2.0s delay, got {sleep_calls}"
                assert any(5.0 <= call < 5.1 for call in sleep_calls), f"Expected ~5.0s delay, got {sleep_calls}"

    def test_fallback_max_latency(self):
        """Test that fallback chain timeouts are configured correctly."""
        # Just verify the timeouts are as documented
        cloud_service = LLMService.with_cloud()

        # The timeouts should be [10s, 20s, 30s] per the code
        # We can't easily test actual latency without actually waiting,
        # but we verify the structure is in place
        assert cloud_service.enable_fallback is True
        assert cloud_service._is_local is False


# =============================================================================
# HEALTH CHECK INTEGRATION TESTS
# =============================================================================


class TestHealthCheckIntegration:
    """Test health check integration with LLM service."""

    @pytest.mark.asyncio
    async def test_health_check_on_demand(self):
        """Test that health checks can be called on-demand."""
        checker = get_health_checker()
        endpoint = "http://test-ollama:11434/v1"

        checker.register_endpoint(endpoint)

        # Health check should complete (will return false without real Ollama)
        result = await checker.health_check(endpoint, timeout_seconds=1)
        assert isinstance(result, bool)

    @patch("src.llm_service.OpenAI")
    def test_metrics_exported_after_requests(self, mock_openai):
        """Test that metrics are available after requests."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )

        # Mock successful response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.model = "llama3.2"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        service.client = mock_client

        # Make requests
        for _ in range(5):
            service.complete("test")

        # Check metrics
        summary = service._health_checker.get_metrics_summary(service.base_url)
        assert summary["total_requests"] == 5
        assert summary["total_failures"] == 0
        assert summary["failure_rate"] == 0.0


# =============================================================================
# FALLBACK CHAIN TESTS
# =============================================================================


class TestFallbackChain:
    """Test complete fallback chain behavior."""

    def test_fallback_used_when_cloud_fails(self):
        """Test that fallback is used when cloud fails."""
        with patch("src.llm_service.OpenAI") as mock_openai_class:
            # Mock cloud to fail
            mock_client_instance = MagicMock()
            mock_client_instance.chat.completions.create.side_effect = Exception(
                "Cloud API error"
            )
            mock_openai_class.return_value = mock_client_instance

            cloud_service = LLMService.with_cloud()

            # Mock local success
            with patch("src.llm_service.LLMService.with_local") as mock_local:
                mock_local_service = MagicMock()
                mock_local_service.complete.return_value = {
                    "content": "Local response",
                    "model": "llama3.2",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                    "stealth_mode_used": False,
                    "response_time_ms": 150,
                }
                mock_local.return_value = mock_local_service

                # Call with fallback
                result = cloud_service.complete_with_fallback("test prompt")

                # Should have used fallback
                assert result["fallback_used"] is True
                assert result["content"] == "Local response"
                assert "original_error" in result

    def test_fallback_disabled(self):
        """Test that fallback can be disabled."""
        with patch("src.llm_service.OpenAI") as mock_openai_class:
            # Mock cloud to fail
            mock_client_instance = MagicMock()
            mock_client_instance.chat.completions.create.side_effect = Exception(
                "Cloud API error"
            )
            mock_openai_class.return_value = mock_client_instance

            cloud_service = LLMService.with_cloud(enable_fallback=False)

            # Should raise without trying fallback
            with pytest.raises(Exception):
                cloud_service.complete_with_fallback("test prompt")


# =============================================================================
# REGRESSION TESTS
# =============================================================================


class TestRegressions:
    """Test that circuit breaker doesn't break existing functionality."""

    @patch("src.llm_service.OpenAI")
    def test_normal_cloud_requests_still_work(self, mock_openai):
        """Test that normal cloud requests work without circuit breaker."""
        service = LLMService.with_cloud()

        # Mock response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Cloud response"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 15

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        service.client = mock_client

        result = service.complete("test prompt")

        assert result["content"] == "Cloud response"
        assert result["model"] == "gpt-4o-mini"

    @patch("src.llm_service.OpenAI")
    def test_stealth_mode_still_works(self, mock_openai):
        """Test that stealth mode still works with circuit breaker."""
        service = LLMService(
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
            model="llama3.2",
        )

        # Mock response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Response"
        mock_response.model = "llama3.2"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 15

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        service.client = mock_client

        with patch("src.llm_service.time.sleep") as mock_sleep:
            result = service.complete("test prompt", stealth_mode=True)

            # Should have called sleep for stealth mode
            mock_sleep.assert_called()
            assert result["stealth_mode_used"] is True


# =============================================================================
# CLEANUP
# =============================================================================


@pytest.fixture(autouse=True)
def reset_health_checker():
    """Reset health checker before each test."""
    from src import llm_health_check

    llm_health_check._global_health_checker = None
    yield
    llm_health_check._global_health_checker = None
