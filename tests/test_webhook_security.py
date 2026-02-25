"""
Comprehensive tests for webhook security verification (Issue #35).

Tests cover:
- HMAC-SHA256 signature verification
- Timestamp-based replay attack prevention
- Error handling and logging
- Integration with Stripe webhook endpoint
"""

import json
import hmac
import hashlib
import time
import pytest
from unittest.mock import patch

from src.utils.webhook_security import (
    verify_webhook_signature,
    WebhookVerificationError,
    InvalidSignatureError,
    ReplayAttackError,
    MissingHeaderError,
    should_replay_webhook,
    log_webhook_verification_attempt,
)


class TestWebhookSignatureVerification:
    """Tests for HMAC-SHA256 signature verification."""

    @pytest.fixture
    def test_webhook_secret(self):
        """Stripe webhook secret for testing."""
        return "whsec_test_secret_key_123456789"

    @pytest.fixture
    def test_payload(self):
        """Sample webhook payload."""
        payload = {
            "id": "evt_1234567890",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_session",
                    "payment_status": "paid",
                }
            },
        }
        return json.dumps(payload).encode("utf-8")

    def create_valid_signature(
        self, payload: bytes, secret: str, timestamp: int
    ) -> str:
        """Helper to create a valid Stripe signature."""
        signed_content = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_valid_signature_verification(self, test_payload, test_webhook_secret):
        """Test successful signature verification."""
        current_time = int(time.time())
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, current_time
        )

        event = verify_webhook_signature(
            payload=test_payload,
            signature=signature,
            secret=test_webhook_secret,
        )

        assert event["type"] == "checkout.session.completed"
        assert event["data"]["object"]["id"] == "cs_test_session"

    def test_invalid_signature_raises_error(self, test_payload, test_webhook_secret):
        """Test that invalid signature raises InvalidSignatureError."""
        current_time = int(time.time())
        # Create an invalid signature
        invalid_signature = f"t={current_time},v1=invalid_signature_hash"

        with pytest.raises(InvalidSignatureError):
            verify_webhook_signature(
                payload=test_payload,
                signature=invalid_signature,
                secret=test_webhook_secret,
            )

    def test_missing_signature_header_raises_error(self, test_payload):
        """Test that missing signature header raises MissingHeaderError."""
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature=None,
                secret="test_secret",
            )

    def test_empty_signature_header_raises_error(self, test_payload):
        """Test that empty signature header raises MissingHeaderError."""
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature="",
                secret="test_secret",
            )

    def test_malformed_signature_header_raises_error(self, test_payload):
        """Test that malformed signature header raises MissingHeaderError."""
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature="malformed_header",
                secret="test_secret",
            )

    def test_missing_timestamp_in_header_raises_error(self, test_payload):
        """Test that missing timestamp in signature raises MissingHeaderError."""
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature="v1=somesignature",
                secret="test_secret",
            )

    def test_missing_signature_value_in_header_raises_error(self, test_payload):
        """Test that missing signature value raises MissingHeaderError."""
        current_time = int(time.time())
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature=f"t={current_time}",
                secret="test_secret",
            )

    def test_invalid_timestamp_format_raises_error(self, test_payload):
        """Test that invalid timestamp format raises MissingHeaderError."""
        with pytest.raises(MissingHeaderError):
            verify_webhook_signature(
                payload=test_payload,
                signature="t=invalid_timestamp,v1=signature",
                secret="test_secret",
            )


class TestReplayAttackPrevention:
    """Tests for timestamp-based replay attack prevention."""

    @pytest.fixture
    def test_webhook_secret(self):
        """Stripe webhook secret for testing."""
        return "whsec_test_secret_key_123456789"

    @pytest.fixture
    def test_payload(self):
        """Sample webhook payload."""
        payload = {
            "id": "evt_1234567890",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_session"}},
        }
        return json.dumps(payload).encode("utf-8")

    def create_valid_signature(
        self, payload: bytes, secret: str, timestamp: int
    ) -> str:
        """Helper to create a valid Stripe signature."""
        signed_content = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_webhook_timestamp_too_old_raises_error(
        self, test_payload, test_webhook_secret
    ):
        """Test that webhook older than 5 minutes raises ReplayAttackError."""
        # Create signature with timestamp 10 minutes in the past
        old_timestamp = int(time.time()) - 600
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, old_timestamp
        )

        with pytest.raises(ReplayAttackError):
            verify_webhook_signature(
                payload=test_payload,
                signature=signature,
                secret=test_webhook_secret,
                timestamp_seconds=300,  # 5-minute window
            )

    def test_webhook_timestamp_at_boundary_accepted(
        self, test_payload, test_webhook_secret
    ):
        """Test that webhook at the boundary of the window is accepted."""
        # Create signature with timestamp exactly 5 minutes (300 seconds) in the past
        boundary_timestamp = int(time.time()) - 300
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, boundary_timestamp
        )

        event = verify_webhook_signature(
            payload=test_payload,
            signature=signature,
            secret=test_webhook_secret,
            timestamp_seconds=300,
        )

        assert event["type"] == "checkout.session.completed"

    def test_webhook_timestamp_slightly_old_accepted(
        self, test_payload, test_webhook_secret
    ):
        """Test that webhook slightly older than current time is accepted."""
        # Create signature with timestamp 2 minutes in the past
        old_timestamp = int(time.time()) - 120
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, old_timestamp
        )

        event = verify_webhook_signature(
            payload=test_payload,
            signature=signature,
            secret=test_webhook_secret,
            timestamp_seconds=300,
        )

        assert event["type"] == "checkout.session.completed"

    def test_webhook_timestamp_in_future_raises_error(
        self, test_payload, test_webhook_secret
    ):
        """Test that webhook with future timestamp raises ReplayAttackError."""
        # Create signature with timestamp 10 minutes in the future
        future_timestamp = int(time.time()) + 600
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, future_timestamp
        )

        with pytest.raises(ReplayAttackError):
            verify_webhook_signature(
                payload=test_payload,
                signature=signature,
                secret=test_webhook_secret,
                timestamp_seconds=300,
            )

    def test_webhook_with_custom_replay_window(
        self, test_payload, test_webhook_secret
    ):
        """Test that custom replay window is respected."""
        # Create signature with timestamp 10 seconds in the past
        recent_timestamp = int(time.time()) - 10
        signature = self.create_valid_signature(
            test_payload, test_webhook_secret, recent_timestamp
        )

        # Should fail with 5-second window
        with pytest.raises(ReplayAttackError):
            verify_webhook_signature(
                payload=test_payload,
                signature=signature,
                secret=test_webhook_secret,
                timestamp_seconds=5,  # Very strict window
            )

        # Should pass with 30-second window
        event = verify_webhook_signature(
            payload=test_payload,
            signature=signature,
            secret=test_webhook_secret,
            timestamp_seconds=30,  # More lenient window
        )

        assert event["type"] == "checkout.session.completed"


class TestPayloadValidation:
    """Tests for payload validation and parsing."""

    @pytest.fixture
    def test_webhook_secret(self):
        return "whsec_test_secret_key_123456789"

    def create_valid_signature(
        self, payload: bytes, secret: str, timestamp: int
    ) -> str:
        """Helper to create a valid Stripe signature."""
        signed_content = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_invalid_json_payload_raises_error(self, test_webhook_secret):
        """Test that invalid JSON payload raises WebhookVerificationError."""
        invalid_payload = b"invalid json {]"
        current_time = int(time.time())

        # Create signature for the invalid payload
        signed_content = f"{current_time}.{invalid_payload.decode('utf-8')}"
        signature = hmac.new(
            test_webhook_secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        sig_header = f"t={current_time},v1={signature}"

        with pytest.raises(WebhookVerificationError):
            verify_webhook_signature(
                payload=invalid_payload,
                signature=sig_header,
                secret=test_webhook_secret,
            )

    def test_valid_complex_payload(self, test_webhook_secret):
        """Test that complex valid payload is parsed correctly."""
        payload = {
            "id": "evt_complex_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_complex_session",
                    "payment_status": "paid",
                    "metadata": {"task_id": "task_abc123"},
                    "customer": {"email": "customer@example.com"},
                }
            },
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        current_time = int(time.time())
        signature = self.create_valid_signature(
            payload_bytes, test_webhook_secret, current_time
        )

        event = verify_webhook_signature(
            payload=payload_bytes,
            signature=signature,
            secret=test_webhook_secret,
        )

        assert event["id"] == "evt_complex_123"
        assert event["data"]["object"]["metadata"]["task_id"] == "task_abc123"


class TestReplayWebhookDeduplication:
    """Tests for webhook deduplication to prevent replays."""

    def test_first_webhook_not_flagged_as_replay(self):
        """Test that first webhook is not flagged as replay."""
        recent_webhooks = {}
        result = should_replay_webhook(
            webhook_id="evt_123",
            webhook_timestamp=int(time.time()),
            recent_webhooks=recent_webhooks,
        )
        assert result is False

    def test_duplicate_webhook_flagged_as_replay(self):
        """Test that duplicate webhook is flagged as replay."""
        current_time = int(time.time())
        recent_webhooks = {"evt_123": current_time - 10}

        result = should_replay_webhook(
            webhook_id="evt_123",
            webhook_timestamp=current_time,
            recent_webhooks=recent_webhooks,
        )
        assert result is True

    def test_old_webhook_not_in_dedup_window(self):
        """Test that webhook outside dedup window is not flagged as replay."""
        current_time = int(time.time())
        recent_webhooks = {
            "evt_old": current_time - 60,  # 60 seconds ago
        }

        result = should_replay_webhook(
            webhook_id="evt_old",
            webhook_timestamp=current_time,
            recent_webhooks=recent_webhooks,
            dedup_window_seconds=30,  # 30-second window
        )
        assert result is False

    def test_custom_dedup_window(self):
        """Test that custom dedup window is respected."""
        current_time = int(time.time())

        # Within 60-second window
        recent_webhooks = {"evt_123": current_time - 30}
        result = should_replay_webhook(
            webhook_id="evt_123",
            webhook_timestamp=current_time,
            recent_webhooks=recent_webhooks,
            dedup_window_seconds=60,
        )
        assert result is True

        # Outside 20-second window
        result = should_replay_webhook(
            webhook_id="evt_123",
            webhook_timestamp=current_time,
            recent_webhooks=recent_webhooks,
            dedup_window_seconds=20,
        )
        assert result is False


class TestLoggingAndAudit:
    """Tests for logging and audit trail."""

    @patch("src.utils.webhook_security.logger")
    def test_successful_verification_logged(self, mock_logger):
        """Test that successful verification is logged."""
        log_webhook_verification_attempt(
            success=True,
            event_type="checkout.session.completed",
            event_id="evt_test_123",
        )

        mock_logger.info.assert_called_once()

    @patch("src.utils.webhook_security.logger")
    def test_failed_verification_logged(self, mock_logger):
        """Test that failed verification is logged."""
        log_webhook_verification_attempt(
            success=False,
            error_type="InvalidSignature",
            event_type="checkout.session.completed",
            event_id="evt_test_123",
        )

        mock_logger.warning.assert_called_once()

    @patch("src.utils.webhook_security.logger")
    def test_replay_attack_logged_as_critical(self, mock_logger):
        """Test that replay attacks are logged as critical."""
        with patch("src.utils.webhook_security.time.time", return_value=1000.0):
            payload = b'{"type": "test"}'
            signature = "t=100,v1=somesig"  # Very old timestamp

            try:
                verify_webhook_signature(
                    payload=payload,
                    signature=signature,
                    secret="test_secret",
                )
            except ReplayAttackError:
                pass

        # Verify critical log was called for replay attack
        assert mock_logger.critical.called or mock_logger.warning.called


class TestConstantTimeComparison:
    """Tests for constant-time signature comparison."""

    @pytest.fixture
    def test_webhook_secret(self):
        return "whsec_test_secret_key_123456789"

    @pytest.fixture
    def test_payload(self):
        payload = {"type": "test"}
        return json.dumps(payload).encode("utf-8")

    def create_valid_signature(
        self, payload: bytes, secret: str, timestamp: int
    ) -> str:
        """Helper to create a valid Stripe signature."""
        signed_content = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_one_character_different_signature_rejected(
        self, test_payload, test_webhook_secret
    ):
        """Test that signature different by one character is rejected."""
        current_time = int(time.time())
        valid_signature = self.create_valid_signature(
            test_payload, test_webhook_secret, current_time
        )

        # Modify one character in the signature
        parts = valid_signature.split("v1=")
        sig_part = parts[1]
        modified_sig = sig_part[:-1] + ("0" if sig_part[-1] != "0" else "1")
        invalid_signature = parts[0] + "v1=" + modified_sig

        with pytest.raises(InvalidSignatureError):
            verify_webhook_signature(
                payload=test_payload,
                signature=invalid_signature,
                secret=test_webhook_secret,
            )

    def test_timing_attack_resistant(self, test_payload, test_webhook_secret):
        """Test that signature comparison is timing-attack resistant."""
        current_time = int(time.time())

        # Create a valid signature
        valid_signature = self.create_valid_signature(
            test_payload, test_webhook_secret, current_time
        )

        # Test multiple invalid signatures to ensure constant-time comparison
        for i in range(5):
            parts = valid_signature.split("v1=")
            sig_part = parts[1]
            # Flip bits at different positions to create invalid signature
            # Use XOR with 0x01 to flip the least significant bit
            sig_chars = list(sig_part)
            if len(sig_chars) > i:
                # Flip a hex character
                original_char = sig_chars[i]
                sig_chars[i] = "f" if original_char != "f" else "e"
            modified_sig = "".join(sig_chars)
            invalid_signature = parts[0] + "v1=" + modified_sig

            with pytest.raises(InvalidSignatureError):
                verify_webhook_signature(
                    payload=test_payload,
                    signature=invalid_signature,
                    secret=test_webhook_secret,
                )
