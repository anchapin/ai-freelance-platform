"""
Tests for ConfigManager class.

Tests configuration loading, validation, type checking, and range validation.
"""

import os
import pytest
from src.config import ConfigManager, get_config, ValidationError


class TestConfigManagerLoading:
    """Test basic configuration loading."""

    def setup_method(self):
        """Reset singleton before each test."""
        ConfigManager.reset_instance()

    def teardown_method(self):
        """Clean up environment after each test."""
        ConfigManager.reset_instance()

    def test_config_loads_with_defaults(self):
        """Test that config loads successfully with default values."""
        config = get_config()
        assert config is not None
        assert config.MIN_CLOUD_REVENUE == 3000
        assert config.MAX_BID_AMOUNT == 500
        assert config.MIN_BID_AMOUNT == 10

    def test_config_singleton_behavior(self):
        """Test that ConfigManager follows singleton pattern."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_config_dictionary_conversion(self):
        """Test conversion of config to dictionary."""
        config = get_config()
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert "MIN_CLOUD_REVENUE" in config_dict
        assert "MAX_BID_AMOUNT" in config_dict
        assert "DOCKER_SANDBOX_TIMEOUT" in config_dict
        assert config_dict["MIN_CLOUD_REVENUE"] == 3000


class TestConfigManagerTypeValidation:
    """Test type validation for configuration values."""

    def setup_method(self):
        """Reset singleton before each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    def teardown_method(self):
        """Clean up environment after each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    @staticmethod
    def _cleanup_env_vars():
        """Clean up all config-related environment variables."""
        test_vars = [
            "MIN_CLOUD_REVENUE",
            "MAX_BID_AMOUNT",
            "MIN_BID_AMOUNT",
            "PAGE_LOAD_TIMEOUT",
            "SCAN_INTERVAL",
            "DOCKER_SANDBOX_TIMEOUT",
            "SANDBOX_TIMEOUT_SECONDS",
            "DELIVERY_TOKEN_TTL_HOURS",
            "DELIVERY_MAX_FAILED_ATTEMPTS",
            "DELIVERY_LOCKOUT_SECONDS",
            "DELIVERY_MAX_ATTEMPTS_PER_IP",
            "DELIVERY_IP_LOCKOUT_SECONDS",
            "BID_LOCK_MANAGER_TTL",
            "MAX_FILE_SIZE_BYTES",
            "MIN_EXAMPLES_FOR_TRAINING",
            "WEBHOOK_TIMESTAMP_WINDOW",
            "LLM_HEALTH_CHECK_HISTORY_SIZE",
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS",
            "LLM_HEALTH_CHECK_MAX_DELAY_MS",
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        ]
        for key in test_vars:
            if key in os.environ:
                del os.environ[key]

    def test_reject_non_numeric_values(self):
        """Test that non-numeric values are rejected."""
        os.environ["MIN_CLOUD_REVENUE"] = "not_a_number"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "Expected integer" in str(exc_info.value)

    def test_reject_float_string_values(self):
        """Test that float string values are rejected."""
        os.environ["MAX_BID_AMOUNT"] = "500.5"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "Expected integer" in str(exc_info.value)

    def test_accept_valid_numeric_strings(self):
        """Test that valid numeric strings are accepted."""
        os.environ["MIN_CLOUD_REVENUE"] = "5000"

        config = get_config()
        assert config.MIN_CLOUD_REVENUE == 5000

    def test_accept_negative_strings_for_negative_min_checks(self):
        """Test that negative values are rejected where min > 0."""
        os.environ["MIN_BID_AMOUNT"] = "-10"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "below minimum" in str(exc_info.value)


class TestConfigManagerRangeValidation:
    """Test range validation for configuration values."""

    def setup_method(self):
        """Reset singleton before each test."""
        ConfigManager.reset_instance()
        # Clean up any test env vars from previous tests
        self._cleanup_env_vars()

    def teardown_method(self):
        """Clean up environment after each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    @staticmethod
    def _cleanup_env_vars():
        """Clean up all config-related environment variables."""
        test_vars = [
            "MIN_CLOUD_REVENUE",
            "MAX_BID_AMOUNT",
            "MIN_BID_AMOUNT",
            "PAGE_LOAD_TIMEOUT",
            "SCAN_INTERVAL",
            "DOCKER_SANDBOX_TIMEOUT",
            "SANDBOX_TIMEOUT_SECONDS",
            "DELIVERY_TOKEN_TTL_HOURS",
            "DELIVERY_MAX_FAILED_ATTEMPTS",
            "DELIVERY_LOCKOUT_SECONDS",
            "DELIVERY_MAX_ATTEMPTS_PER_IP",
            "DELIVERY_IP_LOCKOUT_SECONDS",
            "BID_LOCK_MANAGER_TTL",
            "MAX_FILE_SIZE_BYTES",
            "MIN_EXAMPLES_FOR_TRAINING",
            "WEBHOOK_TIMESTAMP_WINDOW",
            "LLM_HEALTH_CHECK_HISTORY_SIZE",
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS",
            "LLM_HEALTH_CHECK_MAX_DELAY_MS",
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        ]
        for key in test_vars:
            if key in os.environ:
                del os.environ[key]

    def test_min_bid_cannot_exceed_max_bid(self):
        """Test that MIN_BID_AMOUNT cannot exceed MAX_BID_AMOUNT."""
        os.environ["MIN_BID_AMOUNT"] = "1000"
        os.environ["MAX_BID_AMOUNT"] = "500"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "cannot exceed" in str(exc_info.value)

    def test_docker_timeout_cannot_exceed_max_timeout(self):
        """Test that DOCKER_SANDBOX_TIMEOUT cannot exceed SANDBOX_TIMEOUT_SECONDS."""
        os.environ["DOCKER_SANDBOX_TIMEOUT"] = "700"
        os.environ["SANDBOX_TIMEOUT_SECONDS"] = "600"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "exceeds maximum" in str(exc_info.value) or "cannot exceed" in str(
            exc_info.value
        )

    def test_initial_delay_cannot_exceed_max_delay(self):
        """Test that initial delay cannot exceed max delay for health check."""
        os.environ["LLM_HEALTH_CHECK_INITIAL_DELAY_MS"] = "15000"
        os.environ["LLM_HEALTH_CHECK_MAX_DELAY_MS"] = "10000"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "exceeds maximum" in str(exc_info.value) or "cannot exceed" in str(
            exc_info.value
        )

    def test_page_load_timeout_below_min(self):
        """Test that PAGE_LOAD_TIMEOUT must be > 0."""
        os.environ["PAGE_LOAD_TIMEOUT"] = "0"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "below minimum" in str(exc_info.value)

    def test_page_load_timeout_above_max(self):
        """Test that PAGE_LOAD_TIMEOUT cannot exceed 300 seconds."""
        os.environ["PAGE_LOAD_TIMEOUT"] = "600"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "exceeds maximum" in str(exc_info.value)

    def test_delivery_lockout_below_min(self):
        """Test that DELIVERY_LOCKOUT_SECONDS must be > 0."""
        os.environ["DELIVERY_LOCKOUT_SECONDS"] = "0"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "below minimum" in str(exc_info.value)

    def test_delivery_lockout_above_max(self):
        """Test that DELIVERY_LOCKOUT_SECONDS cannot exceed 86400."""
        os.environ["DELIVERY_LOCKOUT_SECONDS"] = "100000"

        with pytest.raises(ValidationError) as exc_info:
            get_config()

        assert "exceeds maximum" in str(exc_info.value)

    def test_valid_range_values_accepted(self):
        """Test that values within valid range are accepted."""
        os.environ["PAGE_LOAD_TIMEOUT"] = "60"
        os.environ["DELIVERY_LOCKOUT_SECONDS"] = "7200"

        config = get_config()
        assert config.PAGE_LOAD_TIMEOUT == 60
        assert config.DELIVERY_LOCKOUT_SECONDS == 7200


class TestConfigManagerDefaultValues:
    """Test default values for configuration."""

    def setup_method(self):
        """Reset singleton before each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    def teardown_method(self):
        """Clean up environment after each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    @staticmethod
    def _cleanup_env_vars():
        """Clean up all config-related environment variables."""
        test_vars = [
            "MIN_CLOUD_REVENUE",
            "MAX_BID_AMOUNT",
            "MIN_BID_AMOUNT",
            "PAGE_LOAD_TIMEOUT",
            "SCAN_INTERVAL",
            "DOCKER_SANDBOX_TIMEOUT",
            "SANDBOX_TIMEOUT_SECONDS",
            "DELIVERY_TOKEN_TTL_HOURS",
            "DELIVERY_MAX_FAILED_ATTEMPTS",
            "DELIVERY_LOCKOUT_SECONDS",
            "DELIVERY_MAX_ATTEMPTS_PER_IP",
            "DELIVERY_IP_LOCKOUT_SECONDS",
            "BID_LOCK_MANAGER_TTL",
            "MAX_FILE_SIZE_BYTES",
            "MIN_EXAMPLES_FOR_TRAINING",
            "WEBHOOK_TIMESTAMP_WINDOW",
            "LLM_HEALTH_CHECK_HISTORY_SIZE",
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS",
            "LLM_HEALTH_CHECK_MAX_DELAY_MS",
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        ]
        for key in test_vars:
            if key in os.environ:
                del os.environ[key]

    def test_default_revenue_threshold(self):
        """Test default MIN_CLOUD_REVENUE."""
        config = get_config()
        assert config.MIN_CLOUD_REVENUE == 3000

    def test_default_high_value_threshold(self):
        """Test default HIGH_VALUE_THRESHOLD."""
        config = get_config()
        assert config.HIGH_VALUE_THRESHOLD == 200

    def test_default_bid_amounts(self):
        """Test default bid amounts."""
        config = get_config()
        assert config.MIN_BID_AMOUNT == 10
        assert config.MAX_BID_AMOUNT == 500

    def test_default_timeouts(self):
        """Test default timeout values."""
        config = get_config()
        assert config.PAGE_LOAD_TIMEOUT == 30
        assert config.SCAN_INTERVAL == 300
        assert config.DOCKER_SANDBOX_TIMEOUT == 120
        assert config.SANDBOX_TIMEOUT_SECONDS == 600

    def test_default_delivery_settings(self):
        """Test default delivery settings."""
        config = get_config()
        assert config.DELIVERY_TOKEN_TTL_HOURS == 1
        assert config.DELIVERY_MAX_FAILED_ATTEMPTS == 5
        assert config.DELIVERY_LOCKOUT_SECONDS == 3600
        assert config.DELIVERY_MAX_ATTEMPTS_PER_IP == 20
        assert config.DELIVERY_IP_LOCKOUT_SECONDS == 3600

    def test_default_lock_ttl(self):
        """Test default bid lock manager TTL."""
        config = get_config()
        assert config.BID_LOCK_MANAGER_TTL == 300

    def test_default_file_size(self):
        """Test default max file size."""
        config = get_config()
        assert config.MAX_FILE_SIZE_BYTES == 50 * 1024 * 1024

    def test_default_training_examples(self):
        """Test default min examples for training."""
        config = get_config()
        assert config.MIN_EXAMPLES_FOR_TRAINING == 500

    def test_default_webhook_window(self):
        """Test default webhook timestamp window."""
        config = get_config()
        assert config.WEBHOOK_TIMESTAMP_WINDOW == 300

    def test_default_health_check_settings(self):
        """Test default health check settings."""
        config = get_config()
        assert config.LLM_HEALTH_CHECK_HISTORY_SIZE == 100
        assert config.LLM_HEALTH_CHECK_INITIAL_DELAY_MS == 100
        assert config.LLM_HEALTH_CHECK_MAX_DELAY_MS == 10000


class TestConfigManagerCustomValues:
    """Test loading custom configuration from environment."""

    def setup_method(self):
        """Reset singleton before each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    def teardown_method(self):
        """Clean up environment after each test."""
        ConfigManager.reset_instance()
        self._cleanup_env_vars()

    @staticmethod
    def _cleanup_env_vars():
        """Clean up all config-related environment variables."""
        test_vars = [
            "MIN_CLOUD_REVENUE",
            "MAX_BID_AMOUNT",
            "MIN_BID_AMOUNT",
            "PAGE_LOAD_TIMEOUT",
            "SCAN_INTERVAL",
            "DOCKER_SANDBOX_TIMEOUT",
            "SANDBOX_TIMEOUT_SECONDS",
            "DELIVERY_TOKEN_TTL_HOURS",
            "DELIVERY_MAX_FAILED_ATTEMPTS",
            "DELIVERY_LOCKOUT_SECONDS",
            "DELIVERY_MAX_ATTEMPTS_PER_IP",
            "DELIVERY_IP_LOCKOUT_SECONDS",
            "BID_LOCK_MANAGER_TTL",
            "MAX_FILE_SIZE_BYTES",
            "MIN_EXAMPLES_FOR_TRAINING",
            "WEBHOOK_TIMESTAMP_WINDOW",
            "LLM_HEALTH_CHECK_HISTORY_SIZE",
            "LLM_HEALTH_CHECK_INITIAL_DELAY_MS",
            "LLM_HEALTH_CHECK_MAX_DELAY_MS",
            "URL_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        ]
        for key in test_vars:
            if key in os.environ:
                del os.environ[key]

    def test_override_cloud_revenue(self):
        """Test overriding MIN_CLOUD_REVENUE."""
        os.environ["MIN_CLOUD_REVENUE"] = "5000"

        config = get_config()
        assert config.MIN_CLOUD_REVENUE == 5000

    def test_override_high_value_threshold(self):
        """Test overriding HIGH_VALUE_THRESHOLD."""
        os.environ["HIGH_VALUE_THRESHOLD"] = "500"

        config = get_config()
        assert config.HIGH_VALUE_THRESHOLD == 500

    def test_override_bid_amounts(self):
        """Test overriding bid amounts."""
        os.environ["MIN_BID_AMOUNT"] = "50"
        os.environ["MAX_BID_AMOUNT"] = "2000"

        config = get_config()
        assert config.MIN_BID_AMOUNT == 50
        assert config.MAX_BID_AMOUNT == 2000

    def test_override_timeouts(self):
        """Test overriding timeout values."""
        os.environ["PAGE_LOAD_TIMEOUT"] = "60"
        os.environ["SCAN_INTERVAL"] = "600"
        os.environ["DOCKER_SANDBOX_TIMEOUT"] = "180"
        os.environ["SANDBOX_TIMEOUT_SECONDS"] = "900"

        config = get_config()
        assert config.PAGE_LOAD_TIMEOUT == 60
        assert config.SCAN_INTERVAL == 600
        assert config.DOCKER_SANDBOX_TIMEOUT == 180
        assert config.SANDBOX_TIMEOUT_SECONDS == 900

    def test_override_delivery_settings(self):
        """Test overriding delivery settings."""
        os.environ["DELIVERY_TOKEN_TTL_HOURS"] = "2"
        os.environ["DELIVERY_MAX_FAILED_ATTEMPTS"] = "10"
        os.environ["DELIVERY_LOCKOUT_SECONDS"] = "7200"
        os.environ["DELIVERY_MAX_ATTEMPTS_PER_IP"] = "50"
        os.environ["DELIVERY_IP_LOCKOUT_SECONDS"] = "7200"

        config = get_config()
        assert config.DELIVERY_TOKEN_TTL_HOURS == 2
        assert config.DELIVERY_MAX_FAILED_ATTEMPTS == 10
        assert config.DELIVERY_LOCKOUT_SECONDS == 7200
        assert config.DELIVERY_MAX_ATTEMPTS_PER_IP == 50
        assert config.DELIVERY_IP_LOCKOUT_SECONDS == 7200

    def test_override_health_check_settings(self):
        """Test overriding health check settings."""
        os.environ["LLM_HEALTH_CHECK_HISTORY_SIZE"] = "200"
        os.environ["LLM_HEALTH_CHECK_INITIAL_DELAY_MS"] = "200"
        os.environ["LLM_HEALTH_CHECK_MAX_DELAY_MS"] = "20000"

        config = get_config()
        assert config.LLM_HEALTH_CHECK_HISTORY_SIZE == 200
        assert config.LLM_HEALTH_CHECK_INITIAL_DELAY_MS == 200
        assert config.LLM_HEALTH_CHECK_MAX_DELAY_MS == 20000


class TestConfigManagerReset:
    """Test singleton reset functionality for testing."""

    def test_reset_instance(self):
        """Test that reset_instance works correctly."""
        config1 = get_config()
        os.environ["MIN_CLOUD_REVENUE"] = "10000"
        ConfigManager.reset_instance()
        config2 = get_config()

        assert config1 is not config2
        assert config2.MIN_CLOUD_REVENUE == 10000

    def teardown_method(self):
        """Clean up after test."""
        ConfigManager.reset_instance()
        if "MIN_CLOUD_REVENUE" in os.environ:
            del os.environ["MIN_CLOUD_REVENUE"]
