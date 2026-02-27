"""
Tests for concurrent bid operations across simulated instances.

Issue #19: CRITICAL - BidLockManager distributed locking verification.

This test suite verifies that distributed locking prevents
race conditions when multiple app instances try to bid on the same posting.

Tests include:
- Multiple instances acquiring locks (only 1 succeeds)
- Lock holder isolation (only holder can release)
- Lock expiration and TTL
- Concurrent bid scenario simulation
- Database-backed distributed locks
"""

import asyncio
import pytest
import time

from src.agent_execution.bid_lock_manager import (
    BidLockManager,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
async def lock_manager():
    """Create a BidLockManager instance for testing."""
    manager = BidLockManager(ttl=300)
    await manager.cleanup_all()
    yield manager
    await manager.cleanup_all()


# ============================================================================
# SIMULATED INSTANCE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_two_instances_same_bid(lock_manager):
    """
    Test: Two app instances try to bid on same posting.

    Expected: Only one instance acquires the lock.
    """
    marketplace_id = "upwork"
    posting_id = "job_xyz_123"

    # Instance 1
    instance1_holder = "instance-1-worker-0"
    # Instance 2
    instance2_holder = "instance-2-worker-0"

    # Both attempt to acquire lock concurrently
    task1 = lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=5.0,
        holder_id=instance1_holder,
    )
    task2 = lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=5.0,
        holder_id=instance2_holder,
    )

    result1, result2 = await asyncio.gather(task1, task2)

    # Exactly one should succeed
    assert (result1 and not result2) or (not result1 and result2)
    assert lock_manager._lock_successes == 1
    assert lock_manager._lock_conflicts >= 1


@pytest.mark.asyncio
async def test_three_instances_queued_acquisition(lock_manager):
    """
    Test: Three instances queue for same lock.

    Expected: All eventually acquire lock in sequence (after release).
    """
    marketplace_id = "fiverr"
    posting_id = "gig_456"
    num_instances = 3
    acquisition_order = []

    async def instance_attempt(instance_id: int):
        """Simulate one instance attempting to acquire lock."""
        holder_id = f"instance-{instance_id}"
        acquired = await lock_manager.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            timeout=10.0,
            holder_id=holder_id,
        )

        if acquired:
            acquisition_order.append(instance_id)
            # Hold lock for brief moment
            await asyncio.sleep(0.1)
            # Release
            await lock_manager.release_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                holder_id=holder_id,
            )

        return acquired

    # All instances attempt concurrently
    results = await asyncio.gather(*[instance_attempt(i) for i in range(num_instances)])

    # All should eventually acquire the lock
    assert all(results)
    assert len(acquisition_order) == num_instances
    assert lock_manager._lock_successes == num_instances


@pytest.mark.asyncio
async def test_lock_holder_cannot_steal(lock_manager):
    """
    Test: Instance 2 cannot release lock held by Instance 1.

    Expected: Release fails with wrong holder_id.
    """
    marketplace_id = "upwork"
    posting_id = "job_steal_test"

    # Instance 1 acquires lock
    holder1 = "instance-1"
    acquired = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder1,
    )
    assert acquired is True

    # Instance 2 tries to release holder1's lock
    holder2 = "instance-2"
    released = await lock_manager.release_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder2,
    )

    # Should fail
    assert released is False

    # Only holder1 can release
    released_correct = await lock_manager.release_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder1,
    )
    assert released_correct is True


@pytest.mark.asyncio
async def test_concurrent_multiple_postings(lock_manager):
    """
    Test: Multiple instances bidding on different postings concurrently.

    Expected: Each posting gets one lock holder, different instances
    can lock different postings simultaneously.
    """
    marketplace_id = "upwork"
    num_instances = 5
    num_postings = 5

    results = []

    async def instance_bid_on_posting(instance_id: int, posting_idx: int):
        """Simulate instance bidding on a posting."""
        posting_id = f"job_{posting_idx}"
        holder_id = f"instance-{instance_id}"

        acquired = await lock_manager.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            timeout=2.0,
            holder_id=holder_id,
        )

        if acquired:
            await asyncio.sleep(0.05)  # Simulate bid placement
            await lock_manager.release_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                holder_id=holder_id,
            )

        return {"instance": instance_id, "posting": posting_idx, "acquired": acquired}

    # Each instance tries to bid on all postings
    tasks = [
        instance_bid_on_posting(i, j)
        for i in range(num_instances)
        for j in range(num_postings)
    ]

    results = await asyncio.gather(*tasks)

    # Collect results by posting
    by_posting = {}
    for result in results:
        posting = result["posting"]
        if posting not in by_posting:
            by_posting[posting] = []
        by_posting[posting].append(result)

    # Each posting should have successful bidders
    for posting_idx in range(num_postings):
        acquired_list = [r["acquired"] for r in by_posting[posting_idx]]
        # At least one instance should acquire lock on each posting
        assert any(acquired_list)


@pytest.mark.asyncio
async def test_lock_expiration_ttl(lock_manager):
    """
    Test: Lock automatically expires after TTL.

    Expected: After TTL expires, new instance can acquire same lock.
    """
    lock_manager.ttl = 1  # 1 second TTL for testing

    marketplace_id = "upwork"
    posting_id = "job_ttl_test"
    holder1 = "instance-1"
    holder2 = "instance-2"

    # Instance 1 acquires lock
    acquired1 = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder1,
        timeout=2.0,
    )
    assert acquired1 is True

    # Instance 2 cannot immediately acquire (timeout=0.5)
    acquired2_fast = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder2,
        timeout=0.5,
    )
    assert acquired2_fast is False

    # Wait for TTL expiration
    await asyncio.sleep(1.5)

    # Instance 2 can now acquire (lock expired)
    acquired2_slow = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder2,
        timeout=1.0,
    )
    assert acquired2_slow is True


@pytest.mark.asyncio
async def test_bid_workflow_multi_instance(lock_manager):
    """
    Test: Complete bid workflow simulation with multiple instances.

    Expected:
    1. Instance acquires lock for posting
    2. Places bid (simulated)
    3. Releases lock
    4. Next instance can then bid on same posting
    """
    marketplace_id = "upwork"
    posting_id = "job_workflow_test"

    async def bid_workflow(instance_id: int) -> bool:
        """Simulate complete bid workflow for one instance."""
        holder_id = f"instance-{instance_id}"

        try:
            # Step 1: Acquire lock
            acquired = await lock_manager.acquire_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                timeout=5.0,
                holder_id=holder_id,
            )

            if not acquired:
                return False

            # Step 2: Place bid (simulated)
            # In real code: check if eligible, calculate bid amount, submit to marketplace
            await asyncio.sleep(0.05)  # Simulate API call

            # Step 3: Release lock
            released = await lock_manager.release_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                holder_id=holder_id,
            )

            return released
        except Exception as e:
            print(f"Error in bid workflow: {e}")
            return False

    # Run 3 instances sequentially through lock acquisition
    results = []
    for instance_id in range(3):
        result = await bid_workflow(instance_id)
        results.append(result)

    # All should succeed
    assert all(results)
    assert lock_manager._lock_successes == 3
    assert lock_manager._lock_conflicts == 0  # No conflicts (sequential)


@pytest.mark.asyncio
async def test_lock_timeout_behavior(lock_manager):
    """
    Test: Lock acquisition timeout behavior.

    Expected:
    - Short timeout fails quickly when lock is held
    - Long timeout eventually times out when lock is held
    - Exponential backoff is used
    """
    marketplace_id = "upwork"
    posting_id = "job_timeout_test"
    holder1 = "instance-1"

    # Instance 1 holds lock
    await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder1,
    )

    # Instance 2 with short timeout
    start = time.time()
    result_short = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id="instance-2",
        timeout=0.5,
    )
    elapsed_short = time.time() - start

    assert result_short is False
    assert elapsed_short >= 0.5  # Should wait at least timeout duration
    assert elapsed_short < 1.0  # But not much longer

    # Instance 3 with longer timeout
    start = time.time()
    result_long = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id="instance-3",
        timeout=2.0,
    )
    elapsed_long = time.time() - start

    assert result_long is False
    assert elapsed_long >= 2.0


@pytest.mark.asyncio
async def test_context_manager_multi_instance(lock_manager):
    """
    Test: Context manager ensures proper cleanup across instances.

    Expected: Lock is released even if exception occurs.
    """
    marketplace_id = "upwork"
    posting_id = "job_context_test"

    # Instance 1 acquires and releases via context manager
    holder1 = "instance-1"

    async with lock_manager.with_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=5.0,
        holder_id=holder1,
    ):
        await asyncio.sleep(0.05)

    # Instance 2 should be able to acquire immediately
    holder2 = "instance-2"
    acquired = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=1.0,
        holder_id=holder2,
    )
    assert acquired is True


@pytest.mark.asyncio
async def test_instance_failure_doesnt_block_lock(lock_manager):
    """
    Test: If instance crashes without releasing, TTL ensures lock is freed.

    Expected:
    - Instance 1 acquires lock
    - Instance 1 crashes (no release call)
    - After TTL expires, Instance 2 can acquire lock
    """
    lock_manager.ttl = 1  # Short TTL

    marketplace_id = "upwork"
    posting_id = "job_crash_test"
    holder1 = "instance-1-crashed"
    holder2 = "instance-2-healthy"

    # Instance 1 acquires lock but "crashes" (no release)
    await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder1,
    )

    # Instance 2 cannot acquire immediately
    acquired_fast = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder2,
        timeout=0.5,
    )
    assert acquired_fast is False

    # Wait for TTL and try again
    await asyncio.sleep(1.5)

    acquired_slow = await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id=holder2,
        timeout=1.0,
    )
    assert acquired_slow is True


@pytest.mark.asyncio
async def test_metrics_multi_instance(lock_manager):
    """
    Test: Metrics accurately reflect multi-instance activity.
    """
    marketplace_id = "upwork"
    posting_id = "job_metrics_test"

    # Instance 1: successful acquisition
    await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id="instance-1",
    )

    # Instance 2: conflict
    await lock_manager.acquire_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        holder_id="instance-2",
        timeout=0.5,
    )

    metrics = lock_manager.get_metrics()

    assert metrics["lock_attempts"] == 2
    assert metrics["lock_successes"] == 1
    assert metrics["lock_conflicts"] >= 1


@pytest.mark.asyncio
async def test_different_marketplaces_independent(lock_manager):
    """
    Test: Locks on different marketplaces are independent.

    Expected: Instance A locks upwork posting, Instance B locks fiverr posting.
    Both should succeed simultaneously.
    """
    posting_id = "job_123"
    holder1 = "instance-1"
    holder2 = "instance-2"

    # Instance 1 locks upwork
    result1 = await lock_manager.acquire_lock(
        marketplace_id="upwork",
        posting_id=posting_id,
        holder_id=holder1,
    )

    # Instance 2 locks fiverr (different marketplace)
    result2 = await lock_manager.acquire_lock(
        marketplace_id="fiverr",
        posting_id=posting_id,
        holder_id=holder2,
    )

    # Both should succeed (different lock keys)
    assert result1 is True
    assert result2 is True
    assert lock_manager._lock_successes == 2
    assert lock_manager._lock_conflicts == 0


@pytest.mark.asyncio
async def test_rapid_acquire_release_cycle(lock_manager):
    """
    Test: Rapid acquire/release cycles work correctly.

    Expected: Multiple cycles on same posting succeed.
    """
    marketplace_id = "upwork"
    posting_id = "job_rapid_test"
    num_cycles = 10

    for cycle in range(num_cycles):
        holder_id = f"instance-cycle-{cycle}"

        # Acquire
        acquired = await lock_manager.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            holder_id=holder_id,
            timeout=2.0,
        )
        assert acquired is True

        # Brief hold
        await asyncio.sleep(0.01)

        # Release
        released = await lock_manager.release_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            holder_id=holder_id,
        )
        assert released is True

    assert lock_manager._lock_successes == num_cycles
    assert lock_manager._lock_conflicts == 0


@pytest.mark.asyncio
async def test_redis_connection_fallback():
    """
    Test: Graceful handling of Redis connection failures.

    Expected: Health check detects connection issues.
    """
    # Try to connect to invalid Redis
    manager = RedisBidLockManager(redis_url="redis://invalid-host:6379/0")

    is_healthy = await manager.health_check()
    assert is_healthy is False
