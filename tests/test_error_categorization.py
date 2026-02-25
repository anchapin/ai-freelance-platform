"""
Error Type Categorization Tests (Issue #37)

Tests for the error hierarchy and categorization system that enables smart
retry logic in the executor.

Coverage includes:
- Error classification (TransientError, PermanentError, FatalError)
- Error categorization from exception types
- Retry decision logic
- Exception wrapping and context preservation
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
    ERROR_CLASSIFICATION,
)


# =============================================================================
# ERROR HIERARCHY TESTS
# =============================================================================


class TestErrorHierarchy:
    """Test error class hierarchy and inheritance."""

    def test_error_inheritance_transient(self):
        """Test that TransientError inherits from AgentError."""
        err = TransientError("test error")
        assert isinstance(err, AgentError)
        assert isinstance(err, Exception)
        assert err.retryable is True
        assert err.error_type == "transient"

    def test_error_inheritance_permanent(self):
        """Test that PermanentError inherits from AgentError."""
        err = PermanentError("test error")
        assert isinstance(err, AgentError)
        assert isinstance(err, Exception)
        assert err.retryable is False
        assert err.error_type == "permanent"

    def test_error_inheritance_fatal(self):
        """Test that FatalError inherits from AgentError."""
        err = FatalError("test error")
        assert isinstance(err, AgentError)
        assert isinstance(err, Exception)
        assert err.retryable is False
        assert err.error_type == "fatal"

    def test_specific_transient_errors(self):
        """Test specific TransientError subclasses."""
        network_err = NetworkError("connection failed")
        assert isinstance(network_err, TransientError)
        assert network_err.retryable is True

        timeout_err = TimeoutError("request timed out")
        assert isinstance(timeout_err, TransientError)
        assert timeout_err.retryable is True

        resource_err = ResourceExhaustedError("out of memory")
        assert isinstance(resource_err, TransientError)
        assert resource_err.retryable is True

    def test_specific_permanent_errors(self):
        """Test specific PermanentError subclasses."""
        auth_err = AuthenticationError("invalid credentials")
        assert isinstance(auth_err, PermanentError)
        assert auth_err.retryable is False

        validation_err = ValidationError("invalid input")
        assert isinstance(validation_err, PermanentError)
        assert validation_err.retryable is False

        notfound_err = NotFoundError("resource not found")
        assert isinstance(notfound_err, PermanentError)
        assert notfound_err.retryable is False

    def test_specific_fatal_errors(self):
        """Test specific FatalError subclasses."""
        corruption_err = DataCorruptionError("data integrity violation")
        assert isinstance(corruption_err, FatalError)
        assert corruption_err.retryable is False

        security_err = SecurityError("security breach detected")
        assert isinstance(security_err, FatalError)
        assert security_err.retryable is False


# =============================================================================
# ERROR MESSAGE PRESERVATION
# =============================================================================


class TestErrorMessagePreservation:
    """Test that error messages and context are preserved."""

    def test_error_message_stored(self):
        """Test that error message is accessible."""
        msg = "database connection failed"
        err = NetworkError(msg)
        assert err.message == msg
        assert str(err) == msg

    def test_original_error_preserved(self):
        """Test that original exception is preserved."""
        original = ValueError("invalid value")
        wrapped = ValidationError("validation failed", original_error=original)
        assert wrapped.original_error is original
        assert wrapped.original_error.args[0] == "invalid value"

    def test_error_context_information(self):
        """Test that context information can be attached."""
        msg = "network timeout"
        context = "during_api_call"
        err = wrap_exception(ConnectionError(msg), context=context)
        assert "during_api_call" in err.message
        assert "network timeout" in err.message


# =============================================================================
# EXCEPTION CATEGORIZATION TESTS
# =============================================================================


class TestExceptionCategorization:
    """Test categorization of standard Python exceptions."""

    def test_categorize_network_errors(self):
        """Test categorization of network-related exceptions."""
        error_class, exc_name = categorize_exception(ConnectionError("test"))
        assert issubclass(error_class, NetworkError)
        assert exc_name == "ConnectionError"

        error_class, exc_name = categorize_exception(ConnectionRefusedError("test"))
        assert issubclass(error_class, NetworkError)

        error_class, exc_name = categorize_exception(ConnectionResetError("test"))
        assert issubclass(error_class, NetworkError)

    def test_categorize_timeout_errors(self):
        """Test categorization of timeout exceptions."""
        error_class, exc_name = categorize_exception(TimeoutError("test"))
        assert issubclass(error_class, TimeoutError)
        assert exc_name == "TimeoutError"

    def test_categorize_validation_errors(self):
        """Test categorization of validation exceptions."""
        validation_errors = [
            ValueError("invalid value"),
            TypeError("wrong type"),
            KeyError("missing key"),
            AttributeError("no attribute"),
            IndexError("index out of range"),
        ]

        for err in validation_errors:
            error_class, _ = categorize_exception(err)
            assert issubclass(error_class, ValidationError)

    def test_categorize_fatal_errors(self):
        """Test categorization of fatal exceptions."""
        error_class, exc_name = categorize_exception(AssertionError("test"))
        assert issubclass(error_class, DataCorruptionError)

        error_class, exc_name = categorize_exception(MemoryError("test"))
        assert issubclass(error_class, FatalError)

    def test_categorize_unknown_error(self):
        """Test categorization of unknown exception types."""
        class CustomException(Exception):
            pass

        error_class, exc_name = categorize_exception(CustomException("test"))
        # Unknown errors default to TransientError (safe to retry)
        assert issubclass(error_class, TransientError)
        assert exc_name == "CustomException"


# =============================================================================
# RETRY DECISION LOGIC TESTS
# =============================================================================


class TestRetryDecision:
    """Test the should_retry function for retry decision making."""

    def test_retry_transient_errors(self):
        """Test that transient errors trigger retry."""
        # Network errors
        assert should_retry(ConnectionError("connection failed")) is True
        assert should_retry(ConnectionRefusedError("refused")) is True
        assert should_retry(ConnectionResetError("reset")) is True

        # Timeout
        assert should_retry(TimeoutError("timed out")) is True

    def test_no_retry_permanent_errors(self):
        """Test that permanent errors don't trigger retry."""
        # Authentication
        assert should_retry(AuthenticationError("invalid credentials")) is False

        # Validation
        assert should_retry(ValidationError("invalid input")) is False

    def test_no_retry_fatal_errors(self):
        """Test that fatal errors don't trigger retry."""
        assert should_retry(DataCorruptionError("corruption detected")) is False
        assert should_retry(SecurityError("security breach")) is False

    def test_agent_error_retryable_check(self):
        """Test retryability check on AgentError instances."""
        # Retryable errors
        transient = NetworkError("network failed")
        assert should_retry(transient) is True

        # Non-retryable errors
        permanent = ValidationError("validation failed")
        assert should_retry(permanent) is False

        fatal = DataCorruptionError("data corrupted")
        assert should_retry(fatal) is False


# =============================================================================
# EXCEPTION WRAPPING TESTS
# =============================================================================


class TestExceptionWrapping:
    """Test the wrap_exception function."""

    def test_wrap_basic_exception(self):
        """Test basic exception wrapping."""
        original = ValueError("invalid value")
        wrapped = wrap_exception(original)

        assert isinstance(wrapped, ValidationError)
        assert wrapped.original_error is original
        assert "invalid value" in str(wrapped)

    def test_wrap_with_context(self):
        """Test exception wrapping with context."""
        original = ConnectionError("network failed")
        context = "api_request"
        wrapped = wrap_exception(original, context=context)

        assert isinstance(wrapped, NetworkError)
        assert "api_request" in wrapped.message
        assert "network failed" in wrapped.message

    def test_wrap_network_error(self):
        """Test wrapping network exceptions."""
        original = ConnectionRefusedError("refused")
        wrapped = wrap_exception(original, context="database_connection")

        assert isinstance(wrapped, NetworkError)
        assert wrapped.retryable is True
        assert "database_connection" in wrapped.message

    def test_wrap_timeout_error(self):
        """Test wrapping timeout exceptions."""
        original = TimeoutError("request timeout")
        wrapped = wrap_exception(original, context="http_request")

        assert isinstance(wrapped, TimeoutError)
        assert wrapped.retryable is True

    def test_wrap_unknown_error(self):
        """Test wrapping unknown exception type."""
        class CustomError(Exception):
            pass

        original = CustomError("custom failure")
        wrapped = wrap_exception(original)

        # Unknown exceptions default to TransientError
        assert isinstance(wrapped, TransientError)
        assert wrapped.retryable is True


# =============================================================================
# ERROR CLASSIFICATION MAPPING TESTS
# =============================================================================


class TestErrorClassificationMapping:
    """Test the ERROR_CLASSIFICATION mapping."""

    def test_classification_completeness(self):
        """Test that critical exception types are classified."""
        assert ConnectionError in ERROR_CLASSIFICATION
        assert TimeoutError in ERROR_CLASSIFICATION
        assert ValueError in ERROR_CLASSIFICATION
        assert TypeError in ERROR_CLASSIFICATION
        assert KeyError in ERROR_CLASSIFICATION

    def test_classification_correctness(self):
        """Test that classifications are correct."""
        # Network errors should map to NetworkError
        assert issubclass(
            ERROR_CLASSIFICATION[ConnectionError],
            NetworkError
        )
        assert issubclass(
            ERROR_CLASSIFICATION[ConnectionRefusedError],
            NetworkError
        )

        # Value errors should map to ValidationError
        assert issubclass(
            ERROR_CLASSIFICATION[ValueError],
            ValidationError
        )

        # Memory errors should map to FatalError
        assert issubclass(
            ERROR_CLASSIFICATION[MemoryError],
            FatalError
        )


# =============================================================================
# EXECUTOR INTEGRATION TESTS
# =============================================================================


class TestExecutorErrorHandling:
    """Test error handling in executor context."""

    def test_transient_error_signals_retry(self):
        """Test that transient errors signal retry in executor context."""
        # Simulate executor checking should_retry
        error = NetworkError("connection timeout")
        assert should_retry(error) is True

    def test_permanent_error_signals_no_retry(self):
        """Test that permanent errors signal no retry in executor context."""
        error = AuthenticationError("invalid API key")
        assert should_retry(error) is False

    def test_syntax_error_categorized_as_permanent(self):
        """Test that SyntaxError is categorized as permanent but LLM-fixable."""
        error_class, _ = categorize_exception(SyntaxError("invalid syntax"))
        # Note: SyntaxError maps to ValidationError in ERROR_CLASSIFICATION
        assert issubclass(error_class, PermanentError)

    def test_name_error_categorized_as_permanent(self):
        """Test that NameError is categorized as permanent but LLM-fixable."""
        error_class, _ = categorize_exception(NameError("undefined variable"))
        # NameError should map to ValidationError
        assert issubclass(error_class, PermanentError)


# =============================================================================
# ERROR TYPE DOCUMENTATION TESTS
# =============================================================================


class TestErrorDocumentation:
    """Test that error types have proper documentation."""

    def test_error_classes_have_docstrings(self):
        """Test that error classes have docstrings."""
        assert AgentError.__doc__ is not None
        assert TransientError.__doc__ is not None
        assert PermanentError.__doc__ is not None
        assert FatalError.__doc__ is not None

    def test_error_types_have_descriptions(self):
        """Test error_type attributes are properly set."""
        assert AgentError.error_type == "unknown"
        assert TransientError.error_type == "transient"
        assert PermanentError.error_type == "permanent"
        assert FatalError.error_type == "fatal"

    def test_retry_flags_are_correct(self):
        """Test retryable flags are properly set."""
        assert TransientError.retryable is True
        assert PermanentError.retryable is False
        assert FatalError.retryable is False


# =============================================================================
# REGRESSION TESTS
# =============================================================================


class TestErrorCategorizationRegression:
    """Regression tests for error categorization."""

    def test_network_errors_always_retryable(self):
        """Verify network errors are always retryable."""
        network_errors = [
            ConnectionError("test"),
            ConnectionRefusedError("test"),
            ConnectionResetError("test"),
        ]
        for err in network_errors:
            assert should_retry(err) is True, f"Network error not retryable: {type(err)}"

    def test_validation_errors_never_retryable(self):
        """Verify validation errors are never retryable by executor."""
        # These are permanent but LLM can fix them
        validation_errors = [
            ValueError("test"),
            TypeError("test"),
            KeyError("test"),
        ]
        for err in validation_errors:
            assert should_retry(err) is False, f"Validation error marked retryable: {type(err)}"

    def test_fatal_errors_never_retryable(self):
        """Verify fatal errors are never retryable."""
        assert should_retry(MemoryError("test")) is False
        assert should_retry(SystemExit("test")) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
