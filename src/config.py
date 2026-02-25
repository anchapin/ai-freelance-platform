"""
Configuration Management

Centralized configuration loading from environment variables with defaults.
Supports both local development and production deployments.
"""

import os


def get_redis_url() -> str:
    """
    Get Redis connection URL from environment.

    Priority order:
    1. REDIS_URL env variable (format: redis://host:port/db)
    2. Separate REDIS_HOST, REDIS_PORT, REDIS_DB variables
    3. Default: redis://localhost:6379/0 (local development)

    Returns:
        Redis connection URL

    Raises:
        ValueError: If Redis connection cannot be determined
    """
    # Try explicit URL first
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis_url

    # Try component-based config
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    password = os.getenv("REDIS_PASSWORD", "")

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    else:
        return f"redis://{host}:{port}/{db}"


def get_database_url() -> str:
    """
    Get SQLAlchemy database URL from environment.

    Default: SQLite at data/tasks.db (local development)

    Returns:
        Database URL
    """
    return os.getenv("DATABASE_URL", "sqlite:///./data/tasks.db")


def get_openai_api_key() -> str:
    """Get OpenAI API key from environment."""
    api_key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("API_KEY or OPENAI_API_KEY environment variable not set")
    return api_key


def get_stripe_secret_key() -> str:
    """Get Stripe secret key from environment."""
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise ValueError("STRIPE_SECRET_KEY environment variable not set")
    return key


def get_stripe_webhook_secret() -> str:
    """Get Stripe webhook secret from environment."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET environment variable not set")
    return secret


def is_debug() -> bool:
    """Check if debug mode is enabled."""
    return os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")


def get_log_level() -> str:
    """Get log level from environment."""
    return os.getenv("LOG_LEVEL", "INFO")


def get_max_bid_amount() -> int:
    """Get max bid amount in cents from environment."""
    return int(os.getenv("MAX_BID_AMOUNT", "50000"))  # $500 default


def get_min_bid_amount() -> int:
    """Get min bid amount in cents from environment."""
    return int(os.getenv("MIN_BID_AMOUNT", "1000"))  # $10 default


def should_use_redis_locks() -> bool:
    """
    Determine if Redis-backed distributed locks should be used.
    
    Priority:
    1. USE_REDIS_LOCKS env variable (explicit override)
    2. REDIS_URL availability (try to auto-detect)
    3. Default: True for production, False for development
    
    Returns:
        True if Redis locks should be used, False for in-memory fallback
    """
    # Explicit override
    use_redis = os.getenv("USE_REDIS_LOCKS")
    if use_redis is not None:
        return use_redis.lower() in ("true", "1", "yes")
    
    # Check if REDIS_URL or Redis config is available
    if os.getenv("REDIS_URL"):
        return True
    
    if os.getenv("REDIS_HOST") or os.getenv("REDIS_PORT"):
        return True
    
    # Default: use Redis unless in development mode
    is_dev = os.getenv("ENV", "development").lower() == "development"
    return not is_dev
