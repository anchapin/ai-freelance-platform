"""
Tests for distributed BidLockManager and atomic bid deduplication.

Issue #19: CRITICAL - BidLockManager race condition fix.

Verifies:
- Database-backed distributed locking across processes
- Atomic bid creation prevents duplicates
- Lock expiry and cleanup
- Concurrent lock acquisition (only 1 wins)
- Holder mismatch protection
- Timeout behavior
- Metrics tracking
"""

import asyncio
import time
import pytest
import sys
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.api.models import Base, Bid, BidStatus, DistributedLock
from src.agent_execution.bid_lock_manager import BidLockManager
from src.agent_execution.bid_deduplication import (
    should_bid,
    create_bid_atomically,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create a database session for testing."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def lock_manager(db_engine, monkeypatch):
    """Create a BidLockManager that uses the test database."""
    manager = BidLockManager(ttl=5)

    Session = sessionmaker(bind=db_engine)

    # Patch _get_db to use test database
    monkeypatch.setattr(manager, "_get_db", lambda: Session())

    return manager


# =============================================================================
# DISTRIBUTED LOCK ACQUIRE / RELEASE TESTS
# =============================================================================

class TestDistributedLockAcquireRelease:
    """Test basic lock acquire and release operations."""

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, lock_manager):
        """Test successfully acquiring a lock."""
        result = await lock_manager.acquire_lock("upwork", "job-123", holder_id="scanner-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_release_lock_success(self, lock_manager):
        """Test successfully releasing an acquired lock."""
        await lock_manager.acquire_lock("upwork", "job-123", holder_id="scanner-1")
        result = await lock_manager.release_lock("upwork", "job-123", holder_id="scanner-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_release_nonexistent_lock(self, lock_manager):
        """Test releasing a lock that doesn't exist returns False."""
        result = await lock_manager.release_lock("upwork", "no-such-job", holder_id="scanner-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_release_holder_mismatch(self, lock_manager):
        """Test that only the holder can release the lock."""
        await lock_manager.acquire_lock("upwork", "job-456", holder_id="scanner-1")
        result = await lock_manager.release_lock("upwork", "job-456", holder_id="scanner-2")
        assert result is False

    @pytest.mark.asyncio
    async def test_reacquire_after_release(self, lock_manager):
        """Test acquiring a lock after it has been released."""
        await lock_manager.acquire_lock("upwork", "job-789", holder_id="scanner-1")
        await lock_manager.release_lock("upwork", "job-789", holder_id="scanner-1")
        result = await lock_manager.acquire_lock("upwork", "job-789", holder_id="scanner-2")
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_invalid_marketplace(self, lock_manager):
        """Test that empty marketplace_id raises ValueError."""
        with pytest.raises(ValueError):
            await lock_manager.acquire_lock("", "job-123", holder_id="scanner-1")

    @pytest.mark.asyncio
    async def test_acquire_invalid_posting(self, lock_manager):
        """Test that empty posting_id raises ValueError."""
        with pytest.raises(ValueError):
            await lock_manager.acquire_lock("upwork", "", holder_id="scanner-1")


# =============================================================================
# LOCK CONFLICT AND TIMEOUT TESTS
# =============================================================================

class TestLockConflictAndTimeout:
    """Test lock conflicts and timeout behavior."""

    @pytest.mark.asyncio
    async def test_conflict_second_holder_blocked(self, lock_manager):
        """Test that a second holder cannot acquire the same lock."""
        await lock_manager.acquire_lock("upwork", "job-100", holder_id="scanner-1")
        result = await lock_manager.acquire_lock(
            "upwork", "job-100", holder_id="scanner-2", timeout=0.3
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_increments_metric(self, lock_manager):
        """Test that timeout increments the lock_timeouts metric."""
        await lock_manager.acquire_lock("upwork", "job-200", holder_id="scanner-1")
        await lock_manager.acquire_lock(
            "upwork", "job-200", holder_id="scanner-2", timeout=0.2
        )
        metrics = lock_manager.get_metrics()
        assert metrics["lock_timeouts"] >= 1

    @pytest.mark.asyncio
    async def test_different_postings_no_conflict(self, lock_manager):
        """Test that locks on different postings don't conflict."""
        r1 = await lock_manager.acquire_lock("upwork", "job-A", holder_id="scanner-1")
        r2 = await lock_manager.acquire_lock("upwork", "job-B", holder_id="scanner-1")
        assert r1 is True
        assert r2 is True

    @pytest.mark.asyncio
    async def test_different_marketplaces_no_conflict(self, lock_manager):
        """Test that locks on different marketplaces don't conflict."""
        r1 = await lock_manager.acquire_lock("upwork", "job-1", holder_id="scanner-1")
        r2 = await lock_manager.acquire_lock("fiverr", "job-1", holder_id="scanner-1")
        assert r1 is True
        assert r2 is True


# =============================================================================
# LOCK EXPIRY TESTS
# =============================================================================

class TestLockExpiry:
    """Test lock expiry and automatic cleanup."""

    @pytest.mark.asyncio
    async def test_expired_lock_can_be_reacquired(self, db_engine, monkeypatch):
        """Test that an expired lock is automatically replaced."""
        manager = BidLockManager(ttl=1)  # 1-second TTL
        Session = sessionmaker(bind=db_engine)
        monkeypatch.setattr(manager, "_get_db", lambda: Session())

        await manager.acquire_lock("upwork", "job-exp", holder_id="scanner-1")

        # Wait for lock to expire
        await asyncio.sleep(1.1)

        result = await manager.acquire_lock("upwork", "job-exp", holder_id="scanner-2")
        assert result is True

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_locks(self, db_engine, monkeypatch):
        """Test that cleanup_all removes all locks."""
        manager = BidLockManager(ttl=5)
        Session = sessionmaker(bind=db_engine)
        monkeypatch.setattr(manager, "_get_db", lambda: Session())

        await manager.acquire_lock("upwork", "job-c1", holder_id="s1")
        await manager.acquire_lock("upwork", "job-c2", holder_id="s1")

        await manager.cleanup_all()

        # Both locks should now be free
        r1 = await manager.acquire_lock("upwork", "job-c1", holder_id="s2")
        r2 = await manager.acquire_lock("upwork", "job-c2", holder_id="s2")
        assert r1 is True
        assert r2 is True


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestWithLockContextManager:
    """Test the with_lock async context manager."""

    @pytest.mark.asyncio
    async def test_with_lock_acquires_and_releases(self, lock_manager):
        """Test that with_lock properly acquires and releases."""
        async with lock_manager.with_lock("upwork", "job-ctx", holder_id="s1"):
            # Lock should be held during the block
            result = await lock_manager.acquire_lock(
                "upwork", "job-ctx", holder_id="s2", timeout=0.2
            )
            assert result is False

        # Lock should be released after the block
        result = await lock_manager.acquire_lock("upwork", "job-ctx", holder_id="s2")
        assert result is True

    @pytest.mark.asyncio
    async def test_with_lock_releases_on_exception(self, lock_manager):
        """Test that with_lock releases the lock even on exception."""
        with pytest.raises(RuntimeError):
            async with lock_manager.with_lock("upwork", "job-err", holder_id="s1"):
                raise RuntimeError("intentional error")

        # Lock should still be released
        result = await lock_manager.acquire_lock("upwork", "job-err", holder_id="s2")
        assert result is True

    @pytest.mark.asyncio
    async def test_with_lock_timeout_raises(self, lock_manager):
        """Test that with_lock raises TimeoutError when lock unavailable."""
        await lock_manager.acquire_lock("upwork", "job-to", holder_id="s1")

        with pytest.raises(TimeoutError):
            async with lock_manager.with_lock(
                "upwork", "job-to", holder_id="s2", timeout=0.2
            ):
                pass  # pragma: no cover


# =============================================================================
# CONCURRENT LOCK TESTS (simulate multi-instance)
# =============================================================================

class TestConcurrentLockAcquisition:
    """Test that only one of N concurrent acquire calls succeeds."""

    @pytest.mark.asyncio
    async def test_10_concurrent_acquires_only_1_wins(self, db_engine, monkeypatch):
        """
        Simulate 10 concurrent scanner instances trying to lock the same posting.
        Only 1 should succeed.
        """
        managers = []
        Session = sessionmaker(bind=db_engine)
        for i in range(10):
            m = BidLockManager(ttl=30)
            monkeypatch.setattr(m, "_get_db", lambda: Session())
            managers.append(m)

        results = await asyncio.gather(*[
            m.acquire_lock("upwork", "hot-job", holder_id=f"scanner-{i}", timeout=0.5)
            for i, m in enumerate(managers)
        ])

        winners = [r for r in results if r is True]
        losers = [r for r in results if r is False]

        assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"
        assert len(losers) == 9

    @pytest.mark.asyncio
    async def test_concurrent_different_postings_all_succeed(self, db_engine, monkeypatch):
        """Test that 10 instances locking different postings all succeed."""
        managers = []
        Session = sessionmaker(bind=db_engine)
        for i in range(10):
            m = BidLockManager(ttl=30)
            monkeypatch.setattr(m, "_get_db", lambda: Session())
            managers.append(m)

        results = await asyncio.gather(*[
            m.acquire_lock("upwork", f"job-{i}", holder_id=f"scanner-{i}", timeout=1.0)
            for i, m in enumerate(managers)
        ])

        assert all(r is True for r in results)


# =============================================================================
# METRICS TESTS
# =============================================================================

class TestLockMetrics:
    """Test lock manager metrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_after_operations(self, lock_manager):
        """Test that metrics are correctly tracked."""
        # Acquire two locks
        await lock_manager.acquire_lock("upwork", "m1", holder_id="s1")
        await lock_manager.acquire_lock("upwork", "m2", holder_id="s1")

        # Conflict on first
        await lock_manager.acquire_lock("upwork", "m1", holder_id="s2", timeout=0.2)

        metrics = lock_manager.get_metrics()
        assert metrics["lock_attempts"] == 3
        assert metrics["lock_successes"] == 2
        assert metrics["lock_conflicts"] >= 1
        assert metrics["lock_timeouts"] >= 1


# =============================================================================
# ATOMIC BID CREATION (DEDUPLICATION) TESTS
# =============================================================================

class TestAtomicBidCreation:
    """Test create_bid_atomically for race-condition-free bid placement."""

    @pytest.mark.asyncio
    async def test_create_bid_success(self, db_session):
        """Test creating a bid atomically."""
        bid = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-1",
            marketplace_id="upwork",
            job_title="Build a dashboard",
            job_description="Need data viz",
            bid_amount=15000,
        )
        assert bid is not None
        assert bid.job_id == "post-1"
        assert bid.marketplace == "upwork"
        assert bid.status == BidStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_duplicate_bid_prevented(self, db_session):
        """Test that duplicate ACTIVE bids are prevented by unique constraint."""
        bid1 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-dup",
            marketplace_id="upwork",
            job_title="Job A",
            job_description="Desc A",
            bid_amount=10000,
        )
        assert bid1 is not None

        # Second bid on same posting should be rejected
        bid2 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-dup",
            marketplace_id="upwork",
            job_title="Job A retry",
            job_description="Desc A retry",
            bid_amount=12000,
        )
        assert bid2 is None

    @pytest.mark.asyncio
    async def test_different_postings_both_succeed(self, db_session):
        """Test that bids on different postings both succeed."""
        bid1 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-X",
            marketplace_id="upwork",
            job_title="Job X",
            job_description="Desc X",
            bid_amount=10000,
        )
        bid2 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-Y",
            marketplace_id="upwork",
            job_title="Job Y",
            job_description="Desc Y",
            bid_amount=20000,
        )
        assert bid1 is not None
        assert bid2 is not None

    @pytest.mark.asyncio
    async def test_different_marketplaces_both_succeed(self, db_session):
        """Test that bids on same posting but different marketplaces succeed."""
        bid1 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-Z",
            marketplace_id="upwork",
            job_title="Job Z",
            job_description="Desc Z",
            bid_amount=10000,
        )
        bid2 = await create_bid_atomically(
            db_session=db_session,
            posting_id="post-Z",
            marketplace_id="fiverr",
            job_title="Job Z",
            job_description="Desc Z",
            bid_amount=10000,
        )
        assert bid1 is not None
        assert bid2 is not None


# =============================================================================
# SHOULD_BID DEDUPLICATION TESTS
# =============================================================================

class TestShouldBidDeduplication:
    """Test should_bid deduplication logic."""

    @pytest.mark.asyncio
    async def test_should_bid_no_existing(self, db_session):
        """Test should_bid returns True when no existing bids."""
        result = await should_bid(db_session, "new-post", "upwork")
        assert result is True

    @pytest.mark.asyncio
    async def test_should_bid_existing_active(self, db_session):
        """Test should_bid returns False when ACTIVE bid exists."""
        bid = Bid(
            job_title="Existing Job",
            job_description="Already bid",
            job_id="existing-post",
            bid_amount=10000,
            status=BidStatus.ACTIVE,
            marketplace="upwork",
        )
        db_session.add(bid)
        db_session.commit()

        result = await should_bid(db_session, "existing-post", "upwork")
        assert result is False

    @pytest.mark.asyncio
    async def test_should_bid_empty_inputs(self, db_session):
        """Test should_bid returns False for empty inputs."""
        assert await should_bid(db_session, "", "upwork") is False
        assert await should_bid(db_session, "post", "") is False


# =============================================================================
# DISTRIBUTED LOCK MODEL TESTS
# =============================================================================

class TestDistributedLockModel:
    """Test the DistributedLock SQLAlchemy model."""

    def test_create_lock_row(self, db_session):
        """Test creating a DistributedLock row."""
        lock = DistributedLock(
            lock_key="bid:lock:upwork:job-1",
            holder_id="scanner-1",
            acquired_at=time.time(),
            expires_at=time.time() + 300,
        )
        db_session.add(lock)
        db_session.commit()

        fetched = db_session.query(DistributedLock).filter(
            DistributedLock.lock_key == "bid:lock:upwork:job-1"
        ).first()
        assert fetched is not None
        assert fetched.holder_id == "scanner-1"

    def test_unique_constraint_on_lock_key(self, db_session):
        """Test that duplicate lock_keys raise IntegrityError."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        lock1 = DistributedLock(
            lock_key="bid:lock:upwork:dup",
            holder_id="s1",
            acquired_at=time.time(),
            expires_at=time.time() + 300,
        )
        db_session.add(lock1)
        db_session.commit()

        lock2 = DistributedLock(
            lock_key="bid:lock:upwork:dup",
            holder_id="s2",
            acquired_at=time.time(),
            expires_at=time.time() + 300,
        )
        db_session.add(lock2)
        with pytest.raises(SAIntegrityError):
            db_session.commit()

    def test_to_dict(self, db_session):
        """Test DistributedLock.to_dict()."""
        now = time.time()
        lock = DistributedLock(
            lock_key="bid:lock:test:dict",
            holder_id="test-holder",
            acquired_at=now,
            expires_at=now + 300,
        )
        db_session.add(lock)
        db_session.commit()

        d = lock.to_dict()
        assert d["lock_key"] == "bid:lock:test:dict"
        assert d["holder_id"] == "test-holder"
        assert d["acquired_at"] == now
        assert d["expires_at"] == now + 300
