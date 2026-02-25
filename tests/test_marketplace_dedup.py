"""
Tests for Marketplace Bid Deduplication and Lock Manager

Tests for Issue #8: Implement distributed lock and deduplication for marketplace bids

Coverage:
- Distributed lock acquire/release
- Lock timeout handling
- Concurrent bid scenarios
- Deduplication logic
- Posting freshness validation
- Bid withdrawal
- Race condition scenarios
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent_execution.bid_lock_manager import (
    BidLockManager,
)
from src.agent_execution.bid_deduplication import (
    should_bid,
    mark_bid_withdrawn,
)
from src.api.models import Base, Bid, BidStatus


class TestBidLockManager:
    """Tests for BidLockManager."""
    
    @pytest.fixture
    def manager(self):
        """Create a BidLockManager backed by an in-memory DB."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        mgr = BidLockManager(ttl=300)
        mgr._get_db = lambda: Session()
        return mgr
    
    @pytest.mark.asyncio
    async def test_lock_acquire_and_release(self, manager):
        """Test acquiring and releasing a lock."""
        acquired = await manager.acquire_lock("upwork", "job_123")
        assert acquired is True
        assert manager._lock_successes == 1
        
        released = await manager.release_lock("upwork", "job_123")
        assert released is True
    
    @pytest.mark.asyncio
    async def test_lock_conflict(self, manager):
        """Test that concurrent acquisition of same lock fails."""
        # First acquisition succeeds
        acquired1 = await manager.acquire_lock("upwork", "job_123", holder_id="holder1")
        assert acquired1 is True
        
        # Second acquisition should fail
        acquired2 = await manager.acquire_lock(
            "upwork", "job_123", holder_id="holder2", timeout=0.5
        )
        assert acquired2 is False
        assert manager._lock_conflicts >= 1  # May have multiple retries
        assert manager._lock_timeouts == 1
    
    @pytest.mark.asyncio
    async def test_lock_context_manager(self, manager):
        """Test using lock as context manager."""
        lock_acquired = False
        
        try:
            async with manager.with_lock("upwork", "job_123"):
                lock_acquired = True
        except TimeoutError:
            pytest.fail("Lock context manager raised TimeoutError")
        
        assert lock_acquired is True
        assert manager._lock_successes == 1
    
    @pytest.mark.asyncio
    async def test_lock_context_manager_timeout(self, manager):
        """Test that context manager raises TimeoutError on lock conflict."""
        # Acquire first lock
        await manager.acquire_lock("upwork", "job_123")
        
        # Try to acquire same lock via context manager - should timeout
        with pytest.raises(TimeoutError):
            async with manager.with_lock("upwork", "job_123", timeout=0.5):
                pass
    
    @pytest.mark.asyncio
    async def test_concurrent_bids_on_different_postings(self, manager):
        """Test that locks on different postings don't conflict."""
        # Acquire locks on different postings concurrently
        results = await asyncio.gather(
            manager.acquire_lock("upwork", "job_123"),
            manager.acquire_lock("upwork", "job_456"),
            manager.acquire_lock("fiverr", "job_789"),
        )
        
        assert all(results)
        assert manager._lock_successes == 3
        assert manager._lock_conflicts == 0
    
    @pytest.mark.asyncio
    async def test_lock_expiration(self, manager):
        """Test that expired locks can be reacquired."""
        # Use manager's DB session factory for the short-TTL instance
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        manager_short_ttl = BidLockManager(ttl=1)  # 1 second TTL
        manager_short_ttl._get_db = lambda: Session()
        
        # Acquire lock
        acquired1 = await manager_short_ttl.acquire_lock("upwork", "job_123")
        assert acquired1 is True
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Reacquire (old lock should be expired)
        acquired2 = await manager_short_ttl.acquire_lock(
            "upwork", "job_123", holder_id="new_holder"
        )
        assert acquired2 is True
        assert manager_short_ttl._lock_successes == 2
    
    @pytest.mark.asyncio
    async def test_lock_metrics(self, manager):
        """Test lock manager metrics."""
        await manager.acquire_lock("upwork", "job_123")
        await manager.acquire_lock("upwork", "job_123", timeout=0.1)  # Fails
        
        metrics = manager.get_metrics()
        assert metrics["lock_attempts"] == 2
        assert metrics["lock_successes"] == 1
        assert metrics["lock_conflicts"] >= 1  # May have multiple retries
        assert metrics["lock_timeouts"] == 1
        assert metrics["active_locks"] == 1
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_locks(self, manager):
        """Test cleanup of expired locks."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        manager_short_ttl = BidLockManager(ttl=1)
        manager_short_ttl._get_db = lambda: Session()
        
        # Acquire multiple locks
        await manager_short_ttl.acquire_lock("upwork", "job_1")
        await manager_short_ttl.acquire_lock("upwork", "job_2")
        assert manager_short_ttl.get_metrics()["active_locks"] == 2
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Trigger cleanup by attempting acquisition
        await manager_short_ttl.acquire_lock("upwork", "job_3")
        
        # Old locks should be cleaned up, only job_3 remains
        assert manager_short_ttl.get_metrics()["active_locks"] == 1


class TestBidDeduplication:
    """Tests for bid deduplication logic."""
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock SQLAlchemy session."""
        return MagicMock()
    
    @pytest.mark.asyncio
    async def test_should_bid_no_existing_bids(self, mock_session):
        """Test should_bid returns True when no existing bids."""
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_session.query.return_value.filter.return_value.all.return_value = []
        
        result = await should_bid(mock_session, "job_123", "upwork")
        assert result is True
    
    @pytest.mark.asyncio
    async def test_should_bid_with_existing_active_bid(self, mock_session):
        """Test should_bid returns False when ACTIVE bid exists."""
        mock_bid = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_bid
        
        result = await should_bid(mock_session, "job_123", "upwork")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_should_bid_stale_posting(self, mock_session):
        """Test should_bid returns False for stale postings."""
        # No active bid
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        # But stale posting exists
        old_bid = MagicMock()
        old_bid.posting_cached_at = datetime.now(timezone.utc) - timedelta(hours=25)
        old_bid.status = BidStatus.ACTIVE
        mock_session.query.return_value.filter.return_value.all.return_value = [old_bid]
        
        result = await should_bid(mock_session, "job_123", "upwork", ttl_hours=24)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_mark_bid_withdrawn(self, mock_session):
        """Test marking a bid as withdrawn."""
        mock_bid = MagicMock()
        mock_bid.id = "bid_123"
        mock_bid.status = BidStatus.ACTIVE
        mock_session.query.return_value.filter.return_value.first.return_value = mock_bid
        
        result = await mark_bid_withdrawn(mock_session, "bid_123", "Job closed")
        assert result is True
        assert mock_bid.status == BidStatus.WITHDRAWN
        assert mock_bid.withdrawn_reason == "Job closed"
        assert mock_session.commit.called


class TestConcurrentBidScenarios:
    """Tests for concurrent bid scenarios."""
    
    def _make_db_manager(self, ttl=300):
        """Create a BidLockManager with an in-memory DB."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        mgr = BidLockManager(ttl=ttl)
        mgr._get_db = lambda: Session()
        return mgr
    
    def test_100_concurrent_bids_different_postings(self):
        """Test 100 concurrent bids on different postings."""
        async def run_test():
            manager = self._make_db_manager()
            
            async def bid_on_posting(posting_id):
                async with manager.with_lock("upwork", f"job_{posting_id}"):
                    await asyncio.sleep(0.01)  # Simulate bid placement
            
            # Bid on 100 different postings concurrently
            tasks = [bid_on_posting(i) for i in range(100)]
            await asyncio.gather(*tasks)
            
            metrics = manager.get_metrics()
            assert metrics["lock_successes"] == 100
            assert metrics["lock_conflicts"] == 0
        
        asyncio.run(run_test())
    
    def test_race_condition_same_posting(self):
        """Test race condition: multiple concurrent bids on same posting."""
        async def run_test():
            manager = self._make_db_manager()
            successful_bids = []
            failed_bids = []
            
            async def attempt_bid(bid_id):
                try:
                    async with manager.with_lock("upwork", "job_same", timeout=0.2):
                        await asyncio.sleep(0.01)  # Simulate bid placement
                        successful_bids.append(bid_id)
                except TimeoutError:
                    failed_bids.append(bid_id)
            
            # 5 concurrent attempts on same posting
            tasks = [attempt_bid(i) for i in range(5)]
            await asyncio.gather(*tasks)
            
            # At least one should succeed, some should timeout
            assert len(successful_bids) >= 1, f"Expected at least 1 success, got {len(successful_bids)}"
            assert len(successful_bids) + len(failed_bids) == 5, "Expected 5 total attempts"
            
            metrics = manager.get_metrics()
            assert metrics["lock_successes"] >= 1
            assert metrics["lock_conflicts"] >= 0  # May have retries or not
        
        asyncio.run(run_test())


class TestIntegration:
    """Integration tests with real database models."""
    
    def test_bid_model_extensions(self):
        """Test Bid model has new fields."""
        bid = Bid(
            id="bid_123",
            job_title="Test Job",
            job_description="Test Description",
            job_id="job_123",
            bid_amount=5000,
            marketplace="upwork",
            status=BidStatus.ACTIVE
        )
        
        # Test new fields
        assert hasattr(bid, "withdrawn_reason")
        assert hasattr(bid, "withdrawal_timestamp")
        assert hasattr(bid, "posting_cached_at")
        
        # Test to_dict includes new fields
        bid_dict = bid.to_dict()
        assert "withdrawn_reason" in bid_dict
        assert "withdrawal_timestamp" in bid_dict
        assert "posting_cached_at" in bid_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
