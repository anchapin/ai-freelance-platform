"""
Test suite for error categorization and smart retry logic (Issue #37).

Tests the error hierarchy and categorization functions to ensure:
- Correct classification of exceptions
- Smart retry logic only retries transient errors
- Proper error wrapping with context
"""

import pytest
from src.agent_execution.errors import (
    AgentError,
    TransientError,
    PermanentError,
    FatalError,
    NetworkError,
    TimeoutError,
    ResourceExhaustedError,
    AuthenticationError,
    ValidationError,
    NotFoundError,
    DataCorruptionError,
    SecurityError,
    categorize_exception,
    should_retry,
    wrap_exception,
)


class TestTransientErrors:
    """Test classification of transient (retryable) errors."""

    def test_connection_error_is_transient(self):
        """ConnectionError should be classified as NetworkError (transient)."""
        exc = ConnectionError("Failed to connect")
        error_class, desc = categorize_exception(exc)
        assert error_class == NetworkError
        assert error_class.retryable is True
        assert desc == "ConnectionError"

    def test_connection_refused_is_transient(self):
        """ConnectionRefusedError should be classified as NetworkError."""
        exc = ConnectionRefusedError("Connection refused")
        error_class, desc = categorize_exception(exc)
        assert error_class == NetworkError
        assert error_class.retryable is True

    def test_connection_reset_is_transient(self):
        """ConnectionResetError should be classified as NetworkError."""
        exc = ConnectionResetError("Connection reset by peer")
        error_class, desc = categorize_exception(exc)
        assert error_class == NetworkError
        assert error_class.retryable is True

    def test_timeout_error_is_transient(self):
        """TimeoutError should be classified as transient."""
        exc = TimeoutError("Request timed out")
        error_class, desc = categorize_exception(exc)
        assert error_class == TimeoutError
        assert error_class.retryable is True

    def test_interrupted_error_is_transient(self):
        """InterruptedError should be classified as transient."""
        exc = InterruptedError("Operation interrupted")
        error_class, desc = categorize_exception(exc)
        assert error_class == TransientError
        assert error_class.retryable is True

    def test_os_error_is_transient(self):
        """OSError should be classified as transient."""
        exc = OSError("I/O error")
        error_class, desc = categorize_exception(exc)
        assert error_class == TransientError
        assert error_class.retryable is True


class TestPermanentErrors:
    """Test classification of permanent (non-retryable) errors."""

    def test_value_error_is_permanent(self):
        """ValueError should be classified as ValidationError (permanent)."""
        exc = ValueError("Invalid value")
        error_class, desc = categorize_exception(exc)
        assert error_class == ValidationError
        assert error_class.retryable is False
        assert desc == "ValueError"

    def test_type_error_is_permanent(self):
        """TypeError should be classified as ValidationError."""
        exc = TypeError("Wrong type")
        error_class, desc = categorize_exception(exc)
        assert error_class == ValidationError
        assert error_class.retryable is False

    def test_key_error_is_permanent(self):
        """KeyError should be classified as ValidationError."""
        exc = KeyError("key not found")
        error_class, desc = categorize_exception(exc)
        assert error_class == ValidationError
        assert error_class.retryable is False

    def test_attribute_error_is_permanent(self):
        """AttributeError should be classified as ValidationError."""
        exc = AttributeError("No such attribute")
        error_class, desc = categorize_exception(exc)
        assert error_class == ValidationError
        assert error_class.retryable is False

    def test_index_error_is_permanent(self):
        """IndexError should be classified as ValidationError."""
        exc = IndexError("Index out of range")
        error_class, desc = categorize_exception(exc)
        assert error_class == ValidationError
        assert error_class.retryable is False

    def test_keyboard_interrupt_is_permanent(self):
        """KeyboardInterrupt should be classified as permanent."""
        exc = KeyboardInterrupt()
        error_class, desc = categorize_exception(exc)
        assert error_class == PermanentError
        assert error_class.retryable is False

    def test_runtime_error_is_permanent(self):
        """RuntimeError should be classified as permanent."""
        exc = RuntimeError("Runtime error")
        error_class, desc = categorize_exception(exc)
        assert error_class == PermanentError
        assert error_class.retryable is False

    def test_not_implemented_error_is_permanent(self):
        """NotImplementedError should be classified as permanent."""
        exc = NotImplementedError("Not implemented")
        error_class, desc = categorize_exception(exc)
        assert error_class == PermanentError
        assert error_class.retryable is False


class TestFatalErrors:
    """Test classification of fatal (critical) errors."""

    def test_assertion_error_is_fatal(self):
        """AssertionError should be classified as DataCorruptionError (fatal)."""
        exc = AssertionError("Assertion failed")
        error_class, desc = categorize_exception(exc)
        assert error_class == DataCorruptionError
        assert error_class.retryable is False

    def test_system_exit_is_fatal(self):
        """SystemExit should be classified as FatalError."""
        exc = SystemExit()
        error_class, desc = categorize_exception(exc)
        assert error_class == FatalError
        assert error_class.retryable is False

    def test_memory_error_is_fatal(self):
        """MemoryError should be classified as FatalError."""
        exc = MemoryError("Out of memory")
        error_class, desc = categorize_exception(exc)
        assert error_class == FatalError
        assert error_class.retryable is False


class TestUnknownErrors:
    """Test handling of unknown error types."""

    def test_unknown_error_defaults_to_transient(self):
        """Unknown exception types should default to transient (safe to retry)."""
        exc = Exception("Unknown error")
        error_class, desc = categorize_exception(exc)
        assert error_class == TransientError
        assert error_class.retryable is True
        assert desc == "Exception"

    def test_custom_exception_defaults_to_transient(self):
        """Custom exception types should default to transient."""
        class CustomError(Exception):
            pass

        exc = CustomError("Custom error")
        error_class, desc = categorize_exception(exc)
        assert error_class == TransientError
        assert error_class.retryable is True


class TestShouldRetryFunction:
    """Test the should_retry() function for practical retry logic."""

    def test_should_retry_on_network_error(self):
        """should_retry should return True for network errors."""
        exc = ConnectionError("Network failure")
        assert should_retry(exc) is True

    def test_should_retry_on_timeout(self):
        """should_retry should return True for timeout errors."""
        exc = TimeoutError("Request timeout")
        assert should_retry(exc) is True

    def test_should_not_retry_on_validation_error(self):
        """should_retry should return False for validation errors."""
        exc = ValueError("Invalid input")
        assert should_retry(exc) is False

    def test_should_not_retry_on_type_error(self):
        """should_retry should return False for type errors."""
        exc = TypeError("Wrong type")
        assert should_retry(exc) is False

    def test_should_not_retry_on_key_error(self):
        """should_retry should return False for key errors."""
        exc = KeyError("Missing key")
        assert should_retry(exc) is False

    def test_should_not_retry_on_memory_error(self):
        """should_retry should return False for fatal memory errors."""
        exc = MemoryError("Out of memory")
        assert should_retry(exc) is False

    def test_should_retry_on_unknown_error(self):
        """should_retry should return True for unknown errors (safe default)."""
        exc = Exception("Unknown")
        assert should_retry(exc) is True


class TestWrapExceptionFunction:
    """Test the wrap_exception() function for error wrapping."""

    def test_wrap_network_error(self):
        """wrap_exception should create NetworkError for connection errors."""
        original = ConnectionError("Connection failed")
        wrapped = wrap_exception(original, context="API call")
        
        assert isinstance(wrapped, NetworkError)
        assert wrapped.message == "API call: Connection failed"
        assert wrapped.original_error is original
        assert wrapped.retryable is True

    def test_wrap_validation_error(self):
        """wrap_exception should create ValidationError for value errors."""
        original = ValueError("Invalid format")
        wrapped = wrap_exception(original, context="Input validation")
        
        assert isinstance(wrapped, ValidationError)
        assert wrapped.message == "Input validation: Invalid format"
        assert wrapped.original_error is original
        assert wrapped.retryable is False

    def test_wrap_without_context(self):
        """wrap_exception should work without context string."""
        original = TimeoutError("Timeout")
        wrapped = wrap_exception(original)
        
        assert isinstance(wrapped, TimeoutError)
        assert wrapped.message == "Timeout"
        assert wrapped.original_error is original

    def test_wrapped_error_preserves_type(self):
        """Wrapped error should preserve exception type information."""
        original = ConnectionRefusedError("Connection refused")
        wrapped = wrap_exception(original)
        
        assert isinstance(wrapped, NetworkError)
        assert isinstance(wrapped, TransientError)
        assert wrapped.error_type == "transient"


class TestErrorHierarchy:
    """Test the error class hierarchy and properties."""

    def test_transient_error_is_retryable(self):
        """TransientError class should be marked as retryable."""
        assert TransientError.retryable is True
        assert TransientError.error_type == "transient"

    def test_permanent_error_is_not_retryable(self):
        """PermanentError class should not be retryable."""
        assert PermanentError.retryable is False
        assert PermanentError.error_type == "permanent"

    def test_fatal_error_is_not_retryable(self):
        """FatalError class should not be retryable."""
        assert FatalError.retryable is False
        assert FatalError.error_type == "fatal"

    def test_all_errors_inherit_from_agent_error(self):
        """All custom error classes should inherit from AgentError."""
        assert issubclass(TransientError, AgentError)
        assert issubclass(PermanentError, AgentError)
        assert issubclass(FatalError, AgentError)
        assert issubclass(NetworkError, TransientError)
        assert issubclass(ValidationError, PermanentError)
        assert issubclass(DataCorruptionError, FatalError)

    def test_agent_error_default_properties(self):
        """AgentError should have default error properties."""
        assert AgentError.error_type == "unknown"
        assert AgentError.retryable is False


class TestRealWorldScenarios:
    """Test error categorization in realistic scenarios."""

    def test_database_connection_timeout_is_retryable(self):
        """Database connection timeout should be retryable."""
        exc = TimeoutError("Database connection timeout")
        assert should_retry(exc) is True

    def test_invalid_json_is_not_retryable(self):
        """Invalid JSON input should not be retryable."""
        exc = ValueError("Invalid JSON format")
        assert should_retry(exc) is False

    def test_missing_required_field_is_not_retryable(self):
        """Missing required field should not be retryable."""
        exc = KeyError("required_field")
        assert should_retry(exc) is False

    def test_network_timeout_in_api_call_is_retryable(self):
        """Network timeout during API call should be retryable."""
        original = TimeoutError("API request timed out")
        wrapped = wrap_exception(original, context="API call to external service")
        assert should_retry(wrapped.original_error) is True

    def test_authentication_failure_is_permanent(self):
        """Authentication failures should be permanent errors."""
        exc = ValueError("Invalid credentials")
        error_class, _ = categorize_exception(exc)
        assert error_class.retryable is False

    def test_resource_exhaustion_is_transient(self):
        """Resource exhaustion should be transient (temporary)."""
        exc = ResourceExhaustedError("Out of file descriptors")
        assert should_retry(exc) is True

    def test_data_corruption_is_fatal(self):
        """Data corruption should be fatal."""
        exc = DataCorruptionError("Checksum mismatch")
        assert should_retry(exc) is False

    def test_security_error_is_fatal(self):
        """Security errors should be fatal."""
        exc = SecurityError("SQL injection detected")
        assert should_retry(exc) is False


class TestExceptionProperties:
    """Test properties and behavior of exception instances."""

    def test_agent_error_message_property(self):
        """AgentError should store message."""
        exc = AgentError("Test message")
        assert exc.message == "Test message"
        assert str(exc) == "Test message"

    def test_agent_error_original_error_property(self):
        """AgentError should store original exception."""
        original = ValueError("Original")
        exc = AgentError("Wrapped", original_error=original)
        assert exc.original_error is original

    def test_transient_error_creation(self):
        """TransientError should be creatable with message."""
        exc = TransientError("Temporary failure")
        assert exc.message == "Temporary failure"
        assert exc.retryable is True
        assert exc.error_type == "transient"

    def test_permanent_error_creation(self):
        """PermanentError should be creatable with message."""
        exc = PermanentError("Permanent failure")
        assert exc.message == "Permanent failure"
        assert exc.retryable is False
        assert exc.error_type == "permanent"

    def test_fatal_error_creation(self):
        """FatalError should be creatable with message."""
        exc = FatalError("Critical failure")
        assert exc.message == "Critical failure"
        assert exc.retryable is False
        assert exc.error_type == "fatal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
