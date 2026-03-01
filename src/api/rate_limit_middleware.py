"""
Rate limiting middleware for FastAPI.

Issue #45: API Rate Limiting, Quotas, and Usage Analytics

Automatically enforces rate limits and quotas on all endpoints.
Returns 429 (Too Many Requests) or 402 (Payment Required) status codes.
"""

import os
import time
import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .database import SessionLocal
from .models import UserQuota
from .rate_limiter import RateLimiter, QuotaManager

logger = logging.getLogger(__name__)

# Global rate limiter instance
_rate_limiter = None
_quota_manager = None


def get_rate_limiter():
    """Get or create global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        # Disable rate limiting for tests
        if os.getenv("DISABLE_RATE_LIMITING") == "true":
            logger.info("Rate limiting disabled (DISABLE_RATE_LIMITING=true)")
            _rate_limiter = RateLimiter(None)
            return _rate_limiter

        try:
            import redis

            redis_client = redis.Redis(
                host="localhost",
                port=6379,
                db=0,
                decode_responses=True,
            )
            redis_client.ping()
            _rate_limiter = RateLimiter(redis_client)
        except Exception:
            logger.warning("Redis not available. Using in-memory rate limiter.")
            _rate_limiter = RateLimiter(None)
    return _rate_limiter


def get_quota_manager():
    """Get or create global quota manager."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce rate limits and quotas on all endpoints.

    Extracts user_id from:
    1. Header: X-User-ID
    2. Query parameter: user_id
    3. Default: "anonymous"

    Returns:
    - 429: Too Many Requests (rate limit exceeded)
    - 402: Payment Required (quota exceeded)
    """

    # Endpoints that bypass rate limiting
    BYPASS_ENDPOINTS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/webhook/stripe",  # Webhook endpoints
    }

    async def dispatch(self, request: Request, call_next: Callable):
        """Process request through rate limit checks."""
        start_time = time.time()

        # Skip rate limiting for certain endpoints
        if any(request.url.path.startswith(ep) for ep in self.BYPASS_ENDPOINTS):
            return await call_next(request)

        # Extract user ID
        user_id = self._extract_user_id(request)

        db = SessionLocal()
        try:
            # Get or create user quota
            quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()

            if not quota:
                # Create default FREE quota for new user
                quota = UserQuota(user_id=user_id)
                db.add(quota)
                db.commit()
                db.refresh(quota)

            # Check rate limit
            if os.getenv("DISABLE_RATE_LIMITING") == "true":
                pass  # Skip rate limiting
            else:
                rate_limiter = get_rate_limiter()
                allowed, rate_details = rate_limiter.is_allowed(
                    user_id,
                    quota,
                )

                if not allowed:
                    response_time_ms = (time.time() - start_time) * 1000
                    quota_manager = get_quota_manager()
                    quota_manager.log_rate_limit(
                        db,
                        user_id=user_id,
                        endpoint=request.url.path,
                        method=request.method,
                        requests_in_window=rate_details.get("requests_in_window", 0),
                        rate_limit_rps=quota.rate_limit_rps,
                        exceeded=True,
                        status_code=429,
                        response_time_ms=response_time_ms,
                    )

                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Too Many Requests",
                            "rate_limit_rps": quota.rate_limit_rps,
                            "requests_in_window": rate_details.get(
                                "requests_in_window", 0
                            ),
                            "retry_after": 1,
                        },
                    )

            # Check quota for relevant endpoints
            quota_exceeded = False
            quota_type = None
            quota_check = None

            # Task creation endpoints
            if request.url.path.startswith("/api/submit-task"):
                quota_manager = get_quota_manager()
                allowed_quota, quota_check = quota_manager.check_task_quota(
                    db, user_id, quota
                )
                if not allowed_quota:
                    quota_exceeded = True
                    quota_type = "task"

            # API call quota (for all API endpoints)
            if not quota_exceeded and request.url.path.startswith("/api/"):
                quota_manager = get_quota_manager()
                allowed_quota, quota_check = quota_manager.check_api_quota(
                    db, user_id, quota
                )
                if not allowed_quota:
                    quota_exceeded = True
                    quota_type = "api_call"

            if quota_exceeded:
                response_time_ms = (time.time() - start_time) * 1000
                quota_manager = get_quota_manager()
                quota_manager.log_rate_limit(
                    db,
                    user_id=user_id,
                    endpoint=request.url.path,
                    method=request.method,
                    requests_in_window=0,
                    rate_limit_rps=quota.rate_limit_rps,
                    exceeded=False,  # Rate limit not exceeded, quota is
                    status_code=402,
                    response_time_ms=response_time_ms,
                    quota_type=quota_type,
                    quota_used=quota_check.get("used", 0),
                    quota_limit=quota_check.get("limit", 0),
                    quota_exceeded=True,
                )

                return JSONResponse(
                    status_code=402,
                    content={
                        "detail": "Quota Exceeded",
                        "quota_type": quota_type,
                        "used": quota_check.get("used", 0),
                        "limit": quota_check.get("limit", 0),
                        "remaining": quota_check.get("remaining", 0),
                        "upgrade_url": "https://example.com/pricing",
                    },
                )

            # Process request
            response = await call_next(request)

            # Log successful request
            response_time_ms = (time.time() - start_time) * 1000
            if response.status_code < 400:  # Only log successful requests
                quota_manager = get_quota_manager()
                quota_manager.log_rate_limit(
                    db,
                    user_id=user_id,
                    endpoint=request.url.path,
                    method=request.method,
                    requests_in_window=rate_details.get("requests_in_window", 0),
                    rate_limit_rps=quota.rate_limit_rps,
                    exceeded=False,
                    status_code=response.status_code,
                    response_time_ms=response_time_ms,
                )

            return response

        except Exception as e:
            logger.error(f"Rate limit middleware error: {e}", exc_info=True)
            # Don't block requests on middleware errors
            return await call_next(request)

        finally:
            db.close()

    def _extract_user_id(self, request: Request) -> str:
        """Extract user ID from request."""
        # Try header first
        user_id = request.headers.get("X-User-ID")
        if user_id:
            return user_id

        # Try query parameter
        user_id = request.query_params.get("user_id")
        if user_id:
            return user_id

        # Try from auth token (if available)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Could decode JWT here if needed
            token = auth_header[7:]
            # For now, use token as user_id
            return token[:16]  # Use first 16 chars

        # Default
        return "anonymous"
