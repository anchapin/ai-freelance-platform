"""
Distributed Lock Manager for Bid Placement

This module implements a database-backed distributed lock mechanism to prevent
race conditions when multiple scanner instances attempt to place bids on the
same marketplace posting.

Uses SQLAlchemy with a DistributedLock table to ensure cross-process safety.
The lock is acquired via atomic INSERT with a unique constraint on lock_key,
and released via DELETE. Expired locks are cleaned up automatically.

Issue #8:  Implement distributed lock and deduplication for marketplace bids
Issue #19: Replace in-memory asyncio.Lock with DB-backed distributed lock
"""

import asyncio
import time
import uuid
from typing import Dict, Optional
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.models import DistributedLock
from src.api.database import SessionLocal
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BidLockManager:
    """
    Database-backed distributed lock manager for bid placement.

    Prevents concurrent bids on the same marketplace posting by using
    a DistributedLock table with a unique constraint on lock_key.
    Safe across multiple processes/instances.
    """

    def __init__(self, ttl: int = 300):
        """
        Initialize the BidLockManager.

        Args:
            ttl: Time to live for locks in seconds (default: 300 = 5 minutes)
        """
        self.ttl = ttl

        # Metrics
        self._lock_attempts: int = 0
        self._lock_successes: int = 0
        self._lock_conflicts: int = 0
        self._lock_timeouts: int = 0

    def _make_lock_key(self, marketplace_id: str, posting_id: str) -> str:
        """Create a lock key from marketplace and posting IDs."""
        return f"bid:lock:{marketplace_id}:{posting_id}"

    def _get_db(self) -> Session:
        """Create a new database session."""
        return SessionLocal()

    def _cleanup_expired_locks(self, db: Session) -> int:
        """Remove expired locks from the database."""
        now = time.time()
        expired = (
            db.query(DistributedLock).filter(DistributedLock.expires_at < now).all()
        )

        count = len(expired)
        for lock in expired:
            db.delete(lock)

        if count:
            db.commit()
            logger.debug(f"Cleaned up {count} expired distributed locks")

        return count

    async def acquire_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: str = "default",
    ) -> bool:
        """
        Try to acquire a distributed lock for bidding on a specific posting.

        Uses atomic INSERT with unique constraint as compare-and-set.
        Retries with short sleeps until timeout.

        Args:
            marketplace_id: ID of the marketplace (e.g., "upwork", "fiverr")
            posting_id: ID of the job posting
            timeout: Maximum time to wait for lock in seconds
            holder_id: Identifier of the lock holder (for debugging)

        Returns:
            True if lock acquired, False if timeout or conflict

        Raises:
            ValueError: If marketplace_id or posting_id is invalid
        """
        if not marketplace_id or not posting_id:
            raise ValueError("marketplace_id and posting_id must not be empty")

        self._lock_attempts += 1
        lock_key = self._make_lock_key(marketplace_id, posting_id)
        start_time = time.time()

        while True:
            db = self._get_db()
            try:
                # Clean expired locks
                self._cleanup_expired_locks(db)

                now = time.time()

                # Try atomic INSERT (unique constraint on lock_key)
                new_lock = DistributedLock(
                    id=str(uuid.uuid4()),
                    lock_key=lock_key,
                    holder_id=holder_id,
                    acquired_at=now,
                    expires_at=now + self.ttl,
                )
                db.add(new_lock)
                db.commit()

                # Lock acquired successfully
                self._lock_successes += 1
                logger.info(
                    f"Lock acquired: {holder_id} locked {lock_key} (TTL: {self.ttl}s)"
                )
                return True

            except IntegrityError:
                db.rollback()

                # Unique constraint violation — lock exists.
                # Check if it's expired and can be replaced.
                existing = (
                    db.query(DistributedLock)
                    .filter(DistributedLock.lock_key == lock_key)
                    .first()
                )

                if existing and existing.expires_at < time.time():
                    # Expired — delete and retry immediately
                    db.delete(existing)
                    db.commit()
                    continue

                # Lock is held by someone else
                self._lock_conflicts += 1
                holder = existing.holder_id if existing else "unknown"
                logger.warning(
                    f"Lock conflict: {holder_id} tried to acquire "
                    f"{lock_key} but it's held by {holder}"
                )

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    self._lock_timeouts += 1
                    logger.error(f"Lock timeout for {lock_key} after {elapsed:.1f}s")
                    return False

                # Wait before retrying
                await asyncio.sleep(0.1)

            except Exception as e:
                db.rollback()
                logger.error(f"Error acquiring lock {lock_key}: {e}")
                return False

            finally:
                db.close()

    async def release_lock(
        self, marketplace_id: str, posting_id: str, holder_id: str = "default"
    ) -> bool:
        """
        Release a previously acquired lock.

        Args:
            marketplace_id: ID of the marketplace
            posting_id: ID of the job posting
            holder_id: Identifier of the lock holder

        Returns:
            True if lock released, False if lock doesn't exist or holder mismatch
        """
        lock_key = self._make_lock_key(marketplace_id, posting_id)
        db = self._get_db()

        try:
            existing = (
                db.query(DistributedLock)
                .filter(DistributedLock.lock_key == lock_key)
                .first()
            )

            if not existing:
                logger.warning(f"No lock found for {lock_key} (holder: {holder_id})")
                return False

            if existing.holder_id != holder_id:
                logger.warning(
                    f"Holder mismatch for {lock_key}: "
                    f"{holder_id} tried to release but held by {existing.holder_id}"
                )
                return False

            db.delete(existing)
            db.commit()
            logger.info(f"Lock released: {holder_id} released {lock_key}")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Error releasing lock {lock_key}: {e}")
            return False

        finally:
            db.close()

    @asynccontextmanager
    async def with_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: str = "default",
    ):
        """
        Async context manager for acquiring and releasing locks.

        Usage:
            async with bid_lock_manager.with_lock("upwork", "posting_123"):
                # Critical section - only one bid per posting
                if await should_bid(posting_id, "upwork"):
                    await place_bid(posting_id, "upwork")

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
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
        db = self._get_db()
        try:
            active_locks = (
                db.query(DistributedLock)
                .filter(DistributedLock.expires_at >= time.time())
                .count()
            )
        except Exception:
            active_locks = 0
        finally:
            db.close()

        return {
            "lock_attempts": self._lock_attempts,
            "lock_successes": self._lock_successes,
            "lock_conflicts": self._lock_conflicts,
            "lock_timeouts": self._lock_timeouts,
            "active_locks": active_locks,
        }

    async def cleanup_all(self) -> None:
        """Force cleanup of all locks (for testing/shutdown)."""
        db = self._get_db()
        try:
            db.query(DistributedLock).delete()
            db.commit()
            logger.info("All distributed locks cleared")
        except Exception as e:
            db.rollback()
            logger.error(f"Error clearing all locks: {e}")
        finally:
            db.close()


# Global instance (singleton pattern)
_bid_lock_manager: Optional[BidLockManager] = None


def get_bid_lock_manager() -> BidLockManager:
    """Get or create the global BidLockManager instance."""
    global _bid_lock_manager
    if _bid_lock_manager is None:
        _bid_lock_manager = BidLockManager(ttl=300)  # 5 minute TTL
    return _bid_lock_manager


def init_bid_lock_manager(ttl: int = 300) -> BidLockManager:
    """Initialize the global BidLockManager with custom TTL."""
    global _bid_lock_manager
    _bid_lock_manager = BidLockManager(ttl=ttl)
    return _bid_lock_manager
