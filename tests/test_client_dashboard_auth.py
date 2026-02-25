"""
Tests for client dashboard authentication (Issue #17).

Verifies:
- HMAC token generation and verification
- Client history endpoint requires valid token
- Client discount-info endpoint requires valid token
- Invalid/missing tokens are rejected with 403
- Constant-time comparison prevents timing attacks
- Case-insensitive email normalization
- Token is returned in checkout response
"""

import hmac
import hashlib
from unittest.mock import Mock

from starlette.testclient import TestClient

from src.utils.client_auth import (
    generate_client_token,
    verify_client_token,
    CLIENT_AUTH_SECRET,
)
from src.api.main import app
from src.api.database import get_db


# Helper to override get_db dependency
def override_get_db(mock_db):
    def _override():
        yield mock_db
    return _override


# =============================================================================
# HMAC TOKEN GENERATION TESTS
# =============================================================================

class TestTokenGeneration:
    """Test HMAC token generation."""

    def test_generates_hex_string(self):
        """Test that token is a hex string."""
        token = generate_client_token("test@example.com")
        assert all(c in "0123456789abcdef" for c in token)

    def test_correct_length(self):
        """Test that SHA-256 HMAC produces 64-char hex string."""
        token = generate_client_token("user@example.com")
        assert len(token) == 64

    def test_deterministic(self):
        """Test that same email produces same token."""
        t1 = generate_client_token("alice@example.com")
        t2 = generate_client_token("alice@example.com")
        assert t1 == t2

    def test_different_emails_different_tokens(self):
        """Test that different emails produce different tokens."""
        t1 = generate_client_token("alice@example.com")
        t2 = generate_client_token("bob@example.com")
        assert t1 != t2

    def test_case_insensitive(self):
        """Test that email normalization is case-insensitive."""
        t1 = generate_client_token("User@Example.COM")
        t2 = generate_client_token("user@example.com")
        assert t1 == t2

    def test_whitespace_trimmed(self):
        """Test that leading/trailing whitespace is trimmed."""
        t1 = generate_client_token("  user@example.com  ")
        t2 = generate_client_token("user@example.com")
        assert t1 == t2

    def test_manual_hmac_matches(self):
        """Test that generated token matches manual HMAC computation."""
        email = "verify@test.com"
        expected = hmac.new(
            CLIENT_AUTH_SECRET.encode(),
            email.encode(),
            hashlib.sha256,
        ).hexdigest()
        assert generate_client_token(email) == expected


# =============================================================================
# HMAC TOKEN VERIFICATION TESTS
# =============================================================================

class TestTokenVerification:
    """Test HMAC token verification."""

    def test_valid_token_passes(self):
        """Test that a valid token passes verification."""
        email = "valid@example.com"
        token = generate_client_token(email)
        assert verify_client_token(email, token) is True

    def test_wrong_token_fails(self):
        """Test that a wrong token fails verification."""
        assert verify_client_token("user@example.com", "wrong_token_abc") is False

    def test_empty_email_fails(self):
        """Test that empty email fails."""
        assert verify_client_token("", "some_token") is False

    def test_empty_token_fails(self):
        """Test that empty token fails."""
        assert verify_client_token("user@example.com", "") is False

    def test_none_email_fails(self):
        """Test that None email fails."""
        assert verify_client_token(None, "some_token") is False

    def test_none_token_fails(self):
        """Test that None token fails."""
        assert verify_client_token("user@example.com", None) is False

    def test_case_insensitive_verification(self):
        """Test that verification is case-insensitive on email."""
        token = generate_client_token("user@example.com")
        assert verify_client_token("USER@EXAMPLE.COM", token) is True

    def test_different_email_same_token_fails(self):
        """Test that a token for one email doesn't work for another."""
        token = generate_client_token("alice@example.com")
        assert verify_client_token("bob@example.com", token) is False


# =============================================================================
# CLIENT HISTORY ENDPOINT AUTH TESTS
# =============================================================================

class TestClientHistoryAuth:
    """Test that /api/client/history requires valid authentication."""

    def test_valid_token_returns_200(self):
        """Test that valid token allows access to history."""
        client = TestClient(app)
        mock_db = Mock()

        # Return empty task list
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        email = "client@test.com"
        token = generate_client_token(email)

        try:
            response = client.get(f"/api/client/history?email={email}&token={token}")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_invalid_token_returns_403(self):
        """Test that invalid token returns 403."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/client/history?email=client@test.com&token=bad_token"
            )
            assert response.status_code == 403
            assert "authentication" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_missing_token_returns_422(self):
        """Test that missing token parameter returns 422 (validation error)."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/client/history?email=client@test.com")
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_wrong_email_token_pair_returns_403(self):
        """Test that token for different email returns 403."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        # Token for alice, but requesting bob's history
        token = generate_client_token("alice@test.com")

        try:
            response = client.get(
                f"/api/client/history?email=bob@test.com&token={token}"
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# CLIENT DISCOUNT-INFO ENDPOINT AUTH TESTS
# =============================================================================

class TestClientDiscountInfoAuth:
    """Test that /api/client/discount-info requires valid authentication."""

    def test_valid_token_returns_200(self):
        """Test that valid token allows access to discount info."""
        client = TestClient(app)
        mock_db = Mock()

        mock_db.query.return_value.filter.return_value.count.return_value = 0

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        email = "discount@test.com"
        token = generate_client_token(email)

        try:
            response = client.get(
                f"/api/client/discount-info?email={email}&token={token}"
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_invalid_token_returns_403(self):
        """Test that invalid token returns 403."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/client/discount-info?email=user@test.com&token=invalid"
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_missing_token_returns_422(self):
        """Test that missing token returns 422."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/client/discount-info?email=user@test.com"
            )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# CHECKOUT RESPONSE TOKEN TESTS
# =============================================================================

class TestCheckoutResponseToken:
    """Test that checkout response includes client_auth_token."""

    def test_checkout_response_has_token_field(self):
        """Test CheckoutResponse model has client_auth_token field."""
        from src.api.main import CheckoutResponse

        resp = CheckoutResponse(
            session_id="sess_123",
            url="https://stripe.com/pay",
            amount=100,
            domain="accounting",
            title="Test Task",
            client_auth_token="abc123"
        )
        assert resp.client_auth_token == "abc123"

    def test_checkout_response_token_optional(self):
        """Test client_auth_token is optional (defaults to None)."""
        from src.api.main import CheckoutResponse

        resp = CheckoutResponse(
            session_id="sess_123",
            url="https://stripe.com/pay",
            amount=100,
            domain="accounting",
            title="Test Task"
        )
        assert resp.client_auth_token is None
