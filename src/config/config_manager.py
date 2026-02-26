"""
Centralized Configuration Manager for ArbitrageAI.
Addresses Issue #26: Configuration: Hardcoded Magic Numbers.
Provides validation and audit logging for configuration changes.
"""

import os
import logging
from typing import Any, Optional, Dict

# Import logger
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ConfigManager:
    """
    Manages application configuration, replacing hardcoded magic numbers.
    Loads from environment variables with safe defaults.
    """
    
    # DEFAULT CONFIGURATION VALUES (Issue #26)
    _DEFAULTS = {
        # LLM Routing
        "MIN_CLOUD_REVENUE": 3000,          # $30.00 in cents (Issue #26: src/llm_service.py)
        
        # Marketplace Scanning
        "BID_LIMIT_CENTS": 50000,           # $500.00 in cents (Issue #26: src/agent_execution/market_scanner.py)
        "MIN_BID_THRESHOLD": 30,            # $30 minimum bid to consider (from src/api/main.py autonomous loop)
        
        # Profit Protection / Escalation
        "HIGH_VALUE_THRESHOLD": 200,        # $200.00 in dollars (Issue #26: src/api/main.py)
        
        # Retries & Timeouts
        "MAX_RETRY_ATTEMPTS": 3,
        "DOCKER_SANDBOX_TIMEOUT": 120,
        "MARKET_SCAN_PAGE_TIMEOUT": 30,
        "MARKET_SCAN_INTERVAL": 300,
        
        # Security
        "MAX_FILE_SIZE_BYTES": 50 * 1024 * 1024,  # 50MB
        "DELIVERY_TOKEN_TTL_HOURS": 72,
        "DELIVERY_MAX_FAILED_ATTEMPTS": 5,
        "DELIVERY_LOCKOUT_SECONDS": 3600,
        
        # General
        "ENV": "development",
        "DEBUG": False,
        "LOG_LEVEL": "INFO",
        
        # External URLs (Issue #28: Hardcoded URLs)
        "OLLAMA_URL": "http://localhost:11434/v1",
        "TRACELOOP_URL": "http://localhost:6006/v1/traces",
        "TELEGRAM_API_URL": "https://api.telegram.org",
        "BASE_URL": "http://localhost:5173",
    }
    
    _config_cache: Dict[str, Any] = {}
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Get configuration value from environment or default.
        Logs an audit trail if a value is overridden by environment.
        """
        # Return from cache if already loaded
        if key in cls._config_cache:
            return cls._config_cache[key]
        
        # Get from environment
        env_val = os.getenv(key)
        
        # Determine default
        default_val = default if default is not None else cls._DEFAULTS.get(key)
        
        if env_val is None:
            # Use default
            val = default_val
        else:
            # Type conversion based on default type
            try:
                if isinstance(default_val, bool):
                    val = env_val.lower() in ("true", "1", "yes")
                elif isinstance(default_val, int):
                    val = int(env_val)
                elif isinstance(default_val, float):
                    val = float(env_val)
                else:
                    val = env_val
                
                # Audit log for environment override
                if val != default_val:
                    logger.info(f"[CONFIG] Overriding {key}: default={default_val}, env={val}")
            except (ValueError, TypeError):
                logger.warning(f"[CONFIG] Invalid value for {key} in environment: '{env_val}'. Using default: {default_val}")
                val = default_val
        
        # Cache the result
        cls._config_cache[key] = val
        return val

    @classmethod
    def reset_cache(cls):
        """Reset the configuration cache (mainly for testing)."""
        cls._config_cache = {}

# Shortcut instance (though classmethods are also fine)
config = ConfigManager()
