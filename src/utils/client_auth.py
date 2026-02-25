"""
Client Authentication via HMAC-signed email tokens.

Provides stateless authentication for client dashboard endpoints
without requiring user registration or JWT infrastructure.

How it works:
1. When a task is created, the server generates an HMAC signature
   of the client's email using a secret key.
2. The signed token is returned to the client (e.g., in the Stripe
   success redirect or task response).
3. For subsequent dashboard requests, the client sends (email, token).
4. The server verifies the HMAC signature matches the email.

Security properties:
- Tokens are unforgeable without the secret key
- Constant-time comparison via hmac.compare_digest
- Tokens never expire (tied to email, not session)
- No database lookups needed for verification

Issue #17: SECURITY - Unauthenticated Client Dashboard Access
"""

import hmac
import hashlib
import os

from ..utils.logger import get_logger

logger = get_logger(__name__)

# Secret key for HMAC signing (MUST be set in production)
CLIENT_AUTH_SECRET = os.environ.get(
    "CLIENT_AUTH_SECRET",
    "CHANGE_ME_IN_PRODUCTION_use_a_random_32_byte_key"
)


def generate_client_token(email: str) -> str:
    """
    Generate an HMAC-signed token for a client email.

    Args:
        email: The client's email address (case-insensitive)

    Returns:
        Hex-encoded HMAC signature
    """
    normalized_email = email.strip().lower()
    signature = hmac.new(
        CLIENT_AUTH_SECRET.encode(),
        normalized_email.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def verify_client_token(email: str, token: str) -> bool:
    """
    Verify that an HMAC token is valid for a given email.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        email: The client's email address
        token: The HMAC token to verify

    Returns:
        True if the token is valid, False otherwise
    """
    if not email or not token:
        return False

    expected = generate_client_token(email)
    is_valid = hmac.compare_digest(expected, token)

    if not is_valid:
        logger.warning(f"[CLIENT_AUTH] Invalid token for email: {email}")

    return is_valid
