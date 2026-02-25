"""
Admin endpoints for quota management and monitoring.

Issue #45: API Rate Limiting, Quotas, and Usage Analytics

Provides admin panel functionality:
- Update user quotas
- Override quotas/rate limits
- View usage analytics
- Manage pricing tiers
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field

from .database import get_db
from .models import UserQuota, QuotaUsage, RateLimitLog, PricingTier
from .rate_limiter import get_tier_limits

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class UserQuotaUpdate(BaseModel):
    """Schema for updating user quotas."""
    tier: Optional[str] = None
    monthly_task_limit: Optional[int] = None
    monthly_api_calls_limit: Optional[int] = None
    monthly_compute_minutes_limit: Optional[int] = None
    rate_limit_rps: Optional[int] = None
    rate_limit_burst: Optional[int] = None
    alert_threshold_percentage: Optional[int] = None
    override_rate_limit: Optional[bool] = None
    override_quota: Optional[bool] = None


class QuotaOverride(BaseModel):
    """Schema for admin overrides."""
    override_type: str = Field(..., description="'rate_limit' or 'quota'")
    enabled: bool
    reason: Optional[str] = None


class UserQuotaResponse(BaseModel):
    """Response schema for user quota."""
    id: str
    user_id: str
    tier: str
    monthly_task_limit: int
    monthly_api_calls_limit: int
    monthly_compute_minutes_limit: int
    rate_limit_rps: int
    rate_limit_burst: int
    override_rate_limit: bool
    override_quota: bool
    created_at: str
    updated_at: str


class QuotaUsageResponse(BaseModel):
    """Response schema for quota usage."""
    id: str
    user_id: str
    billing_month: str
    task_count: int
    api_call_count: int
    compute_minutes_used: float
    quota_exceeded: bool
    created_at: str
    updated_at: str


class RateLimitLogResponse(BaseModel):
    """Response schema for rate limit logs."""
    id: str
    user_id: str
    endpoint: str
    method: str
    requests_in_window: int
    rate_limit_rps: int
    exceeded: bool
    status_code: int
    response_time_ms: float
    timestamp: str


class UsageAnalyticsResponse(BaseModel):
    """Usage analytics summary."""
    total_users: int
    total_quotas_exceeded: int
    avg_rate_limit_violations: float
    top_quota_consumers: List[dict]
    rate_limit_violations_last_24h: int
    quota_exceeded_alerts_last_24h: int


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

@router.get("/quotas/{user_id}", response_model=UserQuotaResponse)
def get_user_quota(
    user_id: str,
    db: Session = Depends(get_db),
):
    """Get quota configuration for a user."""
    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")
    return quota.to_dict()


@router.put("/quotas/{user_id}", response_model=UserQuotaResponse)
def update_user_quota(
    user_id: str,
    update: UserQuotaUpdate,
    db: Session = Depends(get_db),
):
    """Update quota configuration for a user."""
    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")
    
    # Update tier if provided
    if update.tier:
        try:
            quota.tier = PricingTier[update.tier.upper()]
            # Apply tier limits
            tier_limits = get_tier_limits(quota.tier)
            quota.monthly_task_limit = tier_limits["monthly_task_limit"]
            quota.monthly_api_calls_limit = tier_limits["monthly_api_calls_limit"]
            quota.monthly_compute_minutes_limit = tier_limits["monthly_compute_minutes_limit"]
            quota.rate_limit_rps = tier_limits["rate_limit_rps"]
            quota.rate_limit_burst = tier_limits["rate_limit_burst"]
        except KeyError:
            raise HTTPException(status_code=400, detail="Invalid tier")
    
    # Update individual limits if provided
    if update.monthly_task_limit is not None:
        quota.monthly_task_limit = update.monthly_task_limit
    if update.monthly_api_calls_limit is not None:
        quota.monthly_api_calls_limit = update.monthly_api_calls_limit
    if update.monthly_compute_minutes_limit is not None:
        quota.monthly_compute_minutes_limit = update.monthly_compute_minutes_limit
    if update.rate_limit_rps is not None:
        quota.rate_limit_rps = update.rate_limit_rps
    if update.rate_limit_burst is not None:
        quota.rate_limit_burst = update.rate_limit_burst
    if update.alert_threshold_percentage is not None:
        quota.alert_threshold_percentage = update.alert_threshold_percentage
    if update.override_rate_limit is not None:
        quota.override_rate_limit = update.override_rate_limit
    if update.override_quota is not None:
        quota.override_quota = update.override_quota
    
    quota.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(quota)
    return quota.to_dict()


@router.post("/quotas/{user_id}/override")
def set_quota_override(
    user_id: str,
    override: QuotaOverride,
    db: Session = Depends(get_db),
):
    """Set admin override for rate limit or quota."""
    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")
    
    if override.override_type == "rate_limit":
        quota.override_rate_limit = override.enabled
    elif override.override_type == "quota":
        quota.override_quota = override.enabled
    else:
        raise HTTPException(status_code=400, detail="Invalid override type")
    
    quota.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(quota)
    
    return {
        "user_id": user_id,
        "override_type": override.override_type,
        "enabled": override.enabled,
        "reason": override.reason,
    }


@router.get("/usage/{user_id}", response_model=QuotaUsageResponse)
def get_user_usage(
    user_id: str,
    billing_month: Optional[str] = Query(None, description="YYYY-MM format"),
    db: Session = Depends(get_db),
):
    """Get quota usage for a user."""
    if not billing_month:
        billing_month = datetime.now(timezone.utc).strftime("%Y-%m")
    
    usage = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user_id,
        QuotaUsage.billing_month == billing_month,
    ).first()
    
    if not usage:
        raise HTTPException(status_code=404, detail="Usage record not found")
    
    return usage.to_dict()


@router.get("/usage/{user_id}/history", response_model=List[QuotaUsageResponse])
def get_user_usage_history(
    user_id: str,
    limit: int = Query(12, ge=1, le=100, description="Number of months to retrieve"),
    db: Session = Depends(get_db),
):
    """Get quota usage history for a user."""
    usages = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user_id,
    ).order_by(desc(QuotaUsage.billing_month)).limit(limit).all()
    
    return [u.to_dict() for u in usages]


@router.get("/rate-limits/logs", response_model=List[RateLimitLogResponse])
def get_rate_limit_logs(
    user_id: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=720, description="Hours to retrieve"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get rate limit logs."""
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    
    query = db.query(RateLimitLog).filter(
        RateLimitLog.timestamp >= cutoff_time,
    )
    
    if user_id:
        query = query.filter(RateLimitLog.user_id == user_id)
    
    logs = query.order_by(desc(RateLimitLog.timestamp)).limit(limit).all()
    
    return [log.to_dict() for log in logs]


@router.get("/analytics", response_model=UsageAnalyticsResponse)
def get_usage_analytics(
    db: Session = Depends(get_db),
):
    """Get overall usage analytics."""
    # Get current billing month
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    
    # Total users
    total_users = db.query(UserQuota).count()
    
    # Total quotas exceeded
    total_quotas_exceeded = db.query(QuotaUsage).filter(
        QuotaUsage.quota_exceeded == True,
        QuotaUsage.billing_month == current_month,
    ).count()
    
    # Rate limit violations last 24h
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    rate_limit_violations_24h = db.query(RateLimitLog).filter(
        RateLimitLog.exceeded == True,
        RateLimitLog.timestamp >= cutoff_time,
    ).count()
    
    # Quota exceeded alerts last 24h
    quota_alerts_24h = db.query(RateLimitLog).filter(
        RateLimitLog.quota_exceeded == True,
        RateLimitLog.timestamp >= cutoff_time,
    ).count()
    
    # Average rate limit violations per user
    avg_violations = (
        rate_limit_violations_24h / total_users
        if total_users > 0
        else 0
    )
    
    # Top quota consumers (by API calls)
    top_consumers = []
    top_usages = db.query(QuotaUsage).filter(
        QuotaUsage.billing_month == current_month,
    ).order_by(desc(QuotaUsage.api_call_count)).limit(10).all()
    
    for usage in top_usages:
        quota = db.query(UserQuota).filter(
            UserQuota.user_id == usage.user_id
        ).first()
        if quota:
            top_consumers.append({
                "user_id": usage.user_id,
                "tier": quota.tier.value,
                "api_calls": usage.api_call_count,
                "tasks": usage.task_count,
                "compute_minutes": usage.compute_minutes_used,
            })
    
    return {
        "total_users": total_users,
        "total_quotas_exceeded": total_quotas_exceeded,
        "avg_rate_limit_violations": avg_violations,
        "top_quota_consumers": top_consumers,
        "rate_limit_violations_last_24h": rate_limit_violations_24h,
        "quota_exceeded_alerts_last_24h": quota_alerts_24h,
    }
