"""
Redis-Based Distributed Lock Manager for Bid Placement

This module implements a Redis-backed distributed lock mechanism to prevent
race conditions when multiple scanner instances attempt to place bids on the
same marketplace posting.

Uses Redis SET with NX (atomic compare-and-set) and automatic expiration (EX).
This replaces the SQLite-based implementation which cannot be truly distributed.

Why Redis instead of Database-backed locks:
- SQLite is single-process and cannot coordinate across multiple instances
- Redis is built for distributed coordination with atomic operations
- Redis provides TTL natively (auto-expiration without cleanup jobs)
- Much faster than database polling (in-memory with sub-millisecond latency)

Issue #19: Implement distributed BidLockManager with Redis
"""

import asyncio
import uuid
from typing import Dict, Optional
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio.client import Redis
from redis.exceptions import RedisError, LockError

from src.utils.logger import get_logger
from src.config import get_redis_url

logger = get_logger(__name__)


class RedisBidLockManager:
    """
    Redis-backed distributed lock manager for bid placement.

    Uses Redis SET with NX (atomic compare-and-set) and EX (auto-expiration).
    Safe across multiple processes/instances/servers.
    """

    def __init__(self, redis_url: Optional[str] = None, ttl: int = 300):
        """
        Initialize the RedisBidLockManager.

        Args:
            redis_url: Redis connection URL (default: from config/env)
            ttl: Time to live for locks in seconds (default: 300 = 5 minutes)
        """
        self.redis_url = redis_url or get_redis_url()
        self.ttl = ttl
        self._redis_pool: Optional[Redis] = None

        # Metrics
        self._lock_attempts: int = 0
        self._lock_successes: int = 0
        self._lock_conflicts: int = 0
        self._lock_timeouts: int = 0
        self._redis_errors: int = 0

    async def _get_redis(self) -> Redis:
        """Get or create Redis connection pool."""
        if self._redis_pool is None:
            try:
                self._redis_pool = await redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    health_check_interval=30,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                )
                logger.info(f"Connected to Redis: {self.redis_url}")
            except RedisError as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

        return self._redis_pool

    def _make_lock_key(self, marketplace_id: str, posting_id: str) -> str:
        """Create a lock key from marketplace and posting IDs."""
        return f"bid_lock:{marketplace_id}:{posting_id}"

    def _make_holder_id(self) -> str:
        """Generate a unique holder ID (server instance + UUID)."""
        import socket
        import os

        hostname = socket.gethostname()
        pid = os.getpid()
        unique_id = str(uuid.uuid4())[:8]
        return f"{hostname}:{pid}:{unique_id}"

    async def acquire_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: Optional[str] = None,
    ) -> bool:
        """
        Try to acquire a distributed lock for bidding on a specific posting.

        Uses Redis SET with NX (atomic compare-and-set).
        Retries with exponential backoff until timeout.

        Args:
            marketplace_id: ID of the marketplace (e.g., "upwork", "fiverr")
            posting_id: ID of the job posting
            timeout: Maximum time to wait for lock in seconds
            holder_id: Identifier of the lock holder (for debugging)

        Returns:
            True if lock acquired, False if timeout or error

        Raises:
            ValueError: If marketplace_id or posting_id is invalid
        """
        if not marketplace_id or not posting_id:
            raise ValueError("marketplace_id and posting_id must not be empty")

        holder_id = holder_id or self._make_holder_id()
        self._lock_attempts += 1
        lock_key = self._make_lock_key(marketplace_id, posting_id)

        retry_count = 0
        retry_delay = 0.05  # 50ms initial delay
        max_retry_delay = 1.0  # 1s max delay

        try:
            redis_client = await self._get_redis()
        except RedisError as e:
            self._redis_errors += 1
            logger.error(f"Redis connection failed: {e}")
            return False

        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                # Try atomic SET with NX (only set if key doesn't exist)
                # EX = expiration in seconds (auto-cleanup)
                acquired = await redis_client.set(
                    lock_key,
                    holder_id,
                    nx=True,  # Only set if key doesn't exist
                    ex=self.ttl,  # Expire after TTL
                )

                if acquired:
                    self._lock_successes += 1
                    logger.info(
                        f"Lock acquired: {holder_id} locked {lock_key} "
                        f"(TTL: {self.ttl}s)"
                    )
                    return True

                # Lock exists, check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    self._lock_timeouts += 1
                    self._lock_conflicts += 1
                    logger.warning(
                        f"Lock timeout: {holder_id} could not acquire "
                        f"{lock_key} after {elapsed:.1f}s"
                    )
                    return False

                # Exponential backoff
                retry_count += 1
                retry_delay = min(retry_delay * 1.5, max_retry_delay)
                await asyncio.sleep(retry_delay)

            except RedisError as e:
                self._redis_errors += 1
                logger.error(f"Redis error acquiring lock {lock_key}: {e}")
                return False

    async def release_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        holder_id: Optional[str] = None,
    ) -> bool:
        """
        Release a previously acquired lock.

        Uses Redis DELETE with value check to prevent releasing locks
        held by other processes.

        Args:
            marketplace_id: ID of the marketplace
            posting_id: ID of the job posting
            holder_id: Identifier of the lock holder (optional verification)

        Returns:
            True if lock released, False if lock doesn't exist or error
        """
        lock_key = self._make_lock_key(marketplace_id, posting_id)

        try:
            redis_client = await self._get_redis()
        except RedisError as e:
            self._redis_errors += 1
            logger.error(f"Redis connection failed: {e}")
            return False

        try:
            if holder_id:
                # Verify holder before deleting (optional but safer)
                current_holder = await redis_client.get(lock_key)
                if current_holder != holder_id:
                    logger.warning(
                        f"Holder mismatch for {lock_key}: "
                        f"{holder_id} tried to release but held by {current_holder}"
                    )
                    return False

            # Delete the lock
            deleted = await redis_client.delete(lock_key)

            if deleted:
                logger.info(
                    f"Lock released: {holder_id or 'unknown'} released {lock_key}"
                )
                return True
            else:
                logger.warning(f"No lock found for {lock_key}")
                return False

        except RedisError as e:
            self._redis_errors += 1
            logger.error(f"Redis error releasing lock {lock_key}: {e}")
            return False

    @asynccontextmanager
    async def with_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: Optional[str] = None,
    ):
        """
        Async context manager for acquiring and releasing locks.

        Usage:
            async with bid_lock_manager.with_lock("upwork", "posting_123"):
                # Critical section - only one bid per posting
                if await should_bid(db_session, posting_id, "upwork"):
                    await place_bid(posting_id, "upwork")

        Args:
            marketplace_id: ID of the marketplace
            posting_id: ID of the job posting
            timeout: Maximum time to wait for lock in seconds
            holder_id: Identifier of the lock holder (for debugging)

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        holder_id = holder_id or self._make_holder_id()
        acquired = await self.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            timeout=timeout,
            holder_id=holder_id,
        )

        if not acquired:
            raise TimeoutError(
                f"Failed to acquire lock for {marketplace_id}:{posting_id} "
                f"within {timeout}s"
            )

        try:
            yield
        finally:
            await self.release_lock(
                marketplace_id=marketplace_id,
                posting_id=posting_id,
                holder_id=holder_id,
            )

    def get_metrics(self) -> Dict[str, int]:
        """Get lock manager metrics."""
        return {
            "lock_attempts": self._lock_attempts,
            "lock_successes": self._lock_successes,
            "lock_conflicts": self._lock_conflicts,
            "lock_timeouts": self._lock_timeouts,
            "redis_errors": self._redis_errors,
        }

    async def cleanup_all(self) -> None:
        """Force cleanup of all locks matching pattern (for testing/shutdown)."""
        try:
            redis_client = await self._get_redis()
        except RedisError as e:
            logger.error(f"Redis connection failed: {e}")
            return

        try:
            # Find all bid lock keys
            pattern = "bid_lock:*"
            cursor = 0
            deleted_count = 0

            while True:
                cursor, keys = await redis_client.scan(
                    cursor, match=pattern, count=100
                )
                if keys:
                    deleted_count += await redis_client.delete(*keys)

                if cursor == 0:
                    break

            logger.info(f"Cleaned up {deleted_count} distributed locks")
        except RedisError as e:
            logger.error(f"Error cleaning locks: {e}")

    async def health_check(self) -> bool:
        """Check Redis connectivity and health."""
        try:
            redis_client = await self._get_redis()
            pong = await redis_client.ping()
            return pong == True
        except RedisError as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection pool."""
        if self._redis_pool:
            await self._redis_pool.close()
            logger.info("Redis connection pool closed")


# Global instance (singleton pattern)
_bid_lock_manager: Optional[RedisBidLockManager] = None


async def get_bid_lock_manager() -> RedisBidLockManager:
    """Get or create the global RedisBidLockManager instance."""
    global _bid_lock_manager
    if _bid_lock_manager is None:
        _bid_lock_manager = RedisBidLockManager(ttl=300)  # 5 minute TTL
        # Verify connection on first access
        if not await _bid_lock_manager.health_check():
            logger.warning("Failed to connect to Redis for BidLockManager")
    return _bid_lock_manager


async def init_bid_lock_manager(
    redis_url: Optional[str] = None, ttl: int = 300
) -> RedisBidLockManager:
    """Initialize the global RedisBidLockManager with custom settings."""
    global _bid_lock_manager
    _bid_lock_manager = RedisBidLockManager(redis_url=redis_url, ttl=ttl)
    if not await _bid_lock_manager.health_check():
        raise RuntimeError("Failed to connect to Redis")
    return _bid_lock_manager
