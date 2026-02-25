"""Configuration module for ArbitrageAI."""

# Import new ConfigManager
from .manager import (
    ConfigManager,
    get_config,
    ValidationError,
)

# Import legacy config functions from parent config.py
# These are kept for backward compatibility
import sys
import os

# Get the parent config module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import from legacy config.py (not this package)
import importlib.util
config_file = os.path.join(parent_dir, "config.py")
if os.path.exists(config_file):
    spec = importlib.util.spec_from_file_location("_config_legacy", config_file)
    _config_legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_config_legacy)
    
    # Re-export legacy functions
    get_redis_url = _config_legacy.get_redis_url
    get_database_url = _config_legacy.get_database_url
    get_ollama_url = _config_legacy.get_ollama_url
    get_traceloop_url = _config_legacy.get_traceloop_url
    get_telegram_api_url = _config_legacy.get_telegram_api_url
    get_openai_api_key = _config_legacy.get_openai_api_key
    get_stripe_secret_key = _config_legacy.get_stripe_secret_key
    get_stripe_webhook_secret = _config_legacy.get_stripe_webhook_secret
    get_log_level = _config_legacy.get_log_level
    get_max_bid_amount = _config_legacy.get_max_bid_amount
    get_min_bid_amount = _config_legacy.get_min_bid_amount
    validate_critical_env_vars = _config_legacy.validate_critical_env_vars
    validate_urls = _config_legacy.validate_urls
    get_all_configured_env_vars = _config_legacy.get_all_configured_env_vars
    is_debug = _config_legacy.is_debug
    should_use_redis_locks = _config_legacy.should_use_redis_locks

__all__ = [
    "ConfigManager",
    "get_config",
    "ValidationError",
    "get_redis_url",
    "get_database_url",
    "get_ollama_url",
    "get_traceloop_url",
    "get_telegram_api_url",
    "get_openai_api_key",
    "get_stripe_secret_key",
    "get_stripe_webhook_secret",
    "get_log_level",
    "get_max_bid_amount",
    "get_min_bid_amount",
    "validate_critical_env_vars",
    "validate_urls",
    "get_all_configured_env_vars",
    "is_debug",
    "should_use_redis_locks",
]
