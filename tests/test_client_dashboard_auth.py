"""
Tests for client dashboard authentication and authorization.
Issue #17: Client portal security and access control.
"""

import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.main import app
from src.api.database import get_db
from src.api.models import Task, TaskStatus
from src.utils.client_auth import generate_client_token, verify_client_token


def override_get_db(mock_db):
    """Helper to override the get_db dependency."""
    def _override():
        yield mock_db
    return _override


class TestClientHistoryAuth:
    """Test authentication for the client history endpoint."""

    def test_valid_token_returns_200(self):
        """Test that a valid email/token pair returns 200 OK."""
        client = TestClient(app)
        mock_db = Mock()
        
        # Standard SQLAlchemy mock pattern
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        
        app.dependency_overrides[get_db] = override_get_db(mock_db)
        
        email = "client@test.com"
        token = generate_client_token(email)
        
        try:
            response = client.get(
                f"/api/client/history?email={email}&token={token}"
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
                "/api/client/history?email=client@test.com&token=bad_token"
            )
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_missing_parameters_returns_422(self):
        """Test that missing email or token returns validation error."""
        client = TestClient(app)
        
        # Missing token
        response = client.get("/api/client/history?email=test@test.com")
        assert response.status_code == 422
        
        # Missing email
        response = client.get("/api/client/history?token=some_token")
        assert response.status_code == 422

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


class TestClientDiscountInfoAuth:
    """Test authentication for the client discount info endpoint."""

    def test_valid_token_returns_200(self):
        """Test that a valid email/token pair returns 200 OK."""
        client = TestClient(app)
        mock_db = Mock()
        
        # Standard SQLAlchemy mock pattern
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_db.query.return_value = mock_query
        
        app.dependency_overrides[get_db] = override_get_db(mock_db)
        
        email = "user@test.com"
        token = generate_client_token(email)
        
        try:
            response = client.get(
                f"/api/client/discount-info?email={email}&token={token}"
            )
            assert response.status_code == 200
            data = response.json()
            assert "current_discount" in data
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


class TestOptionalClientAuthDependency:
    """Test endpoints using optional authentication."""

    def test_no_auth_parameters_returns_200(self):
        """Test that endpoint with optional auth works without credentials."""
        client = TestClient(app)
        mock_db = Mock()
        
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
        
        # Standard SQLAlchemy mock pattern
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_db.query.return_value = mock_query
        
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
