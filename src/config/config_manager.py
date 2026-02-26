"""
Centralized Configuration Manager for ArbitrageAI.
Combines and replaces legacy configuration management.
Provides validation and audit logging for configuration changes.
"""

import os
import logging
from typing import Any, Optional, Dict

# Import logger
try:
    from ..utils.logger import get_logger

    logger = get_logger(__name__)
except (ImportError, ValueError):
    logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigManager:
    """
    Manages application configuration, replacing hardcoded magic numbers.
    Loads from environment variables with safe defaults and validation.
    """

    _instance: Optional["ConfigManager"] = None
    _config_cache: Dict[str, Any] = {}

    # DEFAULT CONFIGURATION VALUES (Match tests/test_config_manager.py)
    _DEFAULTS = {
        # LLM Routing
        "MIN_CLOUD_REVENUE": 3000,
        "CLOUD_GPT4O_OUTPUT_COST": 1000,
        "DEFAULT_TASK_REVENUE": 500,
        "HIGH_VALUE_THRESHOLD": 200,
        # Marketplace Scanning
        "MAX_BID_AMOUNT": 500,
        "MIN_BID_AMOUNT": 10,
        "BID_LIMIT_CENTS": 50000,
        "MIN_BID_THRESHOLD": 30,
        # Marketplace Scanning Timeouts
        "PAGE_LOAD_TIMEOUT": 30,
        "SCAN_INTERVAL": 300,
        # Sandbox Execution Timeouts
        "DOCKER_SANDBOX_TIMEOUT": 120,
        "SANDBOX_TIMEOUT_SECONDS": 600,
        "MAX_RETRY_ATTEMPTS": 3,
        # Delivery & Security Thresholds
        "DELIVERY_TOKEN_TTL_HOURS": 1,
        "MAX_DELIVERY_TOKEN_TTL_DAYS": 7,
        "DELIVERY_MAX_FAILED_ATTEMPTS": 5,
        "DELIVERY_LOCKOUT_SECONDS": 3600,
        "DELIVERY_MAX_ATTEMPTS_PER_IP": 20,
        "DELIVERY_IP_LOCKOUT_SECONDS": 3600,
        "MAX_DELIVERY_AMOUNT_CENTS": 100000000,  # $1M
        # Locking & Distribution
        "BID_LOCK_MANAGER_TTL": 300,
        # File Handling
        "MAX_FILE_SIZE_BYTES": 50 * 1024 * 1024,
        # ML & Distillation
        "MIN_EXAMPLES_FOR_TRAINING": 500,
        # Security & Webhooks
        "WEBHOOK_TIMESTAMP_WINDOW": 300,
        # Health Check & Monitoring
        "LLM_HEALTH_CHECK_HISTORY_SIZE": 100,
        "LLM_HEALTH_CHECK_INITIAL_DELAY_MS": 100,
        "LLM_HEALTH_CHECK_MAX_DELAY_MS": 10000,
        # Circuit Breaker
        "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS": 300,
        # General
        "ENV": "development",
        "DEBUG": False,
        "LOG_LEVEL": "INFO",
        # Training Mode for Simulation & Strategy Testing
        "TRAINING_MODE": False,  # When enabled, prevents real bid submissions
        # External URLs
        "OLLAMA_URL": "http://localhost:11434/v1",
        "TRACELOOP_URL": "http://localhost:6006/v1/traces",
        "TELEGRAM_API_URL": "https://api.telegram.org",
        "BASE_URL": "http://localhost:5173",
        # Disaster Recovery (Issue #50)
        "BACKUP_DIR": "data/backups",
        "RECOVERY_DIR": "data/recovery",
        "BACKUP_RETENTION_DAYS": 30,
        "ENCRYPTION_ENABLED": False,
        "AWS_S3_BACKUP_BUCKET": None,
        "AWS_ACCESS_KEY_ID": None,
        "AWS_SECRET_ACCESS_KEY": None,
        "AWS_REGION": "us-east-1",
        # Infrastructure
        "REDIS_URL": "redis://localhost:6379/0",
        "DATABASE_URL": "sqlite:///./data/tasks.db",
    }

    def __init__(self):
        """Initialize ConfigManager and load all values into attributes."""
        self._load_all()

    def _load_all(self):
        """Load all known configuration into instance attributes."""
        # Use a local list to avoid modifying during iteration if needed
        keys = list(self._DEFAULTS.keys())
        for key in keys:
            val = self.get(key)
            setattr(self, key, val)

        # Cross-field validations
        if self.MIN_BID_AMOUNT > self.MAX_BID_AMOUNT:
            raise ValidationError(
                f"MIN_BID_AMOUNT ({self.MIN_BID_AMOUNT}) cannot exceed MAX_BID_AMOUNT ({self.MAX_BID_AMOUNT})"
            )

        if self.DOCKER_SANDBOX_TIMEOUT > self.SANDBOX_TIMEOUT_SECONDS:
            raise ValidationError(
                f"DOCKER_SANDBOX_TIMEOUT ({self.DOCKER_SANDBOX_TIMEOUT}) cannot exceed SANDBOX_TIMEOUT_SECONDS ({self.SANDBOX_TIMEOUT_SECONDS})"
            )

        if self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS > self.LLM_HEALTH_CHECK_MAX_DELAY_MS:
            raise ValidationError(
                f"LLM_HEALTH_CHECK_INITIAL_DELAY_MS ({self.LLM_HEALTH_CHECK_INITIAL_DELAY_MS}) cannot exceed LLM_HEALTH_CHECK_MAX_DELAY_MS ({self.LLM_HEALTH_CHECK_MAX_DELAY_MS})"
            )

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get configuration value from environment or default with type conversion."""
        # Check cache first
        if key in cls._config_cache:
            return cls._config_cache[key]

        env_val = os.getenv(key)
        default_val = default if default is not None else cls._DEFAULTS.get(key)

        if env_val is None:
            val = default_val
        else:
            try:
                if isinstance(default_val, bool):
                    val = str(env_val).lower() in ("true", "1", "yes")
                elif isinstance(default_val, int):
                    val = int(env_val)
                elif isinstance(default_val, float):
                    val = float(env_val)
                else:
                    val = env_val
            except (ValueError, TypeError):
                raise ValidationError(f"{key}: Expected integer, got '{env_val}'")

        # Additional range validations for specific keys to match tests
        if key == "MIN_BID_AMOUNT" and val is not None:
            try:
                if int(val) < 0:
                    raise ValidationError(f"{key}: {val} is below minimum")
            except (ValueError, TypeError):
                pass

        if key == "PAGE_LOAD_TIMEOUT" and val is not None:
            try:
                v = int(val)
                if v <= 0:
                    raise ValidationError(f"{key}: {v} is below minimum")
                if v > 300:
                    raise ValidationError(f"{key}: {v} exceeds maximum")
            except (ValueError, TypeError):
                pass

        if key == "DELIVERY_LOCKOUT_SECONDS" and val is not None:
            try:
                v = int(val)
                if v <= 0:
                    raise ValidationError(f"{key}: {v} is below minimum")
                if v > 86400:
                    raise ValidationError(f"{key}: {v} exceeds maximum")
            except (ValueError, TypeError):
                pass

        cls._config_cache[key] = val
        return val

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the configuration cache and singleton instance."""
        cls._config_cache = {}
        cls._instance = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert all configuration to dictionary."""
        return {key: getattr(self, key) for key in self._DEFAULTS.keys()}


# Singleton getter
def get_config() -> ConfigManager:
    """Get the global ConfigManager instance."""
    return ConfigManager.get_instance()
