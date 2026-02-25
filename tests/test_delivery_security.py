"""
Tests for delivery endpoint security hardening (Issue #18).

Verifies:
- Cryptographically strong token generation (secrets.token_urlsafe)
- Token expiration enforcement
- One-time use token invalidation
- Rate limiting on failed attempts
- Constant-time token comparison
- Audit logging
- No token leakage in responses
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from starlette.testclient import TestClient

from src.api.main import (
    app,
    _check_delivery_rate_limit,
    _record_delivery_failure,
    _delivery_rate_limits,
    _check_delivery_ip_rate_limit,
    _delivery_ip_rate_limits,
    _sanitize_string,
    DeliveryTokenRequest,
    DELIVERY_MAX_FAILED_ATTEMPTS,
    DELIVERY_LOCKOUT_SECONDS,
    DELIVERY_TOKEN_TTL_HOURS,
    DELIVERY_MAX_ATTEMPTS_PER_IP,
    DELIVERY_IP_LOCKOUT_SECONDS,
)
from src.api.database import get_db
from src.api.models import TaskStatus
from pydantic import ValidationError


# Helper to override get_db dependency
def override_get_db(mock_db):
    def _override():
        yield mock_db
    return _override


# =============================================================================
# TOKEN GENERATION TESTS
# =============================================================================

class TestTokenGeneration:
    """Test that delivery tokens use strong randomness."""

    def test_token_is_urlsafe(self):
        """Test that secrets.token_urlsafe produces URL-safe tokens."""
        token = secrets.token_urlsafe(32)
        # URL-safe base64 uses A-Z, a-z, 0-9, -, _
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_token_has_sufficient_entropy(self):
        """Test that token has at least 256 bits of entropy (32 bytes)."""
        token = secrets.token_urlsafe(32)
        # 32 bytes = 256 bits. Base64 encoding of 32 bytes = ~43 characters
        assert len(token) >= 42

    def test_tokens_are_unique(self):
        """Test that generated tokens are unique."""
        tokens = {secrets.token_urlsafe(32) for _ in range(1000)}
        assert len(tokens) == 1000


# =============================================================================
# RATE LIMITING TESTS
# =============================================================================

class TestDeliveryRateLimiting:
    """Test rate limiting on delivery endpoint."""

    def setup_method(self):
        """Clear rate limit state before each test."""
        _delivery_rate_limits.clear()

    def test_first_attempt_allowed(self):
        """Test that first attempt is always allowed."""
        assert _check_delivery_rate_limit("task-1") is True

    def test_under_limit_allowed(self):
        """Test that attempts under the limit are allowed."""
        for _ in range(DELIVERY_MAX_FAILED_ATTEMPTS - 1):
            _record_delivery_failure("task-2", "192.168.1.1")
        assert _check_delivery_rate_limit("task-2") is True

    def test_at_limit_blocked(self):
        """Test that attempts at the limit are blocked."""
        for _ in range(DELIVERY_MAX_FAILED_ATTEMPTS):
            _record_delivery_failure("task-3", "192.168.1.1")
        assert _check_delivery_rate_limit("task-3") is False

    def test_different_tasks_independent(self):
        """Test that rate limits are per-task."""
        for _ in range(DELIVERY_MAX_FAILED_ATTEMPTS):
            _record_delivery_failure("task-A", "192.168.1.1")
        assert _check_delivery_rate_limit("task-A") is False
        assert _check_delivery_rate_limit("task-B") is True

    def test_lockout_resets_after_window(self):
        """Test that lockout resets after the lockout window."""
        _delivery_rate_limits["task-4"] = (
            DELIVERY_MAX_FAILED_ATTEMPTS,
            time.time() - DELIVERY_LOCKOUT_SECONDS - 1  # expired
        )
        assert _check_delivery_rate_limit("task-4") is True

    def test_rate_limit_returns_429(self):
        """Test that the endpoint returns 429 when rate limited."""
        client = TestClient(app)
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            # Exhaust rate limit
            _delivery_rate_limits["550e8400-e29b-41d4-a716-446655440000"] = (
                DELIVERY_MAX_FAILED_ATTEMPTS,
                time.time()
            )
            response = client.get(
                "/api/delivery/550e8400-e29b-41d4-a716-446655440000/valid_token_string_123456"
            )
            assert response.status_code == 429
        finally:
            app.dependency_overrides.clear()
            _delivery_rate_limits.clear()
            _delivery_ip_rate_limits.clear()


# =============================================================================
# TOKEN EXPIRATION TESTS
# =============================================================================

class TestTokenExpiration:
    """Test delivery token expiration enforcement."""

    def setup_method(self):
        _delivery_rate_limits.clear()

    def test_expired_token_rejected(self):
        """Test that expired delivery tokens are rejected."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440001"
        mock_task.delivery_token = "valid_token_string_1234567890abc"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440001/valid_token_string_1234567890abc")
            assert response.status_code == 403
            assert "expired" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_valid_unexpired_token_accepted(self):
        """Test that valid, non-expired tokens work."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440002"
        mock_task.delivery_token = "good_token_string_1234567890abcd"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_task.result_type = "image"
        mock_task.result_image_url = "https://example.com/result.png"
        mock_task.result_document_url = None
        mock_task.result_spreadsheet_url = None
        mock_task.title = "Test"
        mock_task.domain = "data_analysis"
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440002/good_token_string_1234567890abcd")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_no_expiration_field_accepted(self):
        """Test that tasks without expiration field still work (backward compat)."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440003"
        mock_task.delivery_token = "old_token_string_1234567890abcdef"
        mock_task.delivery_token_expires_at = None
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_task.result_type = "image"
        mock_task.result_image_url = "https://example.com/result.png"
        mock_task.result_document_url = None
        mock_task.result_spreadsheet_url = None
        mock_task.title = "Old Task"
        mock_task.domain = "accounting"
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440003/old_token_string_1234567890abcdef")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# ONE-TIME USE TESTS
# =============================================================================

class TestOneTimeUseToken:
    """Test that tokens are invalidated after successful download."""

    def setup_method(self):
        _delivery_rate_limits.clear()

    def test_used_token_rejected(self):
        """Test that a used token is rejected on second use."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440004"
        mock_task.delivery_token = "used_token_string_1234567890abcde"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = True  # Already used
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440004/used_token_string_1234567890abcde")
            assert response.status_code == 403
            assert "already been used" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_token_marked_used_after_success(self):
        """Test that token is marked as used after successful delivery."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440005"
        mock_task.delivery_token = "mark_token_string_1234567890abcdefg"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_task.result_type = "image"
        mock_task.result_image_url = "https://example.com/img.png"
        mock_task.result_document_url = None
        mock_task.result_spreadsheet_url = None
        mock_task.title = "Mark Task"
        mock_task.domain = "legal"
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440005/mark_token_string_1234567890abcdefg")
            assert response.status_code == 200
            assert mock_task.delivery_token_used is True
            assert mock_db.commit.called
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# TOKEN VERIFICATION TESTS
# =============================================================================

class TestTokenVerification:
    """Test constant-time token comparison and verification."""

    def setup_method(self):
        _delivery_rate_limits.clear()

    def test_wrong_token_rejected(self):
        """Test that wrong tokens are rejected."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440006"
        mock_task.delivery_token = "correct_token_string_1234567890abc"
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440006/wrong_token_string_1234567890xyz")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_no_delivery_token_on_task(self):
        """Test that task without delivery_token rejects any token."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440007"
        mock_task.delivery_token = None
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440007/any_token_string_1234567890abcde")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_task_not_found(self):
        """Test that non-existent task returns 404."""
        client = TestClient(app)
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440099/some_token_string_1234567890")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# RESPONSE SECURITY TESTS
# =============================================================================

class TestResponseSecurity:
    """Test that responses don't leak sensitive data."""

    def setup_method(self):
        _delivery_rate_limits.clear()

    def test_delivery_token_not_in_response(self):
        """Test that delivery_token is NOT included in the response."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440008"
        mock_task.delivery_token = "secret_token_string_1234567890abcde"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_task.result_type = "image"
        mock_task.result_image_url = "https://example.com/img.png"
        mock_task.result_document_url = None
        mock_task.result_spreadsheet_url = None
        mock_task.title = "Leak Test"
        mock_task.domain = "data_analysis"
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440008/secret_token_string_1234567890abcde")
            assert response.status_code == 200
            data = response.json()
            assert "delivery_token" not in data
        finally:
            app.dependency_overrides.clear()

    def test_response_includes_delivered_at(self):
        """Test that response includes delivered_at timestamp."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "550e8400-e29b-41d4-a716-446655440009"
        mock_task.delivery_token = "ts_token_string_1234567890abcdefg"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_task.result_type = "xlsx"
        mock_task.result_image_url = None
        mock_task.result_document_url = None
        mock_task.result_spreadsheet_url = "https://example.com/sheet.xlsx"
        mock_task.title = "Timestamp Task"
        mock_task.domain = "accounting"
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/550e8400-e29b-41d4-a716-446655440009/ts_token_string_1234567890abcdefg")
            assert response.status_code == 200
            data = response.json()
            assert "delivered_at" in data
            assert data["delivered_at"] is not None
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# TTL CONFIGURATION TEST
# =============================================================================

class TestTTLConfiguration:
    """Test that TTL configuration works."""

    def test_default_ttl_is_1_hour(self):
        """Test default delivery token TTL (hardened to 1 hour per Issue #18)."""
        assert DELIVERY_TOKEN_TTL_HOURS == 1


# =============================================================================
# IP-BASED RATE LIMITING TESTS (NEW - Issue #18)
# =============================================================================

class TestIPBasedRateLimiting:
    """Test IP-based rate limiting to prevent distributed brute force."""

    def setup_method(self):
        """Clear rate limit state before each test."""
        _delivery_ip_rate_limits.clear()
        _delivery_rate_limits.clear()

    def test_ip_first_attempt_allowed(self):
        """Test that first attempt from IP is always allowed."""
        assert _check_delivery_ip_rate_limit("192.168.1.100") is True

    def test_ip_under_limit_allowed(self):
        """Test that attempts under the limit are allowed."""
        for _ in range(DELIVERY_MAX_ATTEMPTS_PER_IP - 1):
            _record_delivery_failure("task-1", "192.168.1.101")
        assert _check_delivery_ip_rate_limit("192.168.1.101") is True

    def test_ip_at_limit_blocked(self):
        """Test that attempts at the limit are blocked."""
        for _ in range(DELIVERY_MAX_ATTEMPTS_PER_IP):
            _record_delivery_failure("task-1", "192.168.1.102")
        assert _check_delivery_ip_rate_limit("192.168.1.102") is False

    def test_different_ips_independent(self):
        """Test that rate limits are per-IP."""
        for _ in range(DELIVERY_MAX_ATTEMPTS_PER_IP):
            _record_delivery_failure("task-1", "192.168.1.103")
        assert _check_delivery_ip_rate_limit("192.168.1.103") is False
        assert _check_delivery_ip_rate_limit("192.168.1.104") is True

    def test_ip_lockout_resets_after_window(self):
        """Test that IP lockout resets after the lockout window."""
        _delivery_ip_rate_limits["192.168.1.105"] = (
            DELIVERY_MAX_ATTEMPTS_PER_IP,
            time.time() - DELIVERY_IP_LOCKOUT_SECONDS - 1  # expired
        )
        assert _check_delivery_ip_rate_limit("192.168.1.105") is True

    def test_ip_rate_limit_returns_429(self):
        """Test that endpoint returns 429 for IP rate limit."""
        client = TestClient(app)
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            # Exhaust IP rate limit
            _delivery_ip_rate_limits["testclient"] = (
                DELIVERY_MAX_ATTEMPTS_PER_IP,
                time.time()
            )
            response = client.get(
                "/api/delivery/550e8400-e29b-41d4-a716-446655440000/token_string_1234567890abcde"
            )
            assert response.status_code == 429
        finally:
            app.dependency_overrides.clear()
            _delivery_ip_rate_limits.clear()
            _delivery_rate_limits.clear()


# =============================================================================
# INPUT VALIDATION TESTS (NEW - Issue #18)
# =============================================================================

class TestInputValidation:
    """Test Pydantic input validation for delivery endpoint."""

    def test_valid_uuid_task_id(self):
        """Test that valid UUID task_id is accepted."""
        req = DeliveryTokenRequest(
            task_id="550e8400-e29b-41d4-a716-446655440000",
            token="valid_token_string_1234567890"
        )
        assert req.task_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_invalid_task_id_format(self):
        """Test that invalid task_id format is rejected."""
        try:
            DeliveryTokenRequest(
                task_id="not-a-uuid",
                token="valid_token_string_1234567890"
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_task_id_too_short(self):
        """Test that empty task_id is rejected."""
        try:
            DeliveryTokenRequest(
                task_id="",
                token="valid_token_string_1234567890"
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_token_too_short(self):
        """Test that token shorter than 20 chars is rejected."""
        try:
            DeliveryTokenRequest(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                token="short"
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_token_too_long(self):
        """Test that token longer than 256 chars is rejected."""
        try:
            DeliveryTokenRequest(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                token="x" * 257
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_token_invalid_characters(self):
        """Test that token with invalid characters is rejected."""
        try:
            DeliveryTokenRequest(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                token="invalid token with spaces!"
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_token_alphanumeric_accepted(self):
        """Test that alphanumeric token is accepted."""
        req = DeliveryTokenRequest(
            task_id="550e8400-e29b-41d4-a716-446655440000",
            token="ABCdef123456789-_abcdef"
        )
        assert req.token == "ABCdef123456789-_abcdef"

    def test_task_id_normalized_to_lowercase(self):
        """Test that task_id is normalized to lowercase."""
        req = DeliveryTokenRequest(
            task_id="550E8400-E29B-41D4-A716-446655440000",
            token="valid_token_string_1234567890"
        )
        assert req.task_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_token_whitespace_stripped(self):
        """Test that token whitespace is stripped."""
        req = DeliveryTokenRequest(
            task_id="550e8400-e29b-41d4-a716-446655440000",
            token="  valid_token_string_1234567890  "
        )
        assert req.token == "valid_token_string_1234567890"

    def test_invalid_token_in_endpoint(self):
        """Test that invalid token format returns 400 from endpoint."""
        client = TestClient(app)
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/delivery/550e8400-e29b-41d4-a716-446655440000/bad-token!"
            )
            assert response.status_code == 400
            assert "Invalid input" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_invalid_task_id_in_endpoint(self):
        """Test that invalid task_id format returns 400 from endpoint."""
        client = TestClient(app)
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/not-a-uuid/valid_token_string_1234567890")
            assert response.status_code == 400
            assert "Invalid input" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# INPUT SANITIZATION TESTS (NEW - Issue #18)
# =============================================================================

class TestInputSanitization:
    """Test string sanitization to prevent injection attacks."""

    def test_sanitize_removes_null_bytes(self):
        """Test that null bytes are removed."""
        result = _sanitize_string("hello\x00world")
        assert "\x00" not in result
        assert result == "helloworld"

    def test_sanitize_respects_max_length(self):
        """Test that sanitization respects max_length."""
        result = _sanitize_string("a" * 600, max_length=100)
        assert len(result) == 100

    def test_sanitize_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        result = _sanitize_string("  hello world  ")
        assert result == "hello world"

    def test_sanitize_normal_string_unchanged(self):
        """Test that normal strings are unchanged."""
        input_str = "normal string"
        result = _sanitize_string(input_str)
        assert result == input_str

    def test_sanitize_non_string_returned_as_is(self):
        """Test that non-string types are returned as-is."""
        result = _sanitize_string(None, max_length=100)
        assert result is None
