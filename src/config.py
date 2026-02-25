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


# =============================================================================
# EXTERNAL SERVICE URLs (Issue #28: Configuration)
# =============================================================================


def get_ollama_url() -> str:
    """
    Get Ollama local inference server URL from environment.

    Environment variable: OLLAMA_URL
    Default: http://localhost:11434/v1

    Returns:
        Ollama base URL for LLM inference
    """
    return os.getenv("OLLAMA_URL", "http://localhost:11434/v1")


def get_traceloop_url() -> str:
    """
    Get Traceloop collector URL from environment.

    Environment variable: TRACELOOP_URL
    Default: http://localhost:6006/v1/traces

    Returns:
        Traceloop traces endpoint URL
    """
    return os.getenv("TRACELOOP_URL", "http://localhost:6006/v1/traces")


def get_telegram_api_url() -> str:
    """
    Get Telegram Bot API base URL from environment.

    Environment variable: TELEGRAM_API_URL
    Default: https://api.telegram.org

    Returns:
        Telegram Bot API base URL
    """
    return os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")


def validate_urls() -> None:
    """
    Validate that all external service URLs are properly configured.

    Checks that URLs are:
    - Not empty
    - Valid URL format (starts with http:// or https://)

    Raises:
        ValueError: If any URL is invalid or misconfigured
    """
    urls = {
        "OLLAMA_URL": get_ollama_url(),
        "TRACELOOP_URL": get_traceloop_url(),
        "TELEGRAM_API_URL": get_telegram_api_url(),
    }

    for name, url in urls.items():
        if not url:
            raise ValueError(f"{name} is not configured")

        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(
                f"{name}={url} is invalid. Must start with http:// or https://"
            )


# =============================================================================
# STARTUP VALIDATION (Issue #27: Configuration Audit)
# =============================================================================


def validate_critical_env_vars() -> None:
    """
    Validate that all critical environment variables are set.

    This function checks for required variables that would cause runtime failures
    if missing. Fails loudly on startup rather than silently at runtime.

    Raises:
        ValueError: If any critical environment variable is missing or invalid
    """
    errors = []

    # Check for LLM API configuration
    # Either API_KEY or OPENAI_API_KEY must be set for cloud models
    if not os.getenv("API_KEY") and not os.getenv("OPENAI_API_KEY"):
        errors.append(
            "LLM API key not configured: set either API_KEY or OPENAI_API_KEY"
        )

    # Check for Stripe configuration in non-development mode
    env_type = os.getenv("ENV", "development").lower()
    if env_type == "production":
        if not os.getenv("STRIPE_SECRET_KEY"):
            errors.append("STRIPE_SECRET_KEY not set (required in production)")

        if not os.getenv("STRIPE_WEBHOOK_SECRET"):
            errors.append("STRIPE_WEBHOOK_SECRET not set (required in production)")

        if not os.getenv("DATABASE_URL"):
            errors.append("DATABASE_URL not set (required in production)")

    # Warn about insecure defaults
    client_secret = os.getenv("CLIENT_AUTH_SECRET", "")
    if client_secret == "CHANGE_ME_IN_PRODUCTION_use_a_random_32_byte_key":
        if env_type == "production":
            errors.append(
                "CLIENT_AUTH_SECRET using insecure default in production. "
                "Generate a secure key: openssl rand -hex 32"
            )

    # Validate delivery token configuration
    try:
        int(os.getenv("DELIVERY_TOKEN_TTL_HOURS", "1"))
        int(os.getenv("DELIVERY_MAX_FAILED_ATTEMPTS", "5"))
        int(os.getenv("DELIVERY_LOCKOUT_SECONDS", "3600"))
        int(os.getenv("DELIVERY_MAX_ATTEMPTS_PER_IP", "20"))
        int(os.getenv("DELIVERY_IP_LOCKOUT_SECONDS", "3600"))
    except ValueError as e:
        errors.append(f"Invalid delivery token configuration: {e}")

    # Validate bid amount configuration
    try:
        min_bid = int(os.getenv("MIN_BID_AMOUNT", "1000"))
        max_bid = int(os.getenv("MAX_BID_AMOUNT", "50000"))
        if min_bid > max_bid:
            errors.append(
                f"Invalid bid amounts: MIN_BID_AMOUNT ({min_bid}) > "
                f"MAX_BID_AMOUNT ({max_bid})"
            )
    except ValueError as e:
        errors.append(f"Invalid bid amount configuration: {e}")

    # Validate timeout configurations
    try:
        int(os.getenv("DOCKER_SANDBOX_TIMEOUT", "120"))
        int(os.getenv("MARKET_SCAN_PAGE_TIMEOUT", "30"))
        int(os.getenv("MARKET_SCAN_INTERVAL", "300"))
    except ValueError as e:
        errors.append(f"Invalid timeout configuration: {e}")

    # Validate boolean flags
    for flag in [
        "USE_DOCKER_SANDBOX",
        "USE_LOCAL_BY_DEFAULT",
        "AUTONOMOUS_SCAN_ENABLED",
        "ENABLE_DISTILLATION_CAPTURE",
    ]:
        value = os.getenv(flag, "").lower()
        if value and value not in ("true", "false", "yes", "no", "1", "0"):
            errors.append(f"Invalid boolean value for {flag}={value}")

    # Validate logging level
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in valid_log_levels:
        errors.append(
            f"Invalid LOG_LEVEL={log_level}. Must be one of {valid_log_levels}"
        )

    # Raise all errors at once for better visibility
    if errors:
        error_message = "Configuration validation failed:\n  " + "\n  ".join(errors)
        raise ValueError(error_message)


def get_all_configured_env_vars() -> dict:
    """
    Get a summary of all environment variables used in the application.

    Returns:
        Dictionary mapping variable names to their current values (with secrets masked)
    """
    import re

    # All known environment variables in the application
    all_vars = {
        # Database
        "DATABASE_URL": "sqlite:///./data/tasks.db",
        "REDIS_URL": None,
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "REDIS_DB": "0",
        "REDIS_PASSWORD": None,
        "USE_REDIS_LOCKS": None,
        # LLM
        "API_KEY": None,
        "OPENAI_API_KEY": None,
        "BASE_URL": "https://api.openai.com/v1",
        "CLOUD_MODEL": "gpt-4o-mini",
        "LOCAL_BASE_URL": "http://localhost:11434/v1",
        "LOCAL_API_KEY": "not-needed",
        "LOCAL_MODEL": "llama3.2",
        "USE_LOCAL_BY_DEFAULT": "false",
        "TASK_MODEL_MAP": "{}",
        "TASK_USE_LOCAL_MAP": "{}",
        "OLLAMA_URL": "http://localhost:11434/v1",
        "MIN_CLOUD_REVENUE": "3000",
        # Marketplace
        "MARKETPLACES_FILE": "data/marketplaces.json",
        "MARKETPLACE_URL": None,
        "AUTONOMOUS_SCAN_ENABLED": "false",
        "MARKET_SCAN_MODEL": "llama3.2",
        "MARKET_SCAN_PAGE_TIMEOUT": "30",
        "MARKET_SCAN_INTERVAL": "300",
        "MAX_BID_AMOUNT": "50000",
        "MIN_BID_AMOUNT": "1000",
        # Sandbox
        "USE_DOCKER_SANDBOX": "true",
        "DOCKER_SANDBOX_IMAGE": "ai-sandbox-base",
        "DOCKER_SANDBOX_TIMEOUT": "120",
        "E2B_API_KEY": None,
        # Payment
        "STRIPE_SECRET_KEY": None,
        "STRIPE_WEBHOOK_SECRET": None,
        "STRIPE_PUBLISHABLE_KEY": None,
        # Delivery tokens
        "DELIVERY_TOKEN_TTL_HOURS": "1",
        "DELIVERY_MAX_FAILED_ATTEMPTS": "5",
        "DELIVERY_LOCKOUT_SECONDS": "3600",
        "DELIVERY_MAX_ATTEMPTS_PER_IP": "20",
        "DELIVERY_IP_LOCKOUT_SECONDS": "3600",
        # Authentication
        "CLIENT_AUTH_SECRET": None,
        # Notifications
        "TELEGRAM_BOT_TOKEN": None,
        "TELEGRAM_CHAT_ID": None,
        "TELEGRAM_API_URL": "https://api.telegram.org",
        # Security
        "ANTIVIRUS_SERVICE": "mock",
        "VIRUSTOTAL_API_KEY": None,
        # Observability
        "ENVIRONMENT": "development",
        "ENV": "development",
        "DEBUG": "false",
        "LOG_LEVEL": "INFO",
        "TRACELOOP_URL": "http://localhost:6006/v1/traces",
        # Distillation
        "ENABLE_DISTILLATION_CAPTURE": "true",
        # General
        "CORS_ORIGINS": "http://localhost:5173",
        "BASE_URL": "http://localhost:5173",
    }

    # Build result with current values
    result = {}
    secret_patterns = [
        "API_KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "WEBHOOK",
        "STRIPE",
    ]

    for var_name, default_value in all_vars.items():
        current_value = os.getenv(var_name)

        # Determine what to display
        if current_value is not None:
            display_value = current_value
        elif default_value is not None:
            display_value = default_value
        else:
            display_value = "(not set)"

        # Mask secrets
        is_secret = any(
            re.search(pattern, var_name, re.IGNORECASE) for pattern in secret_patterns
        )
        if is_secret and display_value != "(not set)":
            display_value = "***" + display_value[-4:] if len(display_value) > 4 else "***"

        result[var_name] = display_value

    return result
