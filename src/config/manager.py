"""
Configuration Manager Module

This module provides a centralized ConfigManager class to load and validate
all configuration from environment variables, replacing hardcoded magic numbers
throughout the codebase.

Features:
- Type validation (ensure numeric values are numbers)
- Range validation (e.g., revenue > 0, bid_limit > 0)
- Singleton pattern for global access
- Comprehensive documentation of all thresholds with purpose
"""

import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class ValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigManager:
    """
    Centralized configuration manager for all magic numbers and thresholds.

    This class loads configuration from environment variables with sensible
    defaults and validates all values against type and range constraints.

    Uses singleton pattern to ensure only one instance exists globally.
    """

    _instance: Optional["ConfigManager"] = None

    # ==========================================================================
    # REVENUE & PRICING THRESHOLDS
    # ==========================================================================

    # Min revenue threshold for cloud vs local model selection (in cents)
    # Purpose: Use cloud for high-value tasks, local for low-value to save costs
    # Default: $30 (3000 cents)
    # Validation: Must be >= 100 (1 cent minimum)
    MIN_CLOUD_REVENUE: int

    # Cloud model output cost per 1M tokens (in cents)
    # Purpose: Calculate cost optimization for AI model selection
    # Default: 1000 cents = $10 per 1M output tokens (GPT-4o pricing)
    # Validation: Must be > 0
    CLOUD_GPT4O_OUTPUT_COST: int

    # Default task revenue value (in cents)
    # Purpose: Default revenue estimate when not explicitly provided
    # Default: 500 cents = $5
    # Validation: Must be > 0
    DEFAULT_TASK_REVENUE: int

    # High-value task threshold (in dollars)
    # Purpose: Tasks >= this value are automatically escalated on failure
    # Default: 200 dollars
    # Validation: Must be > 0
    HIGH_VALUE_THRESHOLD: int

    # ==========================================================================
    # BID MANAGEMENT THRESHOLDS
    # ==========================================================================

    # Maximum bid amount allowed (in cents)
    # Purpose: Prevent overly aggressive bids that reduce profit margins
    # Default: 500 cents = $5 (from market_scanner.py)
    # Validation: Must be > 0 and >= MIN_BID_AMOUNT
    MAX_BID_AMOUNT: int

    # Minimum bid amount allowed (in cents)
    # Purpose: Don't submit bids for jobs that are too cheap
    # Default: 10 cents (from market_scanner.py)
    # Validation: Must be > 0 and <= MAX_BID_AMOUNT
    MIN_BID_AMOUNT: int

    # ==========================================================================
    # MARKETPLACE SCANNING TIMEOUTS
    # ==========================================================================

    # Page load timeout for marketplace scanning (in seconds)
    # Purpose: Prevent scanner from hanging on slow/unresponsive pages
    # Default: 30 seconds (from market_scanner.py)
    # Validation: Must be > 0 and <= 300 (5 minutes max)
    PAGE_LOAD_TIMEOUT: int

    # Interval between market scans (in seconds)
    # Purpose: Control scan frequency to balance freshness vs resource usage
    # Default: 300 seconds = 5 minutes (from market_scanner.py)
    # Validation: Must be > 0 and <= 3600 (1 hour max)
    SCAN_INTERVAL: int

    # ==========================================================================
    # SANDBOX EXECUTION TIMEOUTS
    # ==========================================================================

    # Sandbox timeout for Docker-based code execution (in seconds)
    # Purpose: Prevent infinite loops or hanging tasks in sandbox
    # Default: 120 seconds = 2 minutes (from executor.py)
    # Validation: Must be > 0 and <= 600 (10 minutes max)
    DOCKER_SANDBOX_TIMEOUT: int

    # Maximum sandbox timeout for complex tasks (in seconds)
    # Purpose: Allow more time for computationally intensive tasks
    # Default: 600 seconds = 10 minutes (from executor.py)
    # Validation: Must be >= DOCKER_SANDBOX_TIMEOUT
    SANDBOX_TIMEOUT_SECONDS: int

    # ==========================================================================
    # DELIVERY & SECURITY THRESHOLDS
    # ==========================================================================

    # Delivery token TTL (in hours)
    # Purpose: How long delivery tokens remain valid
    # Default: 1 hour (from api/main.py)
    # Validation: Must be > 0 and <= 168 (1 week max)
    DELIVERY_TOKEN_TTL_HOURS: int

    # Max failed delivery attempts before lockout
    # Purpose: Prevent brute force attacks on delivery endpoint
    # Default: 5 attempts (from api/main.py)
    # Validation: Must be > 0 and <= 100
    DELIVERY_MAX_FAILED_ATTEMPTS: int

    # Lockout duration after max failed attempts (in seconds)
    # Purpose: Cool down period for delivery endpoint after failed attempts
    # Default: 3600 seconds = 1 hour (from api/main.py)
    # Validation: Must be > 0 and <= 86400 (1 day max)
    DELIVERY_LOCKOUT_SECONDS: int

    # Max delivery attempts per IP address
    # Purpose: Rate limit delivery attempts per IP
    # Default: 20 attempts (from api/main.py)
    # Validation: Must be > 0 and <= 1000
    DELIVERY_MAX_ATTEMPTS_PER_IP: int

    # IP-based lockout duration (in seconds)
    # Purpose: Cool down period for IP after max attempts
    # Default: 3600 seconds = 1 hour (from api/main.py)
    # Validation: Must be > 0 and <= 86400 (1 day max)
    DELIVERY_IP_LOCKOUT_SECONDS: int

    # ==========================================================================
    # LOCKING & DISTRIBUTION
    # ==========================================================================

    # Bid lock manager TTL (in seconds)
    # Purpose: Prevent duplicate bid placement during concurrent task execution
    # Default: 300 seconds = 5 minutes (from bid_lock_manager.py)
    # Validation: Must be > 0 and <= 3600 (1 hour max)
    BID_LOCK_MANAGER_TTL: int

    # ==========================================================================
    # FILE HANDLING
    # ==========================================================================

    # Maximum file size for uploads (in bytes)
    # Purpose: Prevent large file uploads that could consume resources
    # Default: 50MB (from file_validator.py)
    # Validation: Must be > 0 and <= 1GB
    MAX_FILE_SIZE_BYTES: int

    # ==========================================================================
    # MACHINE LEARNING & DISTILLATION
    # ==========================================================================

    # Minimum examples needed for training distilled models
    # Purpose: Don't start training until we have enough examples
    # Default: 500 examples (from distillation/data_collector.py)
    # Validation: Must be > 0 and <= 10000
    MIN_EXAMPLES_FOR_TRAINING: int

    # ==========================================================================
    # SECURITY & WEBHOOKS
    # ==========================================================================

    # Webhook timestamp validity window (in seconds)
    # Purpose: Prevent replay attacks by rejecting old webhooks
    # Default: 300 seconds = 5 minutes (from webhook_security.py)
    # Validation: Must be > 0 and <= 3600 (1 hour max)
    WEBHOOK_TIMESTAMP_WINDOW: int

    # ==========================================================================
    # HEALTH CHECK & MONITORING
    # ==========================================================================

    # LLM health check response time history size
    # Purpose: Keep recent response times for latency averaging
    # Default: 100 samples (from llm_health_check.py)
    # Validation: Must be > 0 and <= 10000
    LLM_HEALTH_CHECK_HISTORY_SIZE: int

    # Initial backoff delay for LLM health check retries (in milliseconds)
    # Purpose: Starting delay for exponential backoff on health check failures
    # Default: 100ms (from llm_health_check.py)
    # Validation: Must be > 0 and <= 10000
    LLM_HEALTH_CHECK_INITIAL_DELAY_MS: int

    # Maximum backoff delay for LLM health check retries (in milliseconds)
    # Purpose: Max delay for exponential backoff to prevent excessive waits
    # Default: 10000ms = 10 seconds (from llm_health_check.py)
    # Validation: Must be >= INITIAL_DELAY_MS
    LLM_HEALTH_CHECK_MAX_DELAY_MS: int

    # ==========================================================================
    # CIRCUIT BREAKER
    # ==========================================================================

    # URL circuit breaker cooldown duration (in seconds)
    # Purpose: Recovery time before retrying failed URL
    # Default: 300 seconds = 5 minutes (from url_circuit_breaker.py)
    # Validation: Must be > 0 and <= 3600 (1 hour max)
    URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int

    def __init__(self):
        """Initialize ConfigManager with environment variables."""
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Load all configuration from environment and validate."""
        # Load revenue thresholds
        self.MIN_CLOUD_REVENUE = self._load_int(
            "MIN_CLOUD_REVENUE",
            3000,
            min_val=100,
            description="Min cloud revenue (cents)",
        )
        self.CLOUD_GPT4O_OUTPUT_COST = self._load_int(
            "CLOUD_GPT4O_OUTPUT_COST",
            1000,
            min_val=1,
            description="Cloud output cost per 1M tokens (cents)",
        )
        self.DEFAULT_TASK_REVENUE = self._load_int(
            "DEFAULT_TASK_REVENUE",
            500,
            min_val=1,
            description="Default task revenue (cents)",
        )
        self.HIGH_VALUE_THRESHOLD = self._load_int(
            "HIGH_VALUE_THRESHOLD",
            200,
            min_val=1,
            description="High-value task threshold (dollars)",
        )

        # Load bid management thresholds
        max_bid = self._load_int(
            "MAX_BID_AMOUNT",
            500,
            min_val=1,
            description="Max bid amount (cents)",
        )
        min_bid = self._load_int(
            "MIN_BID_AMOUNT",
            10,
            min_val=1,
            description="Min bid amount (cents)",
        )

        # Validate bid range
        if min_bid > max_bid:
            raise ValidationError(
                f"MIN_BID_AMOUNT ({min_bid}) cannot exceed "
                f"MAX_BID_AMOUNT ({max_bid})"
            )

        self.MIN_BID_AMOUNT = min_bid
        self.MAX_BID_AMOUNT = max_bid

        # Load marketplace scanning timeouts
        self.PAGE_LOAD_TIMEOUT = self._load_int(
            "PAGE_LOAD_TIMEOUT",
            30,
            min_val=1,
            max_val=300,
            description="Page load timeout (seconds)",
        )
        self.SCAN_INTERVAL = self._load_int(
            "SCAN_INTERVAL",
            300,
            min_val=1,
            max_val=3600,
            description="Scan interval (seconds)",
        )

        # Load sandbox execution timeouts
        docker_timeout = self._load_int(
            "DOCKER_SANDBOX_TIMEOUT",
            120,
            min_val=1,
            max_val=600,
            description="Docker sandbox timeout (seconds)",
        )
        sandbox_max_timeout = self._load_int(
            "SANDBOX_TIMEOUT_SECONDS",
            600,
            min_val=1,
            max_val=3600,
            description="Max sandbox timeout (seconds)",
        )

        # Validate sandbox timeout
        if docker_timeout > sandbox_max_timeout:
            raise ValidationError(
                f"DOCKER_SANDBOX_TIMEOUT ({docker_timeout}) cannot exceed "
                f"SANDBOX_TIMEOUT_SECONDS ({sandbox_max_timeout})"
            )

        self.DOCKER_SANDBOX_TIMEOUT = docker_timeout
        self.SANDBOX_TIMEOUT_SECONDS = sandbox_max_timeout

        # Load delivery & security thresholds
        self.DELIVERY_TOKEN_TTL_HOURS = self._load_int(
            "DELIVERY_TOKEN_TTL_HOURS",
            1,
            min_val=1,
            max_val=168,
            description="Delivery token TTL (hours)",
        )
        self.DELIVERY_MAX_FAILED_ATTEMPTS = self._load_int(
            "DELIVERY_MAX_FAILED_ATTEMPTS",
            5,
            min_val=1,
            max_val=100,
            description="Max delivery failed attempts",
        )
        self.DELIVERY_LOCKOUT_SECONDS = self._load_int(
            "DELIVERY_LOCKOUT_SECONDS",
            3600,
            min_val=1,
            max_val=86400,
            description="Delivery lockout duration (seconds)",
        )
        self.DELIVERY_MAX_ATTEMPTS_PER_IP = self._load_int(
            "DELIVERY_MAX_ATTEMPTS_PER_IP",
            20,
            min_val=1,
            max_val=1000,
            description="Max delivery attempts per IP",
        )
        self.DELIVERY_IP_LOCKOUT_SECONDS = self._load_int(
            "DELIVERY_IP_LOCKOUT_SECONDS",
            3600,
            min_val=1,
            max_val=86400,
            description="IP lockout duration (seconds)",
        )

        # Load locking & distribution
        self.BID_LOCK_MANAGER_TTL = self._load_int(
            "BID_LOCK_MANAGER_TTL",
            300,
            min_val=1,
            max_val=3600,
            description="Bid lock manager TTL (seconds)",
        )

        # Load file handling
        self.MAX_FILE_SIZE_BYTES = self._load_int(
            "MAX_FILE_SIZE_BYTES",
            50 * 1024 * 1024,  # 50MB default
            min_val=1024,  # 1KB minimum
            max_val=1024 * 1024 * 1024,  # 1GB maximum
            description="Max file size (bytes)",
        )

        # Load ML & distillation
        self.MIN_EXAMPLES_FOR_TRAINING = self._load_int(
            "MIN_EXAMPLES_FOR_TRAINING",
            500,
            min_val=1,
            max_val=10000,
            description="Min examples for training",
        )

        # Load security & webhooks
        self.WEBHOOK_TIMESTAMP_WINDOW = self._load_int(
            "WEBHOOK_TIMESTAMP_WINDOW",
            300,
            min_val=1,
            max_val=3600,
            description="Webhook timestamp window (seconds)",
        )

        # Load health check & monitoring
        self.LLM_HEALTH_CHECK_HISTORY_SIZE = self._load_int(
            "LLM_HEALTH_CHECK_HISTORY_SIZE",
            100,
            min_val=1,
            max_val=10000,
            description="LLM health check history size",
        )
        self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS = self._load_int(
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS",
            100,
            min_val=1,
            max_val=10000,
            description="LLM health check initial delay (ms)",
        )
        self.LLM_HEALTH_CHECK_MAX_DELAY_MS = self._load_int(
            "LLM_HEALTH_CHECK_MAX_DELAY_MS",
            10000,
            min_val=1,
            max_val=300000,
            description="LLM health check max delay (ms)",
        )

        # Validate health check delays
        if (
            self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS
            > self.LLM_HEALTH_CHECK_MAX_DELAY_MS
        ):
            raise ValidationError(
                f"LLM_HEALTH_CHECK_INITIAL_DELAY_MS "
                f"({self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS}) cannot exceed "
                f"LLM_HEALTH_CHECK_MAX_DELAY_MS "
                f"({self.LLM_HEALTH_CHECK_MAX_DELAY_MS})"
            )

        # Load circuit breaker
        self.URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS = self._load_int(
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            300,
            min_val=1,
            max_val=3600,
            description="URL circuit breaker cooldown (seconds)",
        )

    @staticmethod
    def _load_int(
        env_var: str,
        default: int,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
        description: str = "",
    ) -> int:
        """
        Load and validate an integer configuration value.

        Args:
            env_var: Environment variable name
            default: Default value if not set
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            description: Human-readable description for error messages

        Returns:
            Validated integer value

        Raises:
            ValidationError: If value fails type or range validation
        """
        value_str = os.environ.get(env_var)

        if value_str is None:
            value = default
        else:
            try:
                value = int(value_str)
            except ValueError:
                raise ValidationError(
                    f"{env_var}: Expected integer, got '{value_str}' "
                    f"({description})"
                )

        # Validate range
        if min_val is not None and value < min_val:
            raise ValidationError(
                f"{env_var}: {value} is below minimum {min_val} "
                f"({description})"
            )

        if max_val is not None and value > max_val:
            raise ValidationError(
                f"{env_var}: {value} exceeds maximum {max_val} "
                f"({description})"
            )

        return value

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert all configuration to dictionary.

        Returns:
            Dictionary of all configuration values
        """
        return {
            # Revenue thresholds
            "MIN_CLOUD_REVENUE": self.MIN_CLOUD_REVENUE,
            "CLOUD_GPT4O_OUTPUT_COST": self.CLOUD_GPT4O_OUTPUT_COST,
            "DEFAULT_TASK_REVENUE": self.DEFAULT_TASK_REVENUE,
            "HIGH_VALUE_THRESHOLD": self.HIGH_VALUE_THRESHOLD,
            # Bid management
            "MAX_BID_AMOUNT": self.MAX_BID_AMOUNT,
            "MIN_BID_AMOUNT": self.MIN_BID_AMOUNT,
            # Marketplace scanning
            "PAGE_LOAD_TIMEOUT": self.PAGE_LOAD_TIMEOUT,
            "SCAN_INTERVAL": self.SCAN_INTERVAL,
            # Sandbox execution
            "DOCKER_SANDBOX_TIMEOUT": self.DOCKER_SANDBOX_TIMEOUT,
            "SANDBOX_TIMEOUT_SECONDS": self.SANDBOX_TIMEOUT_SECONDS,
            # Delivery & security
            "DELIVERY_TOKEN_TTL_HOURS": self.DELIVERY_TOKEN_TTL_HOURS,
            "DELIVERY_MAX_FAILED_ATTEMPTS": self.DELIVERY_MAX_FAILED_ATTEMPTS,
            "DELIVERY_LOCKOUT_SECONDS": self.DELIVERY_LOCKOUT_SECONDS,
            "DELIVERY_MAX_ATTEMPTS_PER_IP": self.DELIVERY_MAX_ATTEMPTS_PER_IP,
            "DELIVERY_IP_LOCKOUT_SECONDS": self.DELIVERY_IP_LOCKOUT_SECONDS,
            # Locking & distribution
            "BID_LOCK_MANAGER_TTL": self.BID_LOCK_MANAGER_TTL,
            # File handling
            "MAX_FILE_SIZE_BYTES": self.MAX_FILE_SIZE_BYTES,
            # ML & distillation
            "MIN_EXAMPLES_FOR_TRAINING": self.MIN_EXAMPLES_FOR_TRAINING,
            # Security & webhooks
            "WEBHOOK_TIMESTAMP_WINDOW": self.WEBHOOK_TIMESTAMP_WINDOW,
            # Health check & monitoring
            "LLM_HEALTH_CHECK_HISTORY_SIZE": self.LLM_HEALTH_CHECK_HISTORY_SIZE,
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS": (
                self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS
            ),
            "LLM_HEALTH_CHECK_MAX_DELAY_MS": self.LLM_HEALTH_CHECK_MAX_DELAY_MS,
            # Circuit breaker
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS": (
                self.URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS
            ),
        }

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """
        Get or create singleton instance of ConfigManager.

        Returns:
            ConfigManager instance

        Raises:
            ValidationError: If configuration validation fails
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None


# Singleton getter for convenience
def get_config() -> ConfigManager:
    """
    Get the global ConfigManager instance.

    Returns:
        ConfigManager instance

    Raises:
        ValidationError: If configuration validation fails
    """
    return ConfigManager.get_instance()


if __name__ == "__main__":
    # Example usage and validation
    try:
        config = get_config()
        print("Configuration loaded successfully!")
        print("\nAll Configuration Values:")
        print("-" * 60)
        for key, value in sorted(config.to_dict().items()):
            print(f"{key:45s}: {value:>10}")
        print("-" * 60)
    except ValidationError as e:
        print(f"Configuration validation failed: {e}")
        exit(1)
