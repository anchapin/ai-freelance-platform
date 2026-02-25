"""
Redis-backed distributed rate limiting and quota enforcement.

Issue #45: API Rate Limiting, Quotas, and Usage Analytics

Provides:
- RedisRateLimiter for distributed rate limiting (sliding window)
- QuotaManager for monthly quota tracking
- Graceful handling with 429/402 status codes
- Webhook alerts for quota thresholds
"""

import time
import redis
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple
import json
import logging

from sqlalchemy.orm import Session
from .models import (
    UserQuota,
    QuotaUsage,
    RateLimitLog,
    PricingTier,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Distributed rate limiter using Redis (sliding window algorithm).
    
    Tracks requests per second (RPS) with burst capacity using a sliding
    window. Each request increments a counter for the current second window.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize rate limiter.
        
        Args:
            redis_client: Redis connection (or None to create default)
        """
        if redis_client is None:
            try:
                redis_client = redis.Redis(
                    host="localhost",
                    port=6379,
                    db=0,
                    decode_responses=True,
                )
                redis_client.ping()
            except Exception as e:
                logger.warning(f"Redis not available: {e}. Using in-memory fallback.")
                redis_client = None
        
        self.redis = redis_client
        self._in_memory_windows = {}  # Fallback: in-memory window tracking
    
    def is_allowed(
        self,
        user_id: str,
        quota: UserQuota,
        override: bool = False,
    ) -> Tuple[bool, Dict]:
        """
        Check if request is allowed within rate limits.
        
        Uses sliding window algorithm:
        - Current second: increment counter
        - Check if counter > rate_limit_rps
        - Include burst capacity for spikes
        
        Args:
            user_id: User identifier
            quota: UserQuota config
            override: Admin override flag
        
        Returns:
            (allowed: bool, details: dict)
        """
        if override or quota.override_rate_limit:
            return True, {"allowed": True, "reason": "admin_override"}
        
        # For Enterprise tier, no rate limiting
        if quota.tier == PricingTier.ENTERPRISE:
            return True, {"allowed": True, "reason": "enterprise_unlimited"}
        
        current_second = int(time.time())
        window_key = f"rate_limit:{user_id}:{current_second}"
        burst_key = f"rate_limit_burst:{user_id}"
        
        if self.redis:
            return self._check_redis(
                window_key,
                burst_key,
                quota.rate_limit_rps,
                quota.rate_limit_burst,
            )
        else:
            return self._check_memory(
                user_id,
                current_second,
                quota.rate_limit_rps,
                quota.rate_limit_burst,
            )
    
    def _check_redis(
        self,
        window_key: str,
        burst_key: str,
        rps_limit: int,
        burst_limit: int,
    ) -> Tuple[bool, Dict]:
        """Check rate limit using Redis."""
        try:
            # Increment request counter for current second
            pipe = self.redis.pipeline()
            pipe.incr(window_key)
            pipe.expire(window_key, 2)  # Keep for 2 seconds (current + 1)
            results = pipe.execute()
            request_count = results[0]
            
            # Check if burst is available
            burst_available = self.redis.incr(burst_key)
            if burst_available > burst_limit:
                self.redis.decr(burst_key)
                burst_available = burst_limit
            self.redis.expire(burst_key, 3600)  # Reset hourly
            
            # Allow if within RPS or if burst available
            allowed = request_count <= rps_limit or burst_available > 0
            
            if not allowed and burst_available > 0:
                self.redis.decr(burst_key)
                allowed = True
            
            return allowed, {
                "allowed": allowed,
                "requests_in_window": request_count,
                "burst_available": burst_available if allowed else 0,
            }
        except Exception as e:
            logger.error(f"Redis rate limit check failed: {e}. Allowing request.")
            return True, {"allowed": True, "reason": "redis_error"}
    
    def _check_memory(
        self,
        user_id: str,
        current_second: int,
        rps_limit: int,
        burst_limit: int,
    ) -> Tuple[bool, Dict]:
        """Check rate limit using in-memory window (fallback)."""
        window_key = f"{user_id}:{current_second}"
        
        if window_key not in self._in_memory_windows:
            self._in_memory_windows[window_key] = {
                "count": 0,
                "created_at": time.time(),
            }
        
        # Increment counter
        self._in_memory_windows[window_key]["count"] += 1
        request_count = self._in_memory_windows[window_key]["count"]
        
        # Cleanup old windows
        cutoff = time.time() - 2
        expired_keys = [
            k for k, v in self._in_memory_windows.items()
            if v["created_at"] < cutoff
        ]
        for k in expired_keys:
            del self._in_memory_windows[k]
        
        allowed = request_count <= rps_limit
        
        return allowed, {
            "allowed": allowed,
            "requests_in_window": request_count,
        }


class QuotaManager:
    """
    Manages monthly quota enforcement and tracking.
    
    Handles:
    - Task quota enforcement
    - API call quota enforcement
    - Compute time quota enforcement
    - 80%/100% threshold alerts
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def get_current_billing_month(self) -> str:
        """Get current billing month in YYYY-MM format."""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m")
    
    def get_or_create_usage(
        self,
        db: Session,
        user_id: str,
        billing_month: Optional[str] = None,
    ) -> QuotaUsage:
        """Get or create QuotaUsage record for user and month."""
        if billing_month is None:
            billing_month = self.get_current_billing_month()
        
        usage = db.query(QuotaUsage).filter(
            QuotaUsage.user_id == user_id,
            QuotaUsage.billing_month == billing_month,
        ).first()
        
        if not usage:
            usage = QuotaUsage(
                user_id=user_id,
                billing_month=billing_month,
            )
            db.add(usage)
            db.commit()
            db.refresh(usage)
        
        return usage
    
    def check_task_quota(
        self,
        db: Session,
        user_id: str,
        quota: UserQuota,
        override: bool = False,
    ) -> Tuple[bool, Dict]:
        """Check if user can create a new task."""
        if override or quota.override_quota:
            return True, {"allowed": True, "reason": "admin_override"}
        
        if quota.tier == PricingTier.ENTERPRISE:
            return True, {"allowed": True, "reason": "enterprise_unlimited"}
        
        usage = self.get_or_create_usage(db, user_id)
        
        # Check if limit exceeded
        allowed = usage.task_count < quota.monthly_task_limit
        
        return allowed, {
            "allowed": allowed,
            "used": usage.task_count,
            "limit": quota.monthly_task_limit,
            "remaining": max(0, quota.monthly_task_limit - usage.task_count),
        }
    
    def check_api_quota(
        self,
        db: Session,
        user_id: str,
        quota: UserQuota,
        override: bool = False,
    ) -> Tuple[bool, Dict]:
        """Check if user can make an API call."""
        if override or quota.override_quota:
            return True, {"allowed": True, "reason": "admin_override"}
        
        if quota.tier == PricingTier.ENTERPRISE:
            return True, {"allowed": True, "reason": "enterprise_unlimited"}
        
        usage = self.get_or_create_usage(db, user_id)
        
        # Check if limit exceeded
        allowed = usage.api_call_count < quota.monthly_api_calls_limit
        
        return allowed, {
            "allowed": allowed,
            "used": usage.api_call_count,
            "limit": quota.monthly_api_calls_limit,
            "remaining": max(0, quota.monthly_api_calls_limit - usage.api_call_count),
        }
    
    def check_compute_quota(
        self,
        db: Session,
        user_id: str,
        quota: UserQuota,
        compute_minutes: float,
        override: bool = False,
    ) -> Tuple[bool, Dict]:
        """Check if user can use compute minutes."""
        if override or quota.override_quota:
            return True, {"allowed": True, "reason": "admin_override"}
        
        if quota.tier == PricingTier.ENTERPRISE:
            return True, {"allowed": True, "reason": "enterprise_unlimited"}
        
        usage = self.get_or_create_usage(db, user_id)
        
        # Check if limit exceeded
        new_total = usage.compute_minutes_used + compute_minutes
        allowed = new_total <= quota.monthly_compute_minutes_limit
        
        return allowed, {
            "allowed": allowed,
            "used": usage.compute_minutes_used,
            "requested": compute_minutes,
            "limit": quota.monthly_compute_minutes_limit,
            "remaining": max(0.0, quota.monthly_compute_minutes_limit - usage.compute_minutes_used),
        }
    
    def increment_task_count(
        self,
        db: Session,
        user_id: str,
    ) -> QuotaUsage:
        """Increment task count for current month."""
        usage = self.get_or_create_usage(db, user_id)
        usage.task_count += 1
        usage.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(usage)
        return usage
    
    def increment_api_calls(
        self,
        db: Session,
        user_id: str,
        count: int = 1,
    ) -> QuotaUsage:
        """Increment API call count for current month."""
        usage = self.get_or_create_usage(db, user_id)
        usage.api_call_count += count
        usage.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(usage)
        return usage
    
    def add_compute_time(
        self,
        db: Session,
        user_id: str,
        compute_minutes: float,
    ) -> QuotaUsage:
        """Add compute time to current month."""
        usage = self.get_or_create_usage(db, user_id)
        usage.compute_minutes_used += compute_minutes
        usage.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(usage)
        return usage
    
    def check_threshold_and_alert(
        self,
        db: Session,
        user_id: str,
        quota: UserQuota,
        usage: QuotaUsage,
    ) -> Optional[Dict]:
        """Check if usage exceeds alert threshold and return alert if needed."""
        if quota.tier == PricingTier.ENTERPRISE:
            return None
        
        # Calculate overall usage percentage (max of all quotas)
        task_percent = (usage.task_count / quota.monthly_task_limit * 100) if quota.monthly_task_limit > 0 else 0
        api_percent = (usage.api_call_count / quota.monthly_api_calls_limit * 100) if quota.monthly_api_calls_limit > 0 else 0
        compute_percent = (usage.compute_minutes_used / quota.monthly_compute_minutes_limit * 100) if quota.monthly_compute_minutes_limit > 0 else 0
        
        max_percent = max(task_percent, api_percent, compute_percent)
        
        alert = None
        
        # 80% threshold
        if max_percent >= 80 and not usage.alert_sent_at_80_percent:
            usage.alert_sent_at_80_percent = datetime.utcnow()
            alert = {
                "type": "quota_80_percent",
                "user_id": user_id,
                "usage_percentage": max_percent,
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        # 100% threshold
        if max_percent >= 100:
            if not usage.alert_sent_at_100_percent:
                usage.alert_sent_at_100_percent = datetime.utcnow()
                usage.quota_exceeded = True
            
            alert = {
                "type": "quota_100_percent",
                "user_id": user_id,
                "usage_percentage": max_percent,
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        if alert:
            usage.updated_at = datetime.utcnow()
            db.commit()
        
        return alert
    
    def log_rate_limit(
        self,
        db: Session,
        user_id: str,
        endpoint: str,
        method: str,
        requests_in_window: int,
        rate_limit_rps: int,
        exceeded: bool,
        status_code: int,
        response_time_ms: float,
        quota_type: Optional[str] = None,
        quota_used: Optional[int] = None,
        quota_limit: Optional[int] = None,
        quota_exceeded: bool = False,
    ) -> RateLimitLog:
        """Log rate limit enforcement."""
        log = RateLimitLog(
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            requests_in_window=requests_in_window,
            rate_limit_rps=rate_limit_rps,
            exceeded=exceeded,
            quota_type=quota_type,
            quota_used=quota_used,
            quota_limit=quota_limit,
            quota_exceeded=quota_exceeded,
            status_code=status_code,
            response_time_ms=response_time_ms,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log


def get_tier_limits(tier: PricingTier) -> Dict[str, int]:
    """Get quota limits for a pricing tier."""
    limits = {
        PricingTier.FREE: {
            "monthly_task_limit": 10,
            "monthly_api_calls_limit": 100,
            "monthly_compute_minutes_limit": 60,
            "rate_limit_rps": 10,
            "rate_limit_burst": 50,
        },
        PricingTier.PRO: {
            "monthly_task_limit": 1000,
            "monthly_api_calls_limit": 10000,
            "monthly_compute_minutes_limit": 600,
            "rate_limit_rps": 50,
            "rate_limit_burst": 200,
        },
        PricingTier.ENTERPRISE: {
            "monthly_task_limit": 999999999,
            "monthly_api_calls_limit": 999999999,
            "monthly_compute_minutes_limit": 999999999,
            "rate_limit_rps": 1000,
            "rate_limit_burst": 5000,
        },
    }
    return limits.get(tier, limits[PricingTier.FREE])
