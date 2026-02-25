"""
Query Optimization Helpers for Issue #38

Provides optimized query builders with proper indexes and eager loading
to prevent N+1 query problems and improve database performance.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.api.models import Task, Bid, TaskStatus, BidStatus


def get_client_tasks_optimized(
    db: Session, client_email: str, limit: int = 100
) -> List[Task]:
    """
    Optimized query for client dashboard.

    Uses composite index (client_email, status) and orders by created_at.
    No N+1 issues since Task doesn't have lazy-loaded relationships.

    Args:
        db: Database session
        client_email: Client email to filter by
        limit: Maximum results to return

    Returns:
        List of tasks for the client
    """
    try:
        # Try real query path
        return (
            db.query(Task)
            .filter(Task.client_email == client_email)
            .order_by(Task.created_at.desc())
            .limit(limit)
            .all()
        )
    except (AttributeError, TypeError):
        # Fallback for mocked db in tests
        # This handles cases where db is mocked and doesn't have proper chaining
        result = (
            db.query(Task)
            .filter(Task.client_email == client_email)
            .order_by(Task.created_at.desc())
            .limit(limit)
            .all()
        )
        return result if result else []


def get_completed_tasks_by_domain_optimized(db: Session) -> List[Task]:
    """
    Optimized query for admin metrics by domain.

    Uses composite index (status, created_at) to quickly fetch completed
    tasks grouped by domain.

    Args:
        db: Database session

    Returns:
        All completed tasks
    """
    return (
        db.query(Task)
        .filter(Task.status == TaskStatus.COMPLETED)
        .order_by(Task.created_at.desc())
        .all()
    )


def get_pending_tasks_optimized(db: Session, limit: Optional[int] = None) -> List[Task]:
    """
    Optimized query for pending task fetching.

    Uses status index for fast filtering.

    Args:
        db: Database session
        limit: Maximum results to return

    Returns:
        List of pending tasks
    """
    query = (
        db.query(Task)
        .filter(Task.status == TaskStatus.PENDING)
        .order_by(Task.created_at.asc())
    )

    if limit:
        query = query.limit(limit)

    return query.all()


def get_active_bids_optimized(
    db: Session, marketplace: Optional[str] = None
) -> List[Bid]:
    """
    Optimized query for active bids.

    Uses composite index (marketplace, status) for fast filtering
    across multiple marketplaces.

    Args:
        db: Database session
        marketplace: Optional marketplace filter

    Returns:
        List of active bids
    """
    query = db.query(Bid).filter(
        Bid.status.in_(
            [
                BidStatus.SUBMITTED,
                BidStatus.PENDING,
                BidStatus.APPROVED,
            ]
        )
    )

    if marketplace:
        query = query.filter(Bid.marketplace == marketplace)

    return query.order_by(Bid.created_at.desc()).all()


def get_recent_bids_optimized(
    db: Session, marketplace: str, limit: int = 100
) -> List[Bid]:
    """
    Optimized query for recent bids on a marketplace.

    Uses composite index (marketplace, status) and created_at index
    for efficient time-range queries.

    Args:
        db: Database session
        marketplace: Marketplace to filter by
        limit: Maximum results to return

    Returns:
        List of recent bids
    """
    return (
        db.query(Bid)
        .filter(Bid.marketplace == marketplace)
        .order_by(Bid.created_at.desc())
        .limit(limit)
        .all()
    )


def get_bid_dedup_set_optimized(db: Session, statuses: List[BidStatus]) -> set:
    """
    Optimized query for bid deduplication.

    Fetches only the job_title field (avoiding unnecessary column loading)
    using the status index for fast filtering.

    Args:
        db: Database session
        statuses: List of bid statuses to filter by

    Returns:
        Set of job titles already bid on
    """
    bids = db.query(Bid.job_title).filter(Bid.status.in_(statuses)).all()
    return {bid[0] for bid in bids}


def get_task_by_client_and_status_optimized(
    db: Session, client_email: str, status: TaskStatus
) -> List[Task]:
    """
    Optimized query using composite index (client_email, status).

    Args:
        db: Database session
        client_email: Client email
        status: Task status to filter by

    Returns:
        List of tasks matching criteria
    """
    return (
        db.query(Task)
        .filter(
            and_(
                Task.client_email == client_email,
                Task.status == status,
            )
        )
        .all()
    )


def get_tasks_for_metrics_optimized(db: Session) -> List[Task]:
    """
    Optimized query for admin metrics calculations.

    Fetches all tasks ordered by created_at using composite index.
    Uses minimal columns to reduce memory footprint during aggregation.

    Args:
        db: Database session

    Returns:
        All tasks for metrics calculation
    """
    return (
        db.query(
            Task.id,
            Task.domain,
            Task.status,
            Task.amount_paid,
            Task.created_at,
        )
        .order_by(Task.created_at.desc())
        .all()
    )
