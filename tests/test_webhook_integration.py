"""
Integration tests for webhook endpoint with enhanced security (Issue #35).
"""

import pytest
import json
import hmac
import hashlib
import time
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient


def override_get_db(mock_db):
    """Create a generator that yields the mock db."""
    def override():
        yield mock_db
    return override


class TestWebhookSignatureVerificationIntegration:
    """Integration tests for webhook signature verification."""

    def test_webhook_signature_verification_invalid_signature(self):
        """Test webhook rejects invalid signature (Issue #35)."""
        mock_event = {
            "id": "evt_test_456",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_456",
                    "payment_status": "paid",
                }
            }
        }

        from src.api.main import app
        from src.api.database import get_db

        client = TestClient(app)

        # Create mock database
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        # Use a real webhook secret
        test_secret = "whsec_test_123456789"
        payload = json.dumps(mock_event).encode('utf-8')

        # Create INVALID signature
        current_time = int(time.time())
        invalid_signature = f"t={current_time},v1=invalid_signature_hash"

        with patch('src.api.main.STRIPE_WEBHOOK_SECRET', test_secret):
            try:
                response = client.post(
                    "/api/webhook",
                    content=payload,
                    headers={"stripe-signature": invalid_signature}
                )

                # Verify rejection
                assert response.status_code == 400
                assert "Invalid webhook signature" in response.json()["error"]
            finally:
                app.dependency_overrides.clear()

    def test_webhook_signature_verification_replay_attack(self):
        """Test webhook prevents replay attacks (Issue #35)."""
        mock_event = {
            "id": "evt_test_789",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_789",
                    "payment_status": "paid",
                }
            }
        }

        from src.api.main import app
        from src.api.database import get_db

        client = TestClient(app)

        # Create mock database
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        # Use a real webhook secret
        test_secret = "whsec_test_123456789"
        payload = json.dumps(mock_event).encode('utf-8')

        # Create signature with timestamp 10 minutes in the past (outside 5-minute window)
        old_timestamp = int(time.time()) - 600
        signed_content = f"{old_timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            test_secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        sig_header = f"t={old_timestamp},v1={signature}"

        with patch('src.api.main.STRIPE_WEBHOOK_SECRET', test_secret):
            try:
                response = client.post(
                    "/api/webhook",
                    content=payload,
                    headers={"stripe-signature": sig_header}
                )

                # Verify rejection due to replay attack
                assert response.status_code == 400
                assert "timestamp outside acceptable window" in response.json()["error"]
            finally:
                app.dependency_overrides.clear()

    def test_webhook_signature_verification_missing_header(self):
        """Test webhook rejects missing signature header (Issue #35)."""
        mock_event = {
            "id": "evt_test_missing",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_missing",
                }
            }
        }

        from src.api.main import app
        from src.api.database import get_db

        client = TestClient(app)

        # Create mock database
        mock_db = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        payload = json.dumps(mock_event).encode('utf-8')
        test_secret = "whsec_test_123456789"

        with patch('src.api.main.STRIPE_WEBHOOK_SECRET', test_secret):
            try:
                response = client.post(
                    "/api/webhook",
                    content=payload,
                    headers={},  # No stripe-signature header
                )

                # Verify rejection due to missing header
                assert response.status_code == 400
                assert "Invalid or missing webhook headers" in response.json()["error"]
            finally:
                app.dependency_overrides.clear()

    def test_webhook_signature_verification_valid_signature(self):
        """Test webhook accepts valid signature (Issue #35)."""
        mock_event = {
            "id": "evt_test_valid",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_valid",
                    "payment_status": "paid",
                }
            }
        }

        from src.api.main import app
        from src.api.database import get_db
        from src.api.models import TaskStatus

        client = TestClient(app)

        # Create mock database
        mock_db = Mock()
        mock_task = Mock()
        mock_task.id = "test_task_valid"
        mock_task.status = TaskStatus.PENDING
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        mock_db.commit = Mock()
        app.dependency_overrides[get_db] = override_get_db(mock_db)

        # Use a real webhook secret
        test_secret = "whsec_test_123456789"
        payload = json.dumps(mock_event).encode('utf-8')

        # Create VALID signature with current timestamp
        current_time = int(time.time())
        signed_content = f"{current_time}.{payload.decode('utf-8')}"
        signature = hmac.new(
            test_secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        sig_header = f"t={current_time},v1={signature}"

        with patch('src.api.main.STRIPE_WEBHOOK_SECRET', test_secret):
            try:
                response = client.post(
                    "/api/webhook",
                    content=payload,
                    headers={"stripe-signature": sig_header}
                )

                # Verify success
                assert response.status_code == 200
                assert response.json()["status"] == "success"
            finally:
                app.dependency_overrides.clear()

    def test_webhook_checkout_expired_event(self):
        """Test webhook handles checkout.session.expired event."""
        mock_event = {
            "id": "evt_expired_123",
            "type": "checkout.session.expired",
            "data": {
                "object": {
                    "id": "cs_expired_123",
                }
            }
        }

        from src.api.main import app
        from src.api.database import get_db
        from src.api.models import TaskStatus

        client = TestClient(app)

        # Create mock database
        mock_db = Mock()
        mock_task = Mock()
        mock_task.id = "test_task_expired"
        mock_task.status = TaskStatus.PENDING
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        mock_db.commit = Mock()

        app.dependency_overrides[get_db] = override_get_db(mock_db)

        with patch('src.api.main.STRIPE_WEBHOOK_SECRET', 'whsec_placeholder'):
            try:
                response = client.post(
                    "/api/webhook",
                    content=json.dumps(mock_event).encode('utf-8'),
                    headers={"stripe-signature": "test_signature"}
                )

                # Verify response
                assert response.status_code == 200
                # Verify task was updated to FAILED
                assert mock_task.status == TaskStatus.FAILED
            finally:
                app.dependency_overrides.clear()
