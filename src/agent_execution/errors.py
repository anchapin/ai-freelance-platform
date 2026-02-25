"""
Error Hierarchy and Categorization

Defines error categories for smart retry logic:
- TransientError: Temporary failures (network, timeout, resource issues)
- PermanentError: Permanent failures (auth, validation, not found)
- FatalError: System-critical failures (corruption, critical state)

This allows the executor to intelligently retry only transient errors.

Issue #37: Error type categorization
"""

from typing import Type, Tuple


class AgentError(Exception):
    """Base exception for all agent execution errors."""

    error_type: str = "unknown"
    retryable: bool = False

    def __init__(self, message: str, original_error: Exception = None):
        """
        Initialize error with message and optional original error.

        Args:
            message: Human-readable error message
            original_error: The underlying exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.original_error = original_error


class TransientError(AgentError):
    """
    Temporary failures that may succeed on retry.

    Examples: network timeout, rate limit, resource exhaustion, connection reset
    """

    error_type: str = "transient"
    retryable: bool = True


class NetworkError(TransientError):
    """Network-related transient errors (timeout, connection reset, DNS)."""

    pass


class TimeoutError(TransientError):
    """Request timeout - try again."""

    pass


class ResourceExhaustedError(TransientError):
    """Memory, disk, or process limits hit - may recover."""

    pass


class PermanentError(AgentError):
    """
    Permanent failures that won't succeed on retry.

    Examples: authentication failure, validation error, resource not found
    """

    error_type: str = "permanent"
    retryable: bool = False


class AuthenticationError(PermanentError):
    """Authentication or authorization failure."""

    pass


class ValidationError(PermanentError):
    """Input validation failure - invalid format, missing field, etc."""

    pass


class NotFoundError(PermanentError):
    """Resource not found (file, API endpoint, database record)."""

    pass


class FatalError(AgentError):
    """
    System-critical failures that require immediate attention.

    Examples: data corruption, security breach, unrecoverable state
    """

    error_type: str = "fatal"
    retryable: bool = False


class DataCorruptionError(FatalError):
    """Data integrity violation detected."""

    pass


class SecurityError(FatalError):
    """Security-related error (auth bypass attempt, injection detected)."""

    pass


# Mapping of exception types to error categories
ERROR_CLASSIFICATION: dict[Type[Exception], Type[AgentError]] = {
    # Network/Transient
    ConnectionError: NetworkError,
    ConnectionRefusedError: NetworkError,
    ConnectionResetError: NetworkError,
    TimeoutError: TimeoutError,
    InterruptedError: TransientError,
    OSError: TransientError,
    # Permanent/User Errors (Code errors that LLM can fix)
    ValueError: ValidationError,
    TypeError: ValidationError,
    KeyError: ValidationError,
    AttributeError: ValidationError,
    IndexError: ValidationError,
    SyntaxError: ValidationError,
    NameError: ValidationError,
    ImportError: ValidationError,
    IndentationError: ValidationError,
    # Other Permanent Errors
    KeyboardInterrupt: PermanentError,
    RuntimeError: PermanentError,
    NotImplementedError: PermanentError,
    # Fatal
    AssertionError: DataCorruptionError,
    SystemExit: FatalError,
    MemoryError: FatalError,
}


def categorize_exception(
    exception: Exception,
) -> Tuple[Type[AgentError], str]:
    """
    Categorize an exception into error type.

    Args:
        exception: The exception to categorize

    Returns:
        Tuple of (error_class, description)
    """
    # Check if exact type matches
    exc_type = type(exception)
    if exc_type in ERROR_CLASSIFICATION:
        error_class = ERROR_CLASSIFICATION[exc_type]
        return error_class, exc_type.__name__

    # Check if it's a subclass of known exceptions
    for known_exc, error_class in ERROR_CLASSIFICATION.items():
        if isinstance(exception, known_exc):
            return error_class, exc_type.__name__

    # Default to transient if unknown (safe to retry)
    return TransientError, exc_type.__name__


def should_retry(exception: Exception) -> bool:
    """
    Determine if an exception should trigger a retry.

    Args:
        exception: The exception to evaluate

    Returns:
        True if the error is retryable, False otherwise
    """
    # If it's already an AgentError, check its retryable property directly
    if isinstance(exception, AgentError):
        return exception.retryable

    # Otherwise, categorize and check the categorized error class
    error_class, _ = categorize_exception(exception)
    return error_class.retryable


def wrap_exception(
    exception: Exception,
    context: str = "",
) -> AgentError:
    """
    Wrap a raw exception with categorized AgentError.

    Args:
        exception: The exception to wrap
        context: Additional context string

    Returns:
        AgentError subclass instance
    """
    error_class, exc_name = categorize_exception(exception)
    message = f"{context}: {str(exception)}" if context else str(exception)
    return error_class(message, original_error=exception)
