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
from typing import Optional
from fastapi import HTTPException, Query

from ..utils.logger import get_logger

logger = get_logger(__name__)

# Secret key for HMAC signing (MUST be set in production)
CLIENT_AUTH_SECRET = os.environ.get(
    "CLIENT_AUTH_SECRET", "CHANGE_ME_IN_PRODUCTION_use_a_random_32_byte_key"
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
        CLIENT_AUTH_SECRET.encode(), normalized_email.encode(), hashlib.sha256
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


# =============================================================================
# FASTAPI AUTH DEPENDENCY & DECORATOR
# =============================================================================


class AuthenticatedClient:
    """Dependency model for authenticated client (email + token)."""

    def __init__(self, email: str, token: str):
        self.email = email.strip().lower() if email else ""
        self.token = token.strip() if token else ""

    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return bool(self.email and self.token and verify_client_token(self.email, self.token))


def require_client_auth(
    email: str = Query(..., description="Client email address"),
    token: str = Query(..., description="HMAC authentication token"),
) -> AuthenticatedClient:
    """
    FastAPI dependency for requiring client authentication on endpoints.

    Validates that email and token form a valid HMAC signature.

    Raises:
        HTTPException 401: Missing or invalid authentication credentials
        HTTPException 403: Token doesn't match the provided email

    Args:
        email: Client email from query parameter
        token: HMAC token from query parameter

    Returns:
        AuthenticatedClient with verified email and token

    Usage:
        @app.get("/api/protected")
        async def protected_endpoint(client: AuthenticatedClient = Depends(require_client_auth)):
            return {"email": client.email}
    """
    # 1. Check for missing parameters
    if not email or not token:
        logger.warning("[CLIENT_AUTH] Missing auth parameters")
        raise HTTPException(
            status_code=401,
            detail="Missing email or token"
        )

    # Normalize email
    normalized_email = email.strip().lower()

    # 2. Verify token matches email
    if not verify_client_token(normalized_email, token):
        logger.warning(f"[CLIENT_AUTH] Invalid token for email: {normalized_email}")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )

    return AuthenticatedClient(normalized_email, token)


def optional_client_auth(
    email: Optional[str] = Query(None, description="Client email address"),
    token: Optional[str] = Query(None, description="HMAC authentication token"),
) -> AuthenticatedClient:
    """
    FastAPI dependency for optional client authentication.

    If email and token are provided, they must be valid.
    If both are missing, returns an empty authenticated client (not authenticated).

    Raises:
        HTTPException 401: Email provided without token or vice versa
        HTTPException 401: Invalid token for the given email

    Args:
        email: Optional client email from query parameter
        token: Optional HMAC token from query parameter

    Returns:
        AuthenticatedClient (may be unauthenticated if no parameters provided)

    Usage:
        @app.post("/api/price")
        async def price_endpoint(client: AuthenticatedClient = Depends(optional_client_auth)):
            if client.is_authenticated():
                # Apply discount
            else:
                # Use default price
    """
    # If neither provided, return unauthenticated client
    if not email and not token:
        return AuthenticatedClient("", "")

    # If only one provided, it's an error
    if not email or not token:
        logger.warning("[CLIENT_AUTH] Partial auth parameters provided")
        raise HTTPException(
            status_code=401,
            detail="Both email and token must be provided for authentication"
        )

    # Normalize email
    normalized_email = email.strip().lower()

    # Verify token matches email
    if not verify_client_token(normalized_email, token):
        logger.warning(f"[CLIENT_AUTH] Invalid token for email: {normalized_email}")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )

    return AuthenticatedClient(normalized_email, token)
