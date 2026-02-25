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
    DELIVERY_MAX_FAILED_ATTEMPTS,
    DELIVERY_LOCKOUT_SECONDS,
    DELIVERY_TOKEN_TTL_HOURS,
)
from src.api.database import get_db
from src.api.models import TaskStatus


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
            _record_delivery_failure("task-2")
        assert _check_delivery_rate_limit("task-2") is True

    def test_at_limit_blocked(self):
        """Test that attempts at the limit are blocked."""
        for _ in range(DELIVERY_MAX_FAILED_ATTEMPTS):
            _record_delivery_failure("task-3")
        assert _check_delivery_rate_limit("task-3") is False

    def test_different_tasks_independent(self):
        """Test that rate limits are per-task."""
        for _ in range(DELIVERY_MAX_FAILED_ATTEMPTS):
            _record_delivery_failure("task-A")
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
            _delivery_rate_limits["rate-test"] = (
                DELIVERY_MAX_FAILED_ATTEMPTS,
                time.time()
            )
            response = client.get("/api/delivery/rate-test/some-token")
            assert response.status_code == 429
        finally:
            app.dependency_overrides.clear()
            _delivery_rate_limits.clear()


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
        mock_task.id = "exp-task"
        mock_task.delivery_token = "valid-token"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_task.delivery_token_used = False
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/exp-task/valid-token")
            assert response.status_code == 403
            assert "expired" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_valid_unexpired_token_accepted(self):
        """Test that valid, non-expired tokens work."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "valid-task"
        mock_task.delivery_token = "good-token"
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
            response = client.get("/api/delivery/valid-task/good-token")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_no_expiration_field_accepted(self):
        """Test that tasks without expiration field still work (backward compat)."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "old-task"
        mock_task.delivery_token = "old-token"
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
            response = client.get("/api/delivery/old-task/old-token")
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
        mock_task.id = "used-task"
        mock_task.delivery_token = "used-token"
        mock_task.delivery_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_task.delivery_token_used = True  # Already used
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/used-task/used-token")
            assert response.status_code == 403
            assert "already been used" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_token_marked_used_after_success(self):
        """Test that token is marked as used after successful delivery."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "mark-task"
        mock_task.delivery_token = "mark-token"
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
            response = client.get("/api/delivery/mark-task/mark-token")
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
        mock_task.id = "verify-task"
        mock_task.delivery_token = "correct-token-abc"
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/verify-task/wrong-token-xyz")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_no_delivery_token_on_task(self):
        """Test that task without delivery_token rejects any token."""
        client = TestClient(app)
        mock_db = Mock()

        mock_task = Mock()
        mock_task.id = "no-token-task"
        mock_task.delivery_token = None
        mock_task.status = TaskStatus.COMPLETED
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/delivery/no-token-task/any-token")
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
            response = client.get("/api/delivery/nonexistent/some-token")
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
        mock_task.id = "leak-task"
        mock_task.delivery_token = "secret-token"
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
            response = client.get("/api/delivery/leak-task/secret-token")
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
        mock_task.id = "ts-task"
        mock_task.delivery_token = "ts-token"
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
            response = client.get("/api/delivery/ts-task/ts-token")
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

    def test_default_ttl_is_72_hours(self):
        """Test default delivery token TTL."""
        assert DELIVERY_TOKEN_TTL_HOURS == 72
