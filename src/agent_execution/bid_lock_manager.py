"""
Distributed Lock Manager for Bid Placement

This module implements a distributed lock mechanism to prevent race conditions
when multiple scanner instances attempt to place bids on the same marketplace posting.

The lock system uses an in-memory cache with TTL (time-to-live) to coordinate
bid placement across concurrent operations within a single process, and can be
extended to use Redis for true distributed locking across multiple processes.

Issue #8: Implement distributed lock and deduplication for marketplace bids
"""

import asyncio
import time
from typing import Dict, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BidLock:
    """Represents an active bid lock."""
    marketplace_id: str
    posting_id: str
    acquired_at: float
    ttl: int  # Time to live in seconds
    holder_id: str  # Identifier of who acquired the lock
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        return time.time() - self.acquired_at > self.ttl
    
    def remaining_ttl(self) -> float:
        """Get remaining TTL in seconds."""
        elapsed = time.time() - self.acquired_at
        return max(0, self.ttl - elapsed)


class BidLockManager:
    """
    In-memory distributed lock manager for bid placement.
    
    Prevents concurrent bids on the same marketplace posting by using
    advisory locks with TTL. Uses asyncio.Lock for local synchronization.
    
    Can be extended to use Redis for true distributed locking across processes.
    """
    
    def __init__(self, ttl: int = 300, max_lock_holders: int = 10):
        """
        Initialize the BidLockManager.
        
        Args:
            ttl: Time to live for locks in seconds (default: 300 = 5 minutes)
            max_lock_holders: Maximum number of concurrent lock holders
        """
        self.ttl = ttl
        self.max_lock_holders = max_lock_holders
        
        # In-memory lock storage
        self._locks: Dict[str, BidLock] = {}
        self._lock = asyncio.Lock()  # Local lock for thread safety
        
        # Metrics
        self._lock_attempts: int = 0
        self._lock_successes: int = 0
        self._lock_conflicts: int = 0
        self._lock_timeouts: int = 0
    
    def _make_lock_key(self, marketplace_id: str, posting_id: str) -> str:
        """Create a lock key from marketplace and posting IDs."""
        return f"bid:lock:{marketplace_id}:{posting_id}"
    
    async def acquire_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: str = "default"
    ) -> bool:
        """
        Try to acquire a lock for bidding on a specific posting.
        
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
            async with self._lock:
                # Clean expired locks first
                self._cleanup_expired_locks()
                
                # Check if lock exists and is still valid
                existing_lock = self._locks.get(lock_key)
                if existing_lock and not existing_lock.is_expired():
                    # Lock exists and is still valid - conflict!
                    self._lock_conflicts += 1
                    logger.warning(
                        f"Lock conflict: {holder_id} tried to acquire "
                        f"{lock_key} but it's held by {existing_lock.holder_id} "
                        f"(TTL: {existing_lock.remaining_ttl():.1f}s remaining)"
                    )
                    
                    # Check timeout
                    elapsed = time.time() - start_time
                    if elapsed > timeout:
                        self._lock_timeouts += 1
                        logger.error(f"Lock timeout for {lock_key} after {elapsed:.1f}s")
                        return False
                    
                    # Wait before retrying
                    await asyncio.sleep(0.1)
                    continue
                
                # Lock is free or expired - acquire it
                self._locks[lock_key] = BidLock(
                    marketplace_id=marketplace_id,
                    posting_id=posting_id,
                    acquired_at=time.time(),
                    ttl=self.ttl,
                    holder_id=holder_id
                )
                
                self._lock_successes += 1
                logger.info(
                    f"Lock acquired: {holder_id} locked {lock_key} "
                    f"(TTL: {self.ttl}s)"
                )
                return True
    
    async def release_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        holder_id: str = "default"
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
        
        async with self._lock:
            existing_lock = self._locks.get(lock_key)
            
            if not existing_lock:
                logger.warning(f"No lock found for {lock_key} (holder: {holder_id})")
                return False
            
            if existing_lock.holder_id != holder_id:
                logger.warning(
                    f"Holder mismatch for {lock_key}: "
                    f"{holder_id} tried to release but held by {existing_lock.holder_id}"
                )
                return False
            
            del self._locks[lock_key]
            logger.info(f"Lock released: {holder_id} released {lock_key}")
            return True
    
    @asynccontextmanager
    async def with_lock(
        self,
        marketplace_id: str,
        posting_id: str,
        timeout: float = 10.0,
        holder_id: str = "default"
    ):
        """
        Async context manager for acquiring and releasing locks.
        
        Usage:
            async with bid_lock_manager.with_lock("upwork", "posting_123"):
                # Critical section - only one bid per posting
                if await should_bid(posting_id, "upwork"):
                    await place_bid(posting_id, "upwork")
        
        Args:
            marketplace_id: ID of the marketplace
            posting_id: ID of the job posting
            timeout: Maximum time to wait for lock in seconds
            holder_id: Identifier of the lock holder
            
        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        acquired = await self.acquire_lock(
            marketplace_id=marketplace_id,
            posting_id=posting_id,
            timeout=timeout,
            holder_id=holder_id
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
                holder_id=holder_id
            )
    
    def _cleanup_expired_locks(self) -> int:
        """Remove expired locks from the lock dictionary."""
        expired_keys = [
            key for key, lock in self._locks.items()
            if lock.is_expired()
        ]
        
        for key in expired_keys:
            del self._locks[key]
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired locks")
        
        return len(expired_keys)
    
    def get_metrics(self) -> Dict[str, int]:
        """Get lock manager metrics."""
        return {
            "lock_attempts": self._lock_attempts,
            "lock_successes": self._lock_successes,
            "lock_conflicts": self._lock_conflicts,
            "lock_timeouts": self._lock_timeouts,
            "active_locks": len(self._locks),
        }
    
    async def cleanup_all(self) -> None:
        """Force cleanup of all locks (for testing/shutdown)."""
        async with self._lock:
            self._locks.clear()
            logger.info("All locks cleared")


# Global instance (singleton pattern)
_bid_lock_manager: Optional[BidLockManager] = None


def get_bid_lock_manager() -> BidLockManager:
    """Get or create the global BidLockManager instance."""
    global _bid_lock_manager
    if _bid_lock_manager is None:
        _bid_lock_manager = BidLockManager(ttl=300)  # 5 minute TTL
    return _bid_lock_manager


async def init_bid_lock_manager(ttl: int = 300) -> BidLockManager:
    """Initialize the global BidLockManager with custom TTL."""
    global _bid_lock_manager
    _bid_lock_manager = BidLockManager(ttl=ttl)
    return _bid_lock_manager
