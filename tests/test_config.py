"""
Tests for configuration validation and environment variable management.

Issue #27: Configuration audit and validation
"""

import os
import pytest
from src.config import (
    validate_critical_env_vars,
    get_all_configured_env_vars,
    validate_urls,
    get_redis_url,
    get_database_url,
    get_openai_api_key,
    get_log_level,
    get_max_bid_amount,
    get_min_bid_amount,
    is_debug,
    should_use_redis_locks,
)


class TestValidationCriticalEnvVars:
    """Test critical environment variable validation."""

    def test_missing_api_key_fails(self, monkeypatch):
        """API_KEY and OPENAI_API_KEY missing should raise ValueError."""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="LLM API key not configured"):
            validate_critical_env_vars()

    def test_api_key_provided_passes(self, monkeypatch):
        """API_KEY being set should pass validation."""
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("ENV", "development")

        # Should not raise
        validate_critical_env_vars()

    def test_openai_api_key_provided_passes(self, monkeypatch):
        """OPENAI_API_KEY being set should pass validation."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
        monkeypatch.setenv("ENV", "development")

        # Should not raise
        validate_critical_env_vars()

    def test_production_requires_stripe_keys(self, monkeypatch):
        """Production mode requires STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY not set"):
            validate_critical_env_vars()

    def test_production_with_stripe_keys_passes(self, monkeypatch):
        """Production with STRIPE keys should pass."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/tasks.db")

        # Should not raise
        validate_critical_env_vars()

    def test_invalid_log_level_fails(self, monkeypatch):
        """Invalid LOG_LEVEL should raise ValueError."""
        monkeypatch.setenv("LOG_LEVEL", "INVALID_LEVEL")
        monkeypatch.setenv("API_KEY", "test-key")

        with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
            validate_critical_env_vars()

    def test_invalid_delivery_token_ttl_fails(self, monkeypatch):
        """Invalid DELIVERY_TOKEN_TTL_HOURS should raise ValueError."""
        monkeypatch.setenv("DELIVERY_TOKEN_TTL_HOURS", "not_an_int")
        monkeypatch.setenv("API_KEY", "test-key")

        with pytest.raises(ValueError, match="Invalid delivery token configuration"):
            validate_critical_env_vars()

    def test_invalid_bid_amounts_fails(self, monkeypatch):
        """MIN_BID_AMOUNT > MAX_BID_AMOUNT should raise ValueError."""
        monkeypatch.setenv("MIN_BID_AMOUNT", "50000")
        monkeypatch.setenv("MAX_BID_AMOUNT", "1000")
        monkeypatch.setenv("API_KEY", "test-key")

        with pytest.raises(ValueError, match="MIN_BID_AMOUNT.*MAX_BID_AMOUNT"):
            validate_critical_env_vars()

    def test_invalid_boolean_flag_fails(self, monkeypatch):
        """Invalid boolean flag should raise ValueError."""
        monkeypatch.setenv("USE_DOCKER_SANDBOX", "maybe")
        monkeypatch.setenv("API_KEY", "test-key")

        with pytest.raises(ValueError, match="Invalid boolean value"):
            validate_critical_env_vars()

    def test_insecure_client_secret_in_production_fails(self, monkeypatch):
        """Insecure default CLIENT_AUTH_SECRET in production should fail."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/tasks.db")
        monkeypatch.setenv(
            "CLIENT_AUTH_SECRET", "CHANGE_ME_IN_PRODUCTION_use_a_random_32_byte_key"
        )

        with pytest.raises(ValueError, match="CLIENT_AUTH_SECRET using insecure"):
            validate_critical_env_vars()


class TestGetAllConfiguredEnvVars:
    """Test retrieval of all configured environment variables."""

    def test_returns_dictionary(self):
        """Should return a dictionary of all known environment variables."""
        result = get_all_configured_env_vars()

        assert isinstance(result, dict)
        assert len(result) > 20  # Should have many variables

    def test_includes_all_major_categories(self):
        """Should include variables from all major categories."""
        result = get_all_configured_env_vars()

        # Check for key variables from each category
        assert "DATABASE_URL" in result  # Database
        assert "API_KEY" in result  # LLM
        assert "REDIS_URL" in result  # Redis
        assert "STRIPE_SECRET_KEY" in result  # Payment
        assert "DELIVERY_TOKEN_TTL_HOURS" in result  # Delivery
        assert "TELEGRAM_BOT_TOKEN" in result  # Notifications
        assert "LOG_LEVEL" in result  # Observability

    def test_masks_secrets(self, monkeypatch):
        """Secret variables should be masked in output."""
        monkeypatch.setenv("API_KEY", "sk_test_1234567890abcdef")
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_1234567890abcdef")

        result = get_all_configured_env_vars()

        # Check that secrets are masked
        assert result["API_KEY"].startswith("***")
        assert result["STRIPE_SECRET_KEY"].startswith("***")

    def test_shows_default_values(self):
        """Should show default values for unconfigured variables."""
        result = get_all_configured_env_vars()

        # These should have defaults
        assert result["LOG_LEVEL"] == "INFO"
        assert result["ENV"] == "development"
        assert result["DEBUG"] == "false"

    def test_shows_not_set_for_optional_vars(self, monkeypatch):
        """Optional variables without defaults should show (not set)."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        result = get_all_configured_env_vars()

        assert result["TELEGRAM_BOT_TOKEN"] == "(not set)"


class TestDatabaseConfiguration:
    """Test database configuration."""

    def test_default_database_url(self):
        """Default DATABASE_URL should be SQLite."""
        url = get_database_url()
        assert url.startswith("sqlite://")

    def test_custom_database_url(self, monkeypatch):
        """Custom DATABASE_URL should be respected."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        url = get_database_url()
        assert url == "postgresql://user:pass@host/db"


class TestRedisConfiguration:
    """Test Redis configuration."""

    def test_redis_url_takes_priority(self, monkeypatch):
        """REDIS_URL should take priority over components."""
        monkeypatch.setenv("REDIS_URL", "redis://priority:6379/0")
        monkeypatch.setenv("REDIS_HOST", "other")
        monkeypatch.setenv("REDIS_PORT", "9999")

        url = get_redis_url()
        assert url == "redis://priority:6379/0"

    def test_redis_components_with_password(self, monkeypatch):
        """Redis components with password should build correct URL."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_HOST", "redis.example.com")
        monkeypatch.setenv("REDIS_PORT", "6379")
        monkeypatch.setenv("REDIS_DB", "0")
        monkeypatch.setenv("REDIS_PASSWORD", "mypassword")

        url = get_redis_url()
        assert url == "redis://:mypassword@redis.example.com:6379/0"

    def test_redis_components_without_password(self, monkeypatch):
        """Redis components without password should build correct URL."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_HOST", "localhost")
        monkeypatch.setenv("REDIS_PORT", "6379")
        monkeypatch.setenv("REDIS_DB", "0")
        monkeypatch.delenv("REDIS_PASSWORD", raising=False)

        url = get_redis_url()
        assert url == "redis://localhost:6379/0"


class TestBidAmountConfiguration:
    """Test bid amount configuration."""

    def test_default_bid_amounts(self, monkeypatch):
        """Default bid amounts should be correct."""
        # Clear env to test defaults
        monkeypatch.delenv("MIN_BID_AMOUNT", raising=False)
        monkeypatch.delenv("MAX_BID_AMOUNT", raising=False)
        
        min_bid = get_min_bid_amount()
        max_bid = get_max_bid_amount()

        assert min_bid == 1000  # $10
        assert max_bid == 50000  # $500

    def test_custom_bid_amounts(self, monkeypatch):
        """Custom bid amounts should be respected."""
        monkeypatch.setenv("MIN_BID_AMOUNT", "5000")
        monkeypatch.setenv("MAX_BID_AMOUNT", "100000")

        min_bid = get_min_bid_amount()
        max_bid = get_max_bid_amount()

        assert min_bid == 5000
        assert max_bid == 100000


class TestDebugAndLogging:
    """Test debug and logging configuration."""

    def test_debug_default_false(self):
        """Debug should default to false."""
        assert is_debug() is False

    def test_debug_true_variants(self, monkeypatch):
        """Debug true variants should work."""
        for value in ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]:
            monkeypatch.setenv("DEBUG", value)
            assert is_debug() is True

    def test_debug_false_variants(self, monkeypatch):
        """Debug false variants should work."""
        for value in ["false", "False", "FALSE", "0", "no", "No", "NO"]:
            monkeypatch.setenv("DEBUG", value)
            assert is_debug() is False

    def test_log_level_default(self):
        """Log level should default to INFO."""
        level = get_log_level()
        assert level == "INFO"

    def test_custom_log_level(self, monkeypatch):
        """Custom log level should be respected."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        level = get_log_level()
        assert level == "DEBUG"


class TestURLValidation:
    """Test URL validation."""

    def test_valid_urls_pass(self, monkeypatch):
        """Valid URLs should pass validation."""
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("TRACELOOP_URL", "http://localhost:6006/v1/traces")
        monkeypatch.setenv("TELEGRAM_API_URL", "https://api.telegram.org")

        # Should not raise
        validate_urls()

    def test_invalid_url_fails(self, monkeypatch):
        """Invalid URL format should raise ValueError."""
        monkeypatch.setenv("OLLAMA_URL", "not-a-valid-url")

        with pytest.raises(ValueError, match="OLLAMA_URL.*invalid"):
            validate_urls()

    def test_empty_url_fails(self, monkeypatch):
        """Empty URL should raise ValueError."""
        monkeypatch.setenv("OLLAMA_URL", "")

        with pytest.raises(ValueError, match="OLLAMA_URL is not configured"):
            validate_urls()


class TestRedisLocksDecision:
    """Test Redis locks configuration decision logic."""

    def test_explicit_true_override(self, monkeypatch):
        """Explicit USE_REDIS_LOCKS=true should enable locks."""
        monkeypatch.setenv("USE_REDIS_LOCKS", "true")
        assert should_use_redis_locks() is True

    def test_explicit_false_override(self, monkeypatch):
        """Explicit USE_REDIS_LOCKS=false should disable locks."""
        monkeypatch.setenv("USE_REDIS_LOCKS", "false")
        assert should_use_redis_locks() is False

    def test_redis_url_available(self, monkeypatch):
        """REDIS_URL availability should enable locks."""
        monkeypatch.delenv("USE_REDIS_LOCKS", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        assert should_use_redis_locks() is True

    def test_redis_host_available(self, monkeypatch):
        """REDIS_HOST availability should enable locks."""
        monkeypatch.delenv("USE_REDIS_LOCKS", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_HOST", "redis.example.com")
        assert should_use_redis_locks() is True

    def test_development_default_false(self, monkeypatch):
        """Development environment should default to not using locks."""
        monkeypatch.delenv("USE_REDIS_LOCKS", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        monkeypatch.setenv("ENV", "development")
        assert should_use_redis_locks() is False

    def test_production_default_true(self, monkeypatch):
        """Production environment should default to using locks."""
        monkeypatch.delenv("USE_REDIS_LOCKS", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        monkeypatch.setenv("ENV", "production")
        assert should_use_redis_locks() is True


class TestOpenAIApiKey:
    """Test OpenAI API key configuration."""

    def test_api_key_preferred(self, monkeypatch):
        """API_KEY should be preferred over OPENAI_API_KEY."""
        monkeypatch.setenv("API_KEY", "key1")
        monkeypatch.setenv("OPENAI_API_KEY", "key2")

        key = get_openai_api_key()
        assert key == "key1"

    def test_openai_api_key_fallback(self, monkeypatch):
        """OPENAI_API_KEY should work as fallback."""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key2")

        key = get_openai_api_key()
        assert key == "key2"

    def test_missing_key_raises(self, monkeypatch):
        """Missing API key should raise ValueError."""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="API_KEY or OPENAI_API_KEY"):
            get_openai_api_key()
