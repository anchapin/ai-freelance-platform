"""
Bid Lock Manager Factory

Smart factory that chooses between Redis and in-memory implementations
based on environment configuration and availability.

Issue #19: Distributed locking with Redis + fallback for development.
"""

from typing import Optional, Union
from src.config import should_use_redis_locks, get_redis_url
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def create_bid_lock_manager(
    use_redis: Optional[bool] = None, ttl: int = 300
) -> Union["RedisBidLockManager", "BidLockManager"]:
    """
    Create appropriate BidLockManager based on configuration.

    Args:
        use_redis: Override Redis preference (None = auto-detect from config)
        ttl: Lock TTL in seconds

    Returns:
        RedisBidLockManager if Redis is available, else BidLockManager

    Usage:
        # Auto-detect from config
        manager = await create_bid_lock_manager()

        # Force Redis
        manager = await create_bid_lock_manager(use_redis=True)

        # Force in-memory (development)
        manager = await create_bid_lock_manager(use_redis=False)
    """
    # Determine which implementation to use
    if use_redis is None:
        use_redis = should_use_redis_locks()

    if use_redis:
        try:
            from src.agent_execution.redis_bid_lock_manager import (
                RedisBidLockManager,
            )

            redis_url = get_redis_url()
            manager = RedisBidLockManager(redis_url=redis_url, ttl=ttl)

            # Verify Redis connection
            if await manager.health_check():
                logger.info(f"Using Redis BidLockManager (TTL: {ttl}s)")
                return manager
            else:
                logger.warning(
                    "Redis health check failed, falling back to in-memory locks"
                )
                # Fall through to in-memory
        except Exception as e:
            logger.warning(
                f"Failed to initialize Redis BidLockManager: {e}. "
                "Falling back to in-memory locks."
            )
            # Fall through to in-memory

    # Fallback to in-memory implementation
    from src.agent_execution.bid_lock_manager import BidLockManager

    logger.info(f"Using in-memory BidLockManager (TTL: {ttl}s)")
    return BidLockManager(ttl=ttl)


# Global instance
_bid_lock_manager: Optional[Union["RedisBidLockManager", "BidLockManager"]] = None


async def get_bid_lock_manager() -> Union["RedisBidLockManager", "BidLockManager"]:
    """
    Get or create the global BidLockManager instance (auto-detect).

    Returns:
        Global BidLockManager (Redis or in-memory)
    """
    global _bid_lock_manager
    if _bid_lock_manager is None:
        _bid_lock_manager = await create_bid_lock_manager()
    return _bid_lock_manager


async def init_bid_lock_manager(
    use_redis: Optional[bool] = None, ttl: int = 300
) -> Union["RedisBidLockManager", "BidLockManager"]:
    """
    Initialize the global BidLockManager with custom settings.

    Args:
        use_redis: Override Redis preference
        ttl: Lock TTL in seconds

    Returns:
        Initialized global BidLockManager
    """
    global _bid_lock_manager
    _bid_lock_manager = await create_bid_lock_manager(use_redis=use_redis, ttl=ttl)
    return _bid_lock_manager


async def reset_bid_lock_manager() -> None:
    """Reset the global BidLockManager (for testing)."""
    global _bid_lock_manager
    if _bid_lock_manager is not None:
        try:
            await _bid_lock_manager.cleanup_all()
            if hasattr(_bid_lock_manager, "close"):
                await _bid_lock_manager.close()
        except Exception as e:
            logger.warning(f"Error cleaning up lock manager: {e}")
    _bid_lock_manager = None
