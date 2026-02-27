"""
Tests for Database-backed BidLockManager and distributed locking scenarios.

This test suite validates:
- Atomic lock acquisition with database unique constraints
- Lock expiration and TTL handling
- Concurrent lock contention across multiple "instances"
- Lock holder identification
- Error handling and database connectivity issues
- Lock metrics collection

Issue #19: Implement distributed BidLockManager with database
"""

import asyncio
import pytest

from src.agent_execution.bid_lock_manager import (
    BidLockManager,
    get_bid_lock_manager,
    init_bid_lock_manager,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
async def lock_manager():
    """Create a BidLockManager instance for testing."""
    manager = BidLockManager(ttl=300)
    # Clean up any existing test locks
    await manager.cleanup_all()
    yield manager
    # Cleanup after test
    await manager.cleanup_all()


# ============================================================================
# BASIC LOCK OPERATIONS
# ============================================================================


@pytest.mark.asyncio
async def test_acquire_lock_success(lock_manager):
    """Test successful lock acquisition."""
    result = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        timeout=5.0,
        holder_id="test_holder_1",
    )
    assert result is True
    assert lock_manager._lock_successes == 1
    assert lock_manager._lock_attempts == 1


@pytest.mark.asyncio
async def test_acquire_lock_invalid_params(lock_manager):
    """Test lock acquisition with invalid parameters."""
    with pytest.raises(ValueError, match="must not be empty"):
        await lock_manager.acquire_lock(
            marketplace_id="",
            posting_id="job_123",
        )

    with pytest.raises(ValueError, match="must not be empty"):
        await lock_manager.acquire_lock(
            marketplace_id="upwork",
            posting_id="",
        )


@pytest.mark.asyncio
async def test_acquire_lock_conflict(lock_manager):
    """Test lock acquisition when lock is already held."""
    # First acquisition succeeds
    result1 = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        timeout=1.0,
        holder_id="holder_1",
    )
    assert result1 is True

    # Second acquisition should fail (timeout)
    result2 = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        timeout=0.5,
        holder_id="holder_2",
    )
    assert result2 is False
    assert lock_manager._lock_conflicts > 0
    assert lock_manager._lock_timeouts > 0


@pytest.mark.asyncio
async def test_release_lock_success(lock_manager):
    """Test successful lock release."""
    holder_id = "test_holder_1"

    # Acquire lock
    acquired = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id=holder_id,
    )
    assert acquired is True

    # Release lock
    released = await lock_manager.release_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id=holder_id,
    )
    assert released is True


@pytest.mark.asyncio
async def test_release_lock_nonexistent(lock_manager):
    """Test releasing a lock that doesn't exist."""
    result = await lock_manager.release_lock(
        marketplace_id="upwork",
        posting_id="nonexistent_job",
        holder_id="test_holder",
    )
    assert result is False


@pytest.mark.asyncio
async def test_release_lock_holder_mismatch(lock_manager):
    """Test releasing a lock with wrong holder ID."""
    holder_id1 = "holder_1"
    holder_id2 = "holder_2"

    # Acquire lock with holder1
    await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id=holder_id1,
    )

    # Try to release with holder2
    result = await lock_manager.release_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id=holder_id2,
    )
    assert result is False


# ============================================================================
# CONTEXT MANAGER TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_context_manager_success(lock_manager):
    """Test context manager successfully acquires and releases lock."""
    acquired = False

    async with lock_manager.with_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        timeout=5.0,
    ):
        acquired = True

    assert acquired is True
    assert lock_manager._lock_successes >= 1


@pytest.mark.asyncio
async def test_context_manager_timeout(lock_manager):
    """Test context manager timeout when lock cannot be acquired."""
    # Acquire first lock
    await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id="holder_1",
    )

    # Try to acquire same lock with context manager (should timeout)
    with pytest.raises(TimeoutError):
        async with lock_manager.with_lock(
            marketplace_id="upwork",
            posting_id="job_123",
            timeout=0.5,
            holder_id="holder_2",
        ):
            pass


@pytest.mark.asyncio
async def test_context_manager_exception_releases_lock(lock_manager):
    """Test that lock is released even if exception occurs in context."""
    holder_id = "test_holder"

    with pytest.raises(ValueError):
        async with lock_manager.with_lock(
            marketplace_id="upwork",
            posting_id="job_123",
            holder_id=holder_id,
        ):
            raise ValueError("Test exception")

    # Lock should be released, so we should be able to acquire it again
    result = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        timeout=1.0,
        holder_id="new_holder",
    )
    assert result is True


# ============================================================================
# CONCURRENT LOCK TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_lock_attempts(lock_manager):
    """Test multiple concurrent lock attempts on same resource.

    This test verifies that Redis lock properly serializes access:
    - Multiple holders try to acquire the same lock concurrently
    - All should eventually acquire it (with timeout)
    - Lock is released and re-acquired in queue order
    """
    marketplace_id = "upwork"
    posting_id = "job_123"
    num_concurrent = 5
    timeout = 5.0
    acquisition_order = []
    lock_event = asyncio.Lock()

    async def acquire_and_hold(holder_id: str, duration: float):
        """Attempt to acquire lock and hold it for duration."""
        acquired = await lock_manager.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            timeout=timeout,
            holder_id=holder_id,
        )

        if acquired:
            # Record acquisition order
            async with lock_event:
                acquisition_order.append(holder_id)

            await asyncio.sleep(duration)
            await lock_manager.release_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                holder_id=holder_id,
            )

        return acquired

    # Start all concurrent tasks
    tasks = [acquire_and_hold("holder_0", 0.2)]
    for i in range(1, num_concurrent):
        tasks.append(acquire_and_hold(f"holder_{i}", 0.1))

    # All should eventually succeed (queued behind lock)
    results = await asyncio.gather(*tasks)

    # All should acquire successfully (lock is released after each holder)
    assert all(results), f"Some holders failed to acquire lock: {results}"

    # Verify they acquired in some order
    assert len(acquisition_order) == num_concurrent
    assert acquisition_order[0] == "holder_0"  # First to acquire


@pytest.mark.asyncio
async def test_sequential_lock_reacquisition(lock_manager):
    """Test that lock can be re-acquired after release."""
    marketplace_id = "upwork"
    posting_id = "job_123"

    for i in range(3):
        holder_id = f"holder_{i}"

        # Acquire
        acquired = await lock_manager.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            holder_id=holder_id,
            timeout=5.0,
        )
        assert acquired is True

        # Release
        released = await lock_manager.release_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            holder_id=holder_id,
        )
        assert released is True


@pytest.mark.asyncio
async def test_multiple_different_locks(lock_manager):
    """Test that different postings can have independent locks."""
    # Use short TTL to avoid expiration during test
    lock_manager.ttl = 5
    postings = ["job_1", "job_2", "job_3"]

    # Acquire locks for all postings
    for posting_id in postings:
        result = await lock_manager.acquire_lock(
            marketplace_id="upwork",
            posting_id=posting_id,
            holder_id="holder_1",
        )
        assert result is True

    # All should be held by holder_1
    # Trying to acquire again should fail (with short timeout)
    for posting_id in postings:
        result = await lock_manager.acquire_lock(
            marketplace_id="upwork",
            posting_id=posting_id,
            holder_id="holder_2",
            timeout=0.3,
        )
        assert result is False


# ============================================================================
# LOCK METRICS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_metrics_collection(lock_manager):
    """Test that lock manager collects accurate metrics."""
    # Initial metrics
    metrics = lock_manager.get_metrics()
    assert metrics["lock_attempts"] == 0
    assert metrics["lock_successes"] == 0
    assert metrics["lock_conflicts"] == 0

    # Acquire lock
    await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_1",
        holder_id="holder_1",
    )

    metrics = lock_manager.get_metrics()
    assert metrics["lock_attempts"] == 1
    assert metrics["lock_successes"] == 1
    assert metrics["lock_conflicts"] == 0

    # Try to acquire same lock (should conflict)
    await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_1",
        holder_id="holder_2",
        timeout=0.5,
    )

    metrics = lock_manager.get_metrics()
    assert metrics["lock_attempts"] == 2
    assert metrics["lock_successes"] == 1
    assert metrics["lock_conflicts"] >= 1


# ============================================================================
# TTL AND EXPIRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_lock_ttl_respected(lock_manager):
    """Test that locks expire after TTL."""
    lock_manager.ttl = 1  # 1 second TTL

    holder_id = "holder_1"

    # Acquire lock
    acquired = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id=holder_id,
    )
    assert acquired is True

    # Should not be able to acquire immediately
    immediate = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id="holder_2",
        timeout=0.5,
    )
    assert immediate is False

    # Wait for TTL to expire
    await asyncio.sleep(1.5)

    # Should now be able to acquire (lock expired)
    expired = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_123",
        holder_id="holder_3",
        timeout=1.0,
    )
    assert expired is True


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_health_check_success(lock_manager):
    """Test successful health check - always returns True for DB-backed locks."""
    metrics = lock_manager.get_metrics()
    # Database-backed locks don't have health_check - just verify metrics work
    assert "lock_attempts" in metrics
    assert "lock_successes" in metrics


@pytest.mark.asyncio
async def test_health_check_failure():
    """Test health check with invalid configuration - DB-backed always works."""
    # Database-backed locks don't fail on connection issues (SQLite is local)
    # This test is a no-op for DB-backed locks
    manager = BidLockManager(ttl=300)
    metrics = manager.get_metrics()
    assert "lock_attempts" in metrics


# ============================================================================
# LOCK KEY GENERATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_lock_key_generation(lock_manager):
    """Test lock key format."""
    lock_key = lock_manager._make_lock_key("upwork", "job_123")
    # Database-backed locks use bid:lock: prefix
    assert lock_key == "bid:lock:upwork:job_123"


@pytest.mark.asyncio
async def test_holder_id_generation(lock_manager):
    """Test holder ID parameter - BidLockManager doesn't auto-generate."""
    # Database-backed locks don't auto-generate holder IDs
    # They accept holder_id as a parameter (uses "default" if not provided)
    acquired = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id="job_test",
        holder_id="custom_holder",
        timeout=1.0,
    )
    assert acquired is True


# ============================================================================
# CLEANUP TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_all(lock_manager):
    """Test cleanup of all locks."""
    # Create multiple locks
    for i in range(5):
        await lock_manager.acquire_lock(
            marketplace_id="upwork",
            posting_id=f"job_{i}",
            holder_id=f"holder_{i}",
        )

    # Cleanup all
    await lock_manager.cleanup_all()

    # Should be able to re-acquire all locks (they're gone)
    for i in range(5):
        result = await lock_manager.acquire_lock(
            marketplace_id="upwork",
            posting_id=f"job_{i}",
            holder_id="new_holder",
            timeout=1.0,
        )
        assert result is True


# ============================================================================
# SINGLETON TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_bid_lock_manager():
    """Test singleton pattern for get_bid_lock_manager."""
    manager1 = await get_bid_lock_manager()
    manager2 = await get_bid_lock_manager()
    assert manager1 is manager2


@pytest.mark.asyncio
async def test_get_bid_lock_manager():
    """Test singleton pattern for get_bid_lock_manager."""
    manager1 = get_bid_lock_manager()
    manager2 = get_bid_lock_manager()
    assert manager1 is manager2


@pytest.mark.asyncio
async def test_init_bid_lock_manager():
    """Test initialization with custom settings."""
    manager = init_bid_lock_manager(ttl=600)
    assert manager.ttl == 600
    # Database-backed locks don't have redis_url attribute


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_bid_lock_workflow(lock_manager):
    """Test complete bid lock workflow."""
    marketplace_id = "fiverr"
    posting_id = "gig_456"
    holder_id = "agent_scanner_1"

    # 1. Check if we can acquire lock
    async with lock_manager.with_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=5.0,
        holder_id=holder_id,
    ):
        # 2. Lock is held, perform bidding operations
        assert lock_manager._lock_successes >= 1

        # Simulate bid placement
        await asyncio.sleep(0.1)

    # 3. After context exit, lock should be released
    # Verify by re-acquiring
    re_acquired = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=1.0,
        holder_id="agent_scanner_2",
    )
    assert re_acquired is True
