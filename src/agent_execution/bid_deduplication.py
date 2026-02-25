"""
Bid Deduplication and Placement Logic

This module implements deduplication checks to prevent placing bids on
marketplace postings where we've already placed bids.

Issue #8: Implement distributed lock and deduplication for marketplace bids
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from src.api.models import Bid, BidStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default posting cache TTL in hours
DEFAULT_POSTING_TTL_HOURS = 24


async def should_bid(
    db_session: Session,
    posting_id: str,
    marketplace_id: str,
    ttl_hours: int = DEFAULT_POSTING_TTL_HOURS
) -> bool:
    """
    Check if we should place a bid on a posting.
    
    Returns False if:
    1. An ACTIVE bid already exists for this posting
    2. The posting is stale (cached more than TTL_HOURS ago)
    
    Args:
        db_session: SQLAlchemy database session
        posting_id: Marketplace posting ID
        marketplace_id: Marketplace identifier (e.g., "upwork", "fiverr")
        ttl_hours: Time-to-live for cached postings in hours (default: 24)
        
    Returns:
        True if we should proceed with bidding, False otherwise
    """
    
    if not posting_id or not marketplace_id:
        logger.error("posting_id and marketplace_id must not be empty")
        return False
    
    try:
        # Check for existing ACTIVE bid
        existing_bid = db_session.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id,
            Bid.status == BidStatus.ACTIVE
        ).first()
        
        if existing_bid:
            logger.warning(
                f"Deduplication: Found existing ACTIVE bid {existing_bid.id} "
                f"for posting {marketplace_id}:{posting_id}"
            )
            return False
        
        # Check posting freshness (if we have a cached timestamp)
        # If the posting was cached more than TTL_HOURS ago, it might be stale
        stale_bids = db_session.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id,
            Bid.posting_cached_at.isnot(None),
            Bid.status.in_([BidStatus.ACTIVE, BidStatus.SUBMITTED])
        ).all()
        
        if stale_bids:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
            for bid in stale_bids:
                if bid.posting_cached_at and bid.posting_cached_at < cutoff_time:
                    logger.warning(
                        f"Posting freshness check: posting {marketplace_id}:{posting_id} "
                        f"was cached {(datetime.now(timezone.utc) - bid.posting_cached_at).total_seconds() / 3600:.1f} hours ago, "
                        f"exceeds TTL of {ttl_hours}h"
                    )
                    return False
        
        logger.info(
            f"Deduplication check passed: ok to bid on "
            f"{marketplace_id}:{posting_id}"
        )
        return True
        
    except Exception as e:
        logger.error(
            f"Error checking deduplication for {marketplace_id}:{posting_id}: {e}",
            exc_info=True
        )
        # Conservative approach: if we can't check, don't bid
        return False


async def mark_bid_withdrawn(
    db_session: Session,
    bid_id: str,
    reason: str
) -> bool:
    """
    Mark a bid as withdrawn.
    
    Args:
        db_session: SQLAlchemy database session
        bid_id: Bid ID to withdraw
        reason: Reason for withdrawal
        
    Returns:
        True if successful, False otherwise
    """
    try:
        bid = db_session.query(Bid).filter(Bid.id == bid_id).first()
        
        if not bid:
            logger.error(f"Bid {bid_id} not found")
            return False
        
        if bid.status not in [BidStatus.ACTIVE, BidStatus.SUBMITTED]:
            logger.warning(
                f"Cannot withdraw bid {bid_id} with status {bid.status.value}"
            )
            return False
        
        bid.status = BidStatus.WITHDRAWN
        bid.withdrawn_reason = reason
        bid.withdrawal_timestamp = datetime.now(timezone.utc)
        bid.updated_at = datetime.now(timezone.utc)
        
        db_session.commit()
        
        logger.info(
            f"Bid {bid_id} withdrawn: {reason}"
        )
        return True
        
    except Exception as e:
        logger.error(f"Error withdrawing bid {bid_id}: {e}", exc_info=True)
        db_session.rollback()
        return False


def get_active_bids_for_posting(
    db_session: Session,
    posting_id: str,
    marketplace_id: str
) -> list[Bid]:
    """
    Get all ACTIVE bids for a posting.
    
    Args:
        db_session: SQLAlchemy database session
        posting_id: Marketplace posting ID
        marketplace_id: Marketplace identifier
        
    Returns:
        List of Bid objects with ACTIVE status
    """
    try:
        bids = db_session.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id,
            Bid.status == BidStatus.ACTIVE
        ).all()
        
        return bids
        
    except Exception as e:
        logger.error(
            f"Error querying active bids for {marketplace_id}:{posting_id}: {e}",
            exc_info=True
        )
        return []


def get_bids_by_status(
    db_session: Session,
    marketplace_id: str,
    status: BidStatus
) -> list[Bid]:
    """
    Get all bids for a marketplace with a specific status.
    
    Args:
        db_session: SQLAlchemy database session
        marketplace_id: Marketplace identifier
        status: BidStatus to filter by
        
    Returns:
        List of Bid objects
    """
    try:
        bids = db_session.query(Bid).filter(
            Bid.marketplace == marketplace_id,
            Bid.status == status
        ).all()
        
        return bids
        
    except Exception as e:
        logger.error(
            f"Error querying bids with status {status.value}: {e}",
            exc_info=True
        )
        return []
