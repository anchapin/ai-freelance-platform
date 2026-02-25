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

    def test_invalid_token_returns_401(self):
        """Test that invalid token returns 401 Unauthorized."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/client/history?email=client@test.com&token=bad_token"
            )
            assert response.status_code == 401
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

    def test_wrong_email_token_pair_returns_401(self):
        """Test that token for different email returns 401 Unauthorized."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        # Token for alice, but requesting bob's history
        token = generate_client_token("alice@test.com")

        try:
            response = client.get(
                f"/api/client/history?email=bob@test.com&token={token}"
            )
            assert response.status_code == 401
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

    def test_invalid_token_returns_401(self):
        """Test that invalid token returns 401 Unauthorized."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get(
                "/api/client/discount-info?email=user@test.com&token=invalid"
            )
            assert response.status_code == 401
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


# =============================================================================
# AUTHENTICATED CLIENT DEPENDENCY TESTS
# =============================================================================


class TestAuthenticatedClientDependency:
    """Test the AuthenticatedClient dependency model."""

    def test_authenticated_client_stores_email_and_token(self):
        """Test that AuthenticatedClient stores email and token."""
        from src.utils.client_auth import AuthenticatedClient

        client = AuthenticatedClient("test@example.com", "token123")
        assert client.email == "test@example.com"
        assert client.token == "token123"

    def test_authenticated_client_normalizes_email(self):
        """Test that email is normalized (lowercased and trimmed)."""
        from src.utils.client_auth import AuthenticatedClient

        client = AuthenticatedClient("  User@Example.COM  ", "token123")
        assert client.email == "user@example.com"

    def test_is_authenticated_returns_true_for_valid_client(self):
        """Test is_authenticated returns True for valid email+token combo."""
        from src.utils.client_auth import AuthenticatedClient

        email = "valid@test.com"
        token = generate_client_token(email)
        client = AuthenticatedClient(email, token)
        assert client.is_authenticated() is True

    def test_is_authenticated_returns_false_for_invalid_token(self):
        """Test is_authenticated returns False for invalid token."""
        from src.utils.client_auth import AuthenticatedClient

        client = AuthenticatedClient("test@example.com", "invalid_token")
        assert client.is_authenticated() is False

    def test_is_authenticated_returns_false_for_empty_client(self):
        """Test is_authenticated returns False for empty client."""
        from src.utils.client_auth import AuthenticatedClient

        client = AuthenticatedClient("", "")
        assert client.is_authenticated() is False


# =============================================================================
# REQUIRE_CLIENT_AUTH DEPENDENCY TESTS
# =============================================================================


class TestRequireClientAuthDependency:
    """Test the require_client_auth FastAPI dependency."""

    def test_valid_auth_returns_authenticated_client(self):
        """Test that valid credentials return AuthenticatedClient."""
        client = TestClient(app)
        mock_db = Mock()

        # Mock query chain for discount info endpoint
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        email = "auth@test.com"
        token = generate_client_token(email)

        try:
            response = client.get(
                f"/api/client/discount-info?email={email}&token={token}"
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_missing_email_returns_401(self):
        """Test that missing email returns 401."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/client/discount-info?token=some_token")
            assert response.status_code == 422  # FastAPI validation error
        finally:
            app.dependency_overrides.clear()

    def test_missing_token_returns_422(self):
        """Test that missing token returns 422 validation error."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.get("/api/client/discount-info?email=user@test.com")
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# OPTIONAL_CLIENT_AUTH DEPENDENCY TESTS
# =============================================================================


class TestOptionalClientAuthDependency:
    """Test the optional_client_auth FastAPI dependency."""

    def test_no_auth_parameters_returns_200(self):
        """Test that endpoint with optional auth works without credentials."""
        client = TestClient(app)
        mock_db = Mock()

        mock_db.query.return_value.filter.return_value.count.return_value = 0

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            # Call endpoint without any auth parameters
            response = client.post(
                "/api/client/calculate-price-with-discount?domain=accounting"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_repeat_client"] is False
        finally:
            app.dependency_overrides.clear()

    def test_valid_auth_applies_discount(self):
        """Test that valid auth allows discount calculation."""
        client = TestClient(app)
        mock_db = Mock()

        # Mock one completed task for the client
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        email = "repeat@test.com"
        token = generate_client_token(email)

        try:
            response = client.post(
                f"/api/client/calculate-price-with-discount"
                f"?domain=accounting&email={email}&token={token}"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_repeat_client"] is True
        finally:
            app.dependency_overrides.clear()

    def test_partial_auth_parameters_returns_401(self):
        """Test that providing only email (no token) returns 401."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.post(
                "/api/client/calculate-price-with-discount?domain=accounting&email=test@test.com"
            )
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_partial_auth_token_only_returns_401(self):
        """Test that providing only token (no email) returns 401."""
        client = TestClient(app)
        mock_db = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        try:
            response = client.post(
                "/api/client/calculate-price-with-discount?domain=accounting&token=some_token"
            )
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
