"""
Comprehensive webhook security module for Stripe webhook verification.

Features:
- HMAC-SHA256 signature verification
- Timestamp-based replay attack prevention (5-minute window)
- Detailed logging for all verification attempts
- Exception handling and security event tracking
"""

import hmac
import hashlib
import json
import time
from typing import Dict, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class WebhookVerificationError(Exception):
    """Base exception for webhook verification failures."""

    pass


class InvalidSignatureError(WebhookVerificationError):
    """Raised when webhook signature verification fails."""

    pass


class ReplayAttackError(WebhookVerificationError):
    """Raised when webhook timestamp is outside acceptable window."""

    pass


class MissingHeaderError(WebhookVerificationError):
    """Raised when required webhook headers are missing."""

    pass


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    timestamp_seconds: int = 300,
) -> Dict[str, any]:
    """
    Comprehensive webhook signature verification with replay attack prevention.

    This function:
    1. Validates required headers are present
    2. Verifies HMAC-SHA256 signature using the webhook secret
    3. Checks timestamp is within acceptable window (prevents replay attacks)
    4. Returns parsed event data

    Args:
        payload: Raw webhook payload bytes
        signature: Stripe signature header value (t=timestamp,v1=signature)
        secret: Stripe webhook secret key
        timestamp_seconds: Maximum age of webhook in seconds (default 300 = 5 minutes)

    Returns:
        Dict containing verified webhook event data

    Raises:
        MissingHeaderError: If signature header is missing or malformed
        InvalidSignatureError: If signature verification fails
        ReplayAttackError: If timestamp is outside acceptable window
        WebhookVerificationError: For other verification failures

    Examples:
        >>> payload = b'{"type":"checkout.session.completed"}'
        >>> signature = "t=1234567890,v1=abc123..."
        >>> secret = "whsec_..."
        >>> event = verify_webhook_signature(payload, signature, secret)
        >>> print(event["type"])
        'checkout.session.completed'
    """
    logger_ctx = {
        "component": "webhook_verification",
        "signature_present": bool(signature),
    }

    # 1. Validate signature header is present and formatted correctly
    if not signature:
        error_msg = "Missing stripe-signature header"
        logger.warning(f"[WEBHOOK SECURITY] {error_msg}", extra=logger_ctx)
        raise MissingHeaderError(error_msg)

    # Parse signature header format: t=<timestamp>,v1=<signature>[,v1=<signature>]
    signature_parts = {}
    try:
        for part in signature.split(","):
            key, value = part.split("=", 1)
            signature_parts[key] = value
    except ValueError:
        error_msg = "Malformed stripe-signature header format"
        logger.warning(
            f"[WEBHOOK SECURITY] {error_msg}: {signature[:50]}",
            extra=logger_ctx,
        )
        raise MissingHeaderError(f"Invalid signature header format: {error_msg}")

    # Extract timestamp and signature
    timestamp_str = signature_parts.get("t")
    signed_content = signature_parts.get("v1")

    if not timestamp_str or not signed_content:
        error_msg = "Missing timestamp (t=) or signature (v1=) in header"
        logger.warning(f"[WEBHOOK SECURITY] {error_msg}", extra=logger_ctx)
        raise MissingHeaderError(error_msg)

    # 2. Verify timestamp (prevent replay attacks)
    try:
        webhook_timestamp = int(timestamp_str)
    except ValueError:
        error_msg = f"Invalid timestamp format: {timestamp_str}"
        logger.warning(f"[WEBHOOK SECURITY] {error_msg}", extra=logger_ctx)
        raise MissingHeaderError(error_msg)

    current_timestamp = int(time.time())
    time_difference = current_timestamp - webhook_timestamp

    logger_ctx["webhook_timestamp"] = webhook_timestamp
    logger_ctx["current_timestamp"] = current_timestamp
    logger_ctx["time_difference_seconds"] = time_difference

    # Check if timestamp is too old (potential replay attack)
    if time_difference > timestamp_seconds:
        error_msg = (
            f"Webhook timestamp too old: {time_difference}s > {timestamp_seconds}s"
        )
        logger.warning(
            f"[WEBHOOK SECURITY REPLAY ATTACK PREVENTED] {error_msg}",
            extra=logger_ctx,
        )
        raise ReplayAttackError(error_msg)

    # Check if timestamp is in the future (clock skew or tampering)
    if time_difference < -300:  # Allow 5 minutes of future drift for clock skew
        error_msg = f"Webhook timestamp in future: {time_difference}s"
        logger.warning(
            f"[WEBHOOK SECURITY] {error_msg}",
            extra=logger_ctx,
        )
        raise ReplayAttackError(error_msg)

    # 3. Verify HMAC-SHA256 signature
    # Stripe uses: signed_content = timestamp.payload
    signed_content_to_verify = f"{timestamp_str}.{payload.decode('utf-8')}"

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signed_content_to_verify.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signed_content, expected_signature):
        # Log failed signature attempt without revealing the actual signature
        logger.warning(
            "[WEBHOOK SECURITY SIGNATURE VERIFICATION FAILED]",
            extra={
                **logger_ctx,
                "received_signature": signed_content[:8] + "...",
                "payload_size": len(payload),
            },
        )
        raise InvalidSignatureError("Webhook signature verification failed")

    # 4. Parse and return the verified event
    try:
        event = json.loads(payload)
        logger.info(
            "[WEBHOOK SECURITY] Webhook signature verified successfully",
            extra={
                **logger_ctx,
                "event_type": event.get("type", "unknown"),
                "event_id": event.get("id", "unknown")[:12] + "...",
            },
        )
        return event
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in webhook payload: {str(e)}"
        logger.warning(f"[WEBHOOK SECURITY] {error_msg}", extra=logger_ctx)
        raise WebhookVerificationError(error_msg)


def should_replay_webhook(
    webhook_id: str,
    webhook_timestamp: int,
    recent_webhooks: Dict[str, int],
    dedup_window_seconds: int = 30,
) -> bool:
    """
    Check if a webhook might be a replay of a recently processed webhook.

    This provides an additional layer of protection against replays by tracking
    recently processed webhook IDs within a deduplication window.

    Args:
        webhook_id: Unique webhook/event ID from Stripe
        webhook_timestamp: Webhook timestamp (seconds since epoch)
        recent_webhooks: Dict of {webhook_id: timestamp} of recently processed webhooks
        dedup_window_seconds: Deduplication window in seconds (default 30)

    Returns:
        True if webhook might be a replay, False otherwise

    Examples:
        >>> recent = {"evt_123": 1640000000}
        >>> is_replay = should_replay_webhook("evt_123", 1640000000, recent)
        >>> print(is_replay)
        True
    """
    current_time = int(time.time())

    # Clean up old entries outside the dedup window
    cutoff_time = current_time - dedup_window_seconds
    recent_webhooks_clean = {
        k: v for k, v in recent_webhooks.items() if v > cutoff_time
    }

    # Check if this webhook ID was recently processed
    if webhook_id in recent_webhooks_clean:
        logger.warning(
            f"[WEBHOOK DEDUP] Possible replay detected: webhook_id={webhook_id}",
            extra={
                "previous_timestamp": recent_webhooks_clean[webhook_id],
                "current_timestamp": webhook_timestamp,
                "dedup_window_seconds": dedup_window_seconds,
            },
        )
        return True

    return False


def log_webhook_verification_attempt(
    success: bool,
    error_type: Optional[str] = None,
    event_type: Optional[str] = None,
    event_id: Optional[str] = None,
    additional_context: Optional[Dict] = None,
) -> None:
    """
    Log webhook verification attempt with structured context.

    Args:
        success: Whether verification succeeded
        error_type: Type of error if verification failed (e.g., 'InvalidSignature')
        event_type: Stripe event type from webhook (e.g., 'checkout.session.completed')
        event_id: Stripe event ID
        additional_context: Additional context to log
    """
    context = additional_context or {}
    context.update(
        {
            "component": "webhook_verification",
            "success": success,
            "event_type": event_type,
            "event_id": event_id[:12] + "..." if event_id else None,
        }
    )

    if error_type:
        context["error_type"] = error_type
        logger.warning(
            f"[WEBHOOK] Verification failed: {error_type}",
            extra=context,
        )
    else:
        logger.info(
            "[WEBHOOK] Verification succeeded",
            extra=context,
        )
