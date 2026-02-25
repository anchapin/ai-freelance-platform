"""
Bid Deduplication and Placement Logic

This module implements deduplication checks to prevent placing bids on
marketplace postings where we've already placed bids.

Includes atomic bid creation (compare-and-set) to prevent TOCTOU race
conditions in multi-instance deployments.

Issue #8:  Implement distributed lock and deduplication for marketplace bids
Issue #19: Atomic bid creation to prevent duplicate bids across processes
Issue #40: Database race condition in bid withdrawal with transactions
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import uuid

from src.api.models import Bid, BidStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default posting cache TTL in hours
DEFAULT_POSTING_TTL_HOURS = 24


async def should_bid(
    db_session: Session,
    posting_id: str,
    marketplace_id: str,
    ttl_hours: int = DEFAULT_POSTING_TTL_HOURS,
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
        existing_bid = (
            db_session.query(Bid)
            .filter(
                Bid.job_id == posting_id,
                Bid.marketplace == marketplace_id,
                Bid.status == BidStatus.ACTIVE,
            )
            .first()
        )

        if existing_bid:
            logger.warning(
                f"Deduplication: Found existing ACTIVE bid {existing_bid.id} "
                f"for posting {marketplace_id}:{posting_id}"
            )
            return False

        # Check posting freshness (if we have a cached timestamp)
        # If the posting was cached more than TTL_HOURS ago, it might be stale
        stale_bids = (
            db_session.query(Bid)
            .filter(
                Bid.job_id == posting_id,
                Bid.marketplace == marketplace_id,
                Bid.posting_cached_at.isnot(None),
                Bid.status.in_([BidStatus.ACTIVE, BidStatus.SUBMITTED]),
            )
            .all()
        )

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
            f"Deduplication check passed: ok to bid on {marketplace_id}:{posting_id}"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error checking deduplication for {marketplace_id}:{posting_id}: {e}",
            exc_info=True,
        )
        # Conservative approach: if we can't check, don't bid
        return False


async def mark_bid_withdrawn(db_session: Session, bid_id: str, reason: str) -> bool:
    """
    Mark a bid as withdrawn using atomic transaction.

    Uses SQLAlchemy transaction to ensure atomicity and prevent race conditions.
    Records atomic event ID for idempotency and debugging.

    Args:
        db_session: SQLAlchemy database session
        bid_id: Bid ID to withdraw
        reason: Reason for withdrawal

    Returns:
        True if successful, False otherwise
    """
    # Generate event ID for idempotent operations (Issue #40)
    event_id = str(uuid.uuid4())

    try:
        # Use nested transaction (savepoint) for rollback safety
        savepoint = db_session.begin_nested()

        try:
            # Query with SELECT FOR UPDATE to prevent race conditions
            bid = (
                db_session.query(Bid).filter(Bid.id == bid_id).with_for_update().first()
            )

            if not bid:
                logger.error(f"[{event_id}] Bid {bid_id} not found")
                savepoint.rollback()
                return False

            if bid.status not in [BidStatus.ACTIVE, BidStatus.SUBMITTED]:
                logger.warning(
                    f"[{event_id}] Cannot withdraw bid {bid_id} with status "
                    f"{bid.status.value}"
                )
                savepoint.rollback()
                return False

            # Store previous state for audit trail
            previous_status = bid.status.value if bid.status else None

            # Atomic update
            bid.status = BidStatus.WITHDRAWN
            bid.withdrawn_reason = reason
            bid.withdrawal_timestamp = datetime.now(timezone.utc)
            bid.updated_at = datetime.now(timezone.utc)

            # Commit savepoint (part of larger transaction)
            savepoint.commit()

            # Atomic logging (Issue #40)
            logger.info(
                f"[{event_id}] Bid {bid_id} withdrawn: {reason} "
                f"(status: {previous_status} -> WITHDRAWN)"
            )
            return True

        except Exception as inner_e:
            # Rollback savepoint on error
            savepoint.rollback()
            logger.error(
                f"[{event_id}] Error in transaction for bid {bid_id}: {inner_e}",
                exc_info=True,
            )
            return False

    except Exception as e:
        logger.error(
            f"[{event_id}] Error withdrawing bid {bid_id}: {e}",
            exc_info=True,
        )
        db_session.rollback()
        return False


def get_active_bids_for_posting(
    db_session: Session, posting_id: str, marketplace_id: str
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
        bids = (
            db_session.query(Bid)
            .filter(
                Bid.job_id == posting_id,
                Bid.marketplace == marketplace_id,
                Bid.status == BidStatus.ACTIVE,
            )
            .all()
        )

        return bids

    except Exception as e:
        logger.error(
            f"Error querying active bids for {marketplace_id}:{posting_id}: {e}",
            exc_info=True,
        )
        return []


def get_bids_by_status(
    db_session: Session, marketplace_id: str, status: BidStatus
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
        bids = (
            db_session.query(Bid)
            .filter(Bid.marketplace == marketplace_id, Bid.status == status)
            .all()
        )

        return bids

    except Exception as e:
        logger.error(
            f"Error querying bids with status {status.value}: {e}", exc_info=True
        )
        return []


async def create_bid_atomically(
    db_session: Session,
    posting_id: str,
    marketplace_id: str,
    job_title: str,
    job_description: str,
    bid_amount: int,
    proposal: str = None,
    job_url: str = None,
    evaluation_reasoning: str = None,
    evaluation_confidence: int = None,
    skills_matched: list = None,
) -> Bid | None:
    """
    Atomically create a bid, preventing duplicates via the unique constraint.

    If another process already inserted an ACTIVE bid for the same
    (marketplace, job_id, status), the IntegrityError is caught and None
    is returned instead of raising.

    Args:
        db_session: SQLAlchemy database session
        posting_id: Marketplace posting ID
        marketplace_id: Marketplace identifier
        job_title: Title of the job
        job_description: Description of the job
        bid_amount: Bid amount in cents
        proposal: Generated proposal text
        job_url: URL to the job posting
        evaluation_reasoning: Reasoning from LLM evaluation
        evaluation_confidence: Confidence score 0-100
        skills_matched: List of matched skills

    Returns:
        The created Bid object, or None if a duplicate was detected
    """
    bid = Bid(
        job_title=job_title,
        job_description=job_description,
        job_url=job_url,
        job_id=posting_id,
        bid_amount=bid_amount,
        proposal=proposal,
        status=BidStatus.ACTIVE,
        is_suitable=True,
        evaluation_reasoning=evaluation_reasoning,
        evaluation_confidence=evaluation_confidence,
        marketplace=marketplace_id,
        skills_matched=skills_matched,
        posting_cached_at=datetime.now(timezone.utc),
    )

    try:
        db_session.add(bid)
        db_session.commit()
        logger.info(f"Atomic bid created: {bid.id} for {marketplace_id}:{posting_id}")
        return bid
    except IntegrityError:
        db_session.rollback()
        logger.warning(
            f"Duplicate bid prevented (atomic): "
            f"{marketplace_id}:{posting_id} already has an ACTIVE bid"
        )
        return None
    except Exception as e:
        db_session.rollback()
        logger.error(
            f"Error creating atomic bid for {marketplace_id}:{posting_id}: {e}",
            exc_info=True,
        )
        return None
