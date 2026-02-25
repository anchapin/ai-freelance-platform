"""Error hierarchy for smart retry logic - Issue #37"""

class CustomError(Exception):
    """Base exception for all custom errors"""
    pass

class RetryableError(CustomError):
    """Error that can be safely retried"""
    pass

class PermanentError(CustomError):
    """Error that should not be retried"""
    pass

class NetworkError(RetryableError):
    """Network-related errors (transient)"""
    pass

class RateLimitError(RetryableError):
    """Rate limit hit (transient, can retry after backoff)"""
    pass

class ValidationError(PermanentError):
    """Input validation failed (permanent)"""
    pass

class AuthenticationError(PermanentError):
    """Authentication failed (permanent)"""
    pass
