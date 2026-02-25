"""
Tests for Issue #45: API Rate Limiting, Quotas, and Usage Analytics.

Tests cover:
- Redis-backed rate limiting with sliding window
- Burst capacity handling
- Monthly quota enforcement (tasks, API calls, compute)
- Pricing tier limits (Free, Pro, Enterprise)
- 429 (Too Many Requests) and 402 (Payment Required) status codes
- Threshold alerts (80%, 100%)
- Admin panel functionality
- Rate limit logging and analytics
"""

import pytest
import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = Mock()
    mock.incr = Mock(side_effect=[1, 2, 3, 4, 5])
    mock.expire = Mock()
    mock.decr = Mock()
    mock.ping = Mock()
    return mock


@pytest.fixture
def db_with_quotas():
    """Create test database with quota records."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.api.models import Base, UserQuota, PricingTier
    from datetime import datetime, timezone, timedelta
    
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Create test quotas
    free_quota = UserQuota(
        user_id="free_user@example.com",
        tier=PricingTier.FREE,
        monthly_task_limit=10,
        monthly_api_calls_limit=100,
        monthly_compute_minutes_limit=60,
        rate_limit_rps=10,
        rate_limit_burst=50,
        billing_cycle_start=datetime.now(timezone.utc),
        billing_cycle_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    
    pro_quota = UserQuota(
        user_id="pro_user@example.com",
        tier=PricingTier.PRO,
        monthly_task_limit=1000,
        monthly_api_calls_limit=10000,
        monthly_compute_minutes_limit=600,
        rate_limit_rps=50,
        rate_limit_burst=200,
        billing_cycle_start=datetime.now(timezone.utc),
        billing_cycle_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    
    enterprise_quota = UserQuota(
        user_id="enterprise_user@example.com",
        tier=PricingTier.ENTERPRISE,
        monthly_task_limit=999999999,
        monthly_api_calls_limit=999999999,
        monthly_compute_minutes_limit=999999999,
        rate_limit_rps=1000,
        rate_limit_burst=5000,
        billing_cycle_start=datetime.now(timezone.utc),
        billing_cycle_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    
    session.add_all([free_quota, pro_quota, enterprise_quota])
    session.commit()
    
    yield session
    
    session.close()


@pytest.fixture
def rate_limiter_no_redis():
    """Rate limiter without Redis (in-memory fallback)."""
    from src.api.rate_limiter import RateLimiter
    return RateLimiter(redis_client=None)


@pytest.fixture
def quota_manager():
    """QuotaManager instance."""
    from src.api.rate_limiter import QuotaManager
    return QuotaManager()


# ============================================================================
# TESTS: RATE LIMITING
# ============================================================================

class TestRateLimiting:
    """Tests for rate limiting functionality."""
    
    def test_rate_limit_within_rps(self, rate_limiter_no_redis, db_with_quotas: Session):
        """Test that requests within RPS limit are allowed."""
        quota = db_with_quotas.query(__import__(
            'src.api.models', fromlist=['UserQuota']
        ).UserQuota).filter_by(user_id="free_user@example.com").first()
        
        # First request should be allowed
        allowed, details = rate_limiter_no_redis.is_allowed(
            "free_user@example.com",
            quota,
        )
        
        assert allowed is True
        assert details["allowed"] is True
    
    def test_rate_limit_exceeds_rps(self, rate_limiter_no_redis, db_with_quotas: Session):
        """Test that requests exceeding RPS are blocked."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Simulate multiple requests in same second
        for i in range(quota.rate_limit_rps + 1):
            allowed, details = rate_limiter_no_redis.is_allowed(
                "free_user@example.com",
                quota,
            )
            
            # Should block after RPS limit
            if i >= quota.rate_limit_rps:
                assert allowed is False or (allowed and "burst" in str(details))
    
    def test_burst_capacity(self, rate_limiter_no_redis, db_with_quotas: Session):
        """Test burst capacity exceeding normal RPS."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="pro_user@example.com"
        ).first()
        
        # Burst should allow more requests temporarily
        assert quota.rate_limit_burst > quota.rate_limit_rps
    
    def test_enterprise_unlimited_rate_limit(self, rate_limiter_no_redis, db_with_quotas: Session):
        """Test that Enterprise tier has no rate limiting."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="enterprise_user@example.com"
        ).first()
        
        # Enterprise should always be allowed
        for i in range(1000):
            allowed, details = rate_limiter_no_redis.is_allowed(
                "enterprise_user@example.com",
                quota,
            )
            assert allowed is True
    
    def test_admin_override_rate_limit(self, rate_limiter_no_redis, db_with_quotas: Session):
        """Test admin override bypasses rate limiting."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        quota.override_rate_limit = True
        
        allowed, details = rate_limiter_no_redis.is_allowed(
            "free_user@example.com",
            quota,
            override=False,
        )
        
        assert allowed is True
        assert details["reason"] == "admin_override"


# ============================================================================
# TESTS: QUOTA ENFORCEMENT
# ============================================================================

class TestQuotaEnforcement:
    """Tests for quota enforcement."""
    
    def test_check_task_quota_within_limit(self, quota_manager, db_with_quotas: Session):
        """Test task creation within quota."""
        allowed, details = quota_manager.check_task_quota(
            db_with_quotas,
            "free_user@example.com",
            db_with_quotas.query(__import__(
                'src.api.models', fromlist=['UserQuota']
            ).UserQuota).filter_by(user_id="free_user@example.com").first(),
        )
        
        assert allowed is True
        assert details["remaining"] == 10
    
    def test_check_task_quota_exceeded(self, quota_manager, db_with_quotas: Session):
        """Test task creation beyond quota."""
        from src.api.models import UserQuota, QuotaUsage
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Exceed task quota
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = QuotaUsage(
            user_id="free_user@example.com",
            billing_month=current_month,
            task_count=quota.monthly_task_limit,  # At limit
        )
        db_with_quotas.add(usage)
        db_with_quotas.commit()
        
        allowed, details = quota_manager.check_task_quota(
            db_with_quotas,
            "free_user@example.com",
            quota,
        )
        
        assert allowed is False
        assert details["remaining"] == 0
    
    def test_check_api_quota_within_limit(self, quota_manager, db_with_quotas: Session):
        """Test API calls within quota."""
        from src.api.models import UserQuota
        
        allowed, details = quota_manager.check_api_quota(
            db_with_quotas,
            "free_user@example.com",
            db_with_quotas.query(UserQuota).filter_by(
                user_id="free_user@example.com"
            ).first(),
        )
        
        assert allowed is True
        assert details["remaining"] == 100
    
    def test_check_compute_quota(self, quota_manager, db_with_quotas: Session):
        """Test compute time quota."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Check with 30 minutes requested
        allowed, details = quota_manager.check_compute_quota(
            db_with_quotas,
            "free_user@example.com",
            quota,
            compute_minutes=30.0,
        )
        
        assert allowed is True
        assert details["remaining"] == 60.0  # Total limit: 60 minutes, no usage yet
    
    def test_enterprise_unlimited_quota(self, quota_manager, db_with_quotas: Session):
        """Test that Enterprise tier has unlimited quotas."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="enterprise_user@example.com"
        ).first()
        
        allowed, _ = quota_manager.check_task_quota(
            db_with_quotas,
            "enterprise_user@example.com",
            quota,
        )
        assert allowed is True
        
        allowed, _ = quota_manager.check_api_quota(
            db_with_quotas,
            "enterprise_user@example.com",
            quota,
        )
        assert allowed is True


# ============================================================================
# TESTS: USAGE TRACKING
# ============================================================================

class TestUsageTracking:
    """Tests for quota usage tracking."""
    
    def test_increment_task_count(self, quota_manager, db_with_quotas: Session):
        """Test incrementing task count."""
        usage = quota_manager.increment_task_count(
            db_with_quotas,
            "free_user@example.com",
        )
        
        assert usage.task_count == 1
        assert usage.user_id == "free_user@example.com"
    
    def test_increment_api_calls(self, quota_manager, db_with_quotas: Session):
        """Test incrementing API call count."""
        usage = quota_manager.increment_api_calls(
            db_with_quotas,
            "free_user@example.com",
            count=5,
        )
        
        assert usage.api_call_count == 5
    
    def test_add_compute_time(self, quota_manager, db_with_quotas: Session):
        """Test adding compute time."""
        usage = quota_manager.add_compute_time(
            db_with_quotas,
            "free_user@example.com",
            compute_minutes=15.5,
        )
        
        assert usage.compute_minutes_used == 15.5
    
    def test_get_or_create_usage(self, quota_manager, db_with_quotas: Session):
        """Test getting or creating usage record."""
        # First call creates
        usage1 = quota_manager.get_or_create_usage(
            db_with_quotas,
            "test_user@example.com",
        )
        assert usage1 is not None
        
        # Second call retrieves
        usage2 = quota_manager.get_or_create_usage(
            db_with_quotas,
            "test_user@example.com",
        )
        assert usage2.id == usage1.id


# ============================================================================
# TESTS: THRESHOLD ALERTS
# ============================================================================

class TestThresholdAlerts:
    """Tests for quota threshold alerts."""
    
    def test_80_percent_alert(self, quota_manager, db_with_quotas: Session):
        """Test alert at 80% quota usage."""
        from src.api.models import UserQuota, QuotaUsage
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Create usage at 85%
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = QuotaUsage(
            user_id="free_user@example.com",
            billing_month=current_month,
            task_count=int(quota.monthly_task_limit * 0.85),
            api_call_count=int(quota.monthly_api_calls_limit * 0.85),
        )
        db_with_quotas.add(usage)
        db_with_quotas.commit()
        
        alert = quota_manager.check_threshold_and_alert(
            db_with_quotas,
            "free_user@example.com",
            quota,
            usage,
        )
        
        assert alert is not None
        assert alert["type"] == "quota_80_percent"
    
    def test_100_percent_alert(self, quota_manager, db_with_quotas: Session):
        """Test alert at 100% quota usage."""
        from src.api.models import UserQuota, QuotaUsage
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Create usage at 100%
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = QuotaUsage(
            user_id="free_user@example.com",
            billing_month=current_month,
            task_count=quota.monthly_task_limit,
            api_call_count=quota.monthly_api_calls_limit,
            quota_exceeded=False,
        )
        db_with_quotas.add(usage)
        db_with_quotas.commit()
        
        alert = quota_manager.check_threshold_and_alert(
            db_with_quotas,
            "free_user@example.com",
            quota,
            usage,
        )
        
        assert alert is not None
        assert alert["type"] == "quota_100_percent"
        assert usage.quota_exceeded is True


# ============================================================================
# TESTS: RATE LIMIT LOGGING
# ============================================================================

class TestRateLimitLogging:
    """Tests for rate limit logging."""
    
    def test_log_rate_limit(self, quota_manager, db_with_quotas: Session):
        """Test logging rate limit violations."""
        log = quota_manager.log_rate_limit(
            db_with_quotas,
            user_id="free_user@example.com",
            endpoint="/api/submit-task",
            method="POST",
            requests_in_window=15,
            rate_limit_rps=10,
            exceeded=True,
            status_code=429,
            response_time_ms=45.2,
        )
        
        assert log.exceeded is True
        assert log.status_code == 429
        assert log.requests_in_window == 15
    
    def test_log_quota_exceeded(self, quota_manager, db_with_quotas: Session):
        """Test logging quota exceeded."""
        log = quota_manager.log_rate_limit(
            db_with_quotas,
            user_id="free_user@example.com",
            endpoint="/api/submit-task",
            method="POST",
            requests_in_window=5,
            rate_limit_rps=10,
            exceeded=False,
            status_code=402,
            response_time_ms=30.1,
            quota_type="task",
            quota_used=10,
            quota_limit=10,
            quota_exceeded=True,
        )
        
        assert log.quota_exceeded is True
        assert log.status_code == 402
        assert log.quota_type == "task"


# ============================================================================
# TESTS: PRICING TIERS
# ============================================================================

class TestPricingTiers:
    """Tests for pricing tier limits."""
    
    def test_free_tier_limits(self, db_with_quotas: Session):
        """Test Free tier has correct limits."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        assert quota.monthly_task_limit == 10
        assert quota.monthly_api_calls_limit == 100
        assert quota.monthly_compute_minutes_limit == 60
        assert quota.rate_limit_rps == 10
        assert quota.rate_limit_burst == 50
    
    def test_pro_tier_limits(self, db_with_quotas: Session):
        """Test Pro tier has correct limits."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="pro_user@example.com"
        ).first()
        
        assert quota.monthly_task_limit == 1000
        assert quota.monthly_api_calls_limit == 10000
        assert quota.monthly_compute_minutes_limit == 600
        assert quota.rate_limit_rps == 50
        assert quota.rate_limit_burst == 200
    
    def test_enterprise_tier_limits(self, db_with_quotas: Session):
        """Test Enterprise tier has unlimited limits."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="enterprise_user@example.com"
        ).first()
        
        assert quota.monthly_task_limit == 999999999
        assert quota.monthly_api_calls_limit == 999999999
        assert quota.rate_limit_rps == 1000


# ============================================================================
# TESTS: ADMIN ENDPOINTS
# ============================================================================

class TestAdminEndpoints:
    """Tests for admin quota management endpoints."""
    
    def test_admin_quota_model_update(self, db_with_quotas: Session):
        """Test admin quota updates via model."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Manually update (as if admin did via API)
        quota.monthly_task_limit = 50
        db_with_quotas.commit()
        db_with_quotas.refresh(quota)
        
        assert quota.monthly_task_limit == 50
    
    def test_admin_override_flags(self, db_with_quotas: Session):
        """Test admin override flags."""
        from src.api.models import UserQuota
        
        quota = db_with_quotas.query(UserQuota).filter_by(
            user_id="free_user@example.com"
        ).first()
        
        # Set overrides
        quota.override_rate_limit = True
        quota.override_quota = True
        db_with_quotas.commit()
        db_with_quotas.refresh(quota)
        
        assert quota.override_rate_limit is True
        assert quota.override_quota is True



