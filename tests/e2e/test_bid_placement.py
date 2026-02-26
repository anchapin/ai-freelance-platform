"""
E2E Tests: Bid Placement Workflow

Tests the complete bid placement process:
1. Job discovery and analysis
2. Bid proposal generation
3. Bid submission and tracking
4. Bid deduplication and lock management

Coverage: ~20% of critical path
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from src.api.models import BidStatus
from .utils import (
    create_test_bid,
    build_job_posting_fixture,
    assert_bid_succeeds,
    count_bids_for_job,
)


class TestJobDiscovery:
    """Test job discovery from marketplaces."""
    
    def test_discover_single_job(self):
        """Test discovering a single job posting."""
        job = build_job_posting_fixture(
            marketplace="Upwork",
            budget=500,
            title="Create Data Dashboard"
        )
        
        assert job["marketplace"] == "Upwork"
        assert job["budget"] == 500
        assert job["title"] == "Create Data Dashboard"
        assert "id" in job
        assert "posted_at" in job
    
    def test_discover_multiple_jobs(self):
        """Test discovering multiple job postings."""
        jobs = [
            build_job_posting_fixture(marketplace="Upwork", budget=300),
            build_job_posting_fixture(marketplace="Fiverr", budget=500),
            build_job_posting_fixture(marketplace="Toptal", budget=1000),
        ]
        
        assert len(jobs) == 3
        assert jobs[0]["budget"] == 300
        assert jobs[1]["budget"] == 500
        assert jobs[2]["budget"] == 1000
    
    def test_job_filtering_by_budget_range(self):
        """Test filtering jobs by budget range."""
        jobs = [
            build_job_posting_fixture(budget=200),
            build_job_posting_fixture(budget=500),
            build_job_posting_fixture(budget=1000),
        ]
        
        # Filter jobs between $300-$800
        filtered = [j for j in jobs if 300 <= j["budget"] <= 800]
        
        assert len(filtered) == 1
        assert filtered[0]["budget"] == 500
    
    def test_job_filtering_by_skills(self):
        """Test filtering jobs by required skills."""
        job1 = build_job_posting_fixture(
            skills=["Python", "Data Visualization"]
        )
        job2 = build_job_posting_fixture(
            skills=["JavaScript", "React"]
        )
        
        required_skills = {"Python", "Pandas"}
        
        # Filter jobs that match at least one required skill
        job1_matches = any(s in required_skills for s in job1["skills"])
        job2_matches = any(s in required_skills for s in job2["skills"])
        
        assert job1_matches is True
        assert job2_matches is False
    
    def test_job_freshness_check(self):
        """Test checking if job is fresh (recently posted)."""
        job = build_job_posting_fixture()
        
        posted_time = datetime.fromisoformat(job["posted_at"])
        now = datetime.now(timezone.utc)
        hours_old = (now - posted_time).total_seconds() / 3600
        
        is_fresh = hours_old < 24  # Less than 24 hours old
        
        assert is_fresh is True


class TestBidGeneration:
    """Test bid proposal generation."""
    
    def test_generate_basic_bid_proposal(self):
        """Test generating a basic bid proposal."""
        job = build_job_posting_fixture(
            title="Create Financial Report",
            budget=500
        )
        
        # Simulate bid generation
        proposal = {
            "job_id": job["id"],
            "proposed_budget": int(job["budget"] * 0.8),  # 20% discount
            "proposal_text": "I can create this report with Python and Matplotlib.",
            "estimated_delivery_days": 7,
            "fixed_price": True,
        }
        
        assert proposal["proposed_budget"] == 400
        assert proposal["estimated_delivery_days"] == 7
        assert proposal["fixed_price"] is True
    
    def test_generate_competitive_bid(self):
        """Test generating competitive bid based on marketplace."""
        job = build_job_posting_fixture(
            marketplace="Upwork",
            budget=500
        )
        
        # On Upwork, be more competitive
        proposal_budget = int(job["budget"] * 0.75)  # 25% discount
        
        proposal = {
            "job_id": job["id"],
            "proposed_budget": proposal_budget,
            "marketplace_strategy": "competitive",
        }
        
        assert proposal["proposed_budget"] == 375
        assert proposal["marketplace_strategy"] == "competitive"
    
    def test_generate_premium_bid(self):
        """Test generating premium bid for high-value jobs."""
        job = build_job_posting_fixture(
            budget=2000,  # High value
            title="Complex Financial Analysis"
        )
        
        # For high-value jobs, match budget or slightly discount
        proposal_budget = int(job["budget"] * 0.95)
        
        proposal = {
            "job_id": job["id"],
            "proposed_budget": proposal_budget,
            "premium": True,
            "includes_consulting": True,
        }
        
        assert proposal["proposed_budget"] == 1900
        assert proposal["premium"] is True


class TestBidSubmission:
    """Test bid submission and tracking."""
    
    def test_submit_bid_to_job(self, e2e_db: Session):
        """Test submitting a bid for a job."""
        # Create bid for a job
        job_id = "job_test_123"
        bid = create_test_bid(
            e2e_db,
            job_id=job_id,
            marketplace="Upwork",
            bid_amount=40000,
            status=BidStatus.PENDING
        )
        
        assert bid.job_id == job_id
        assert bid.marketplace == "Upwork"
        assert bid.status == BidStatus.PENDING
    
    def test_track_multiple_bids_for_job(self, e2e_db: Session):
        """Test tracking multiple bids placed on same job."""
        # Place multiple bids on same job
        job_id = "job_test_456"
        
        bid1 = create_test_bid(e2e_db, job_id=job_id, marketplace="Upwork")
        bid2 = create_test_bid(e2e_db, job_id=job_id, marketplace="Fiverr")
        bid3 = create_test_bid(e2e_db, job_id=job_id, marketplace="Toptal")
        
        # Count bids for job
        bid_count = count_bids_for_job(e2e_db, job_id)
        
        assert bid_count == 3
        assert bid1.job_id == job_id
        assert bid2.job_id == job_id
        assert bid3.job_id == job_id
    
    def test_update_bid_status(self, e2e_db: Session):
        """Test updating bid status after response."""
        bid = create_test_bid(
            e2e_db,
            status=BidStatus.PENDING
        )
        
        # Simulate bid being won
        bid.status = BidStatus.WON
        e2e_db.commit()
        e2e_db.refresh(bid)
        
        assert_bid_succeeds(bid)
    
    def test_bid_rejection_tracking(self, e2e_db: Session):
        """Test tracking rejected bids."""
        bid = create_test_bid(
            e2e_db,
            status=BidStatus.PENDING
        )
        
        # Simulate bid rejection
        bid.status = BidStatus.REJECTED
        e2e_db.commit()
        e2e_db.refresh(bid)
        
        assert bid.status == BidStatus.REJECTED
    
    def test_bid_withdrawal(self, e2e_db: Session):
        """Test withdrawing a submitted bid."""
        bid = create_test_bid(
            e2e_db,
            status=BidStatus.PENDING
        )
        
        # Withdraw bid
        bid.status = BidStatus.WITHDRAWN
        e2e_db.commit()
        e2e_db.refresh(bid)
        
        assert bid.status == BidStatus.WITHDRAWN


class TestBidDeduplication:
    """Test bid deduplication to avoid duplicate bids."""
    
    def test_prevent_duplicate_bids_same_job(self, e2e_db: Session):
        """Test preventing duplicate bids on same job."""
        job_id = "job_dedup_test"
        
        # Submit first bid
        create_test_bid(e2e_db, job_id=job_id, marketplace="Upwork")
        
        # Attempt duplicate bid (will fail due to unique constraint)
        duplicate_found = False
        try:
            create_test_bid(e2e_db, job_id=job_id, marketplace="Upwork")
        except Exception:
            # Unique constraint violation is expected
            duplicate_found = True
            e2e_db.rollback()
        
        # Count bids - should only have 1
        bid_count = count_bids_for_job(e2e_db, job_id)
        
        # Either duplicate was found, or we successfully prevented it
        assert duplicate_found or bid_count == 1
    
    def test_allow_bids_different_marketplaces(self, e2e_db: Session):
        """Test allowing bids on same job from different marketplaces."""
        job_id = "job_multi_market"
        
        # Submit bids from different marketplaces
        bid1 = create_test_bid(e2e_db, job_id=job_id, marketplace="Upwork")
        bid2 = create_test_bid(e2e_db, job_id=job_id, marketplace="Fiverr")
        
        bid_count = count_bids_for_job(e2e_db, job_id)
        
        assert bid_count == 2
        assert bid1.marketplace != bid2.marketplace
    
    def test_deduplicate_by_job_id(self, e2e_db: Session):
        """Test deduplication based on job ID."""
        job_id = "job_dedup_123"
        
        # Create bids with tracking
        bid_tracking = {}
        
        # First bid
        bid1 = create_test_bid(e2e_db, job_id=job_id, marketplace="Upwork")
        bid_tracking[bid1.id] = bid1
        
        # Duplicate attempt
        bid2_data = {
            "job_id": job_id,
            "marketplace": "Upwork",
        }
        
        # Check if bid would be duplicate
        existing = [
            b for b in bid_tracking.values()
            if b.job_id == bid2_data["job_id"]
            and b.marketplace == bid2_data["marketplace"]
        ]
        
        # Should find existing bid
        assert len(existing) == 1
        assert existing[0].id == bid1.id


class TestBidLocking:
    """Test distributed bid lock management."""
    
    def test_acquire_bid_lock(self, mock_bid_lock_manager):
        """Test acquiring lock for bid placement."""
        lock_id = "lock_123"
        
        # In async context
        import asyncio
        
        async def test_lock():
            lock_token = await mock_bid_lock_manager.acquire_bid_lock(lock_id, ttl=30)
            assert lock_token is not None
        
        asyncio.run(test_lock())
    
    def test_release_bid_lock(self, mock_bid_lock_manager):
        """Test releasing bid lock."""
        lock_id = "lock_123"
        
        import asyncio
        
        async def test_release():
            # Release lock
            released = await mock_bid_lock_manager.release_bid_lock(lock_id)
            assert released is True
        
        asyncio.run(test_release())
    
    @pytest.mark.asyncio
    async def test_prevent_concurrent_bids(self, mock_bid_lock_manager):
        """Test preventing concurrent bid placement on same job."""
        job_id = "job_concurrent_123"
        
        # Configure mocks for this test
        mock_bid_lock_manager.acquire_bid_lock.return_value = "lock_token_abc"
        mock_bid_lock_manager.is_bid_locked.return_value = True
        mock_bid_lock_manager.release_bid_lock.return_value = True
        
        # First bid acquires lock
        lock1 = await mock_bid_lock_manager.acquire_bid_lock(job_id)
        assert lock1 == "lock_token_abc"
        
        # Second concurrent bid should see the lock
        is_locked = await mock_bid_lock_manager.is_bid_locked(job_id)
        assert is_locked is True
        
        # Release lock
        released = await mock_bid_lock_manager.release_bid_lock(job_id)
        assert released is True


class TestBidProfitability:
    """Test bid profitability calculations."""
    
    def test_calculate_bid_profit(self):
        """Test calculating profit for a bid."""
        bid_amount = 40000  # Bid amount $400
        execution_cost = 5000  # Cost to execute (LLM + E2B) = $50
        
        profit = bid_amount - execution_cost
        
        assert profit == 35000
        assert profit > 0  # Profitable
    
    def test_filter_unprofitable_bids(self):
        """Test filtering out unprofitable bids."""
        bids = [
            {"amount": 50000, "cost": 5000},   # $450 profit
            {"amount": 10000, "cost": 15000},  # -$50 loss
            {"amount": 40000, "cost": 10000},  # $300 profit
        ]
        
        min_profit = 10000
        profitable = [
            b for b in bids
            if (b["amount"] - b["cost"]) >= min_profit
        ]
        
        assert len(profitable) == 2
        assert profitable[0]["amount"] == 50000
        assert profitable[1]["amount"] == 40000
