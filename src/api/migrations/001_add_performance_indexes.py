"""
Migration: Add Performance Indexes and Optimize Queries (Issue #38)

This migration adds strategic database indexes to improve query performance
and prevent N+1 query problems in the ArbitrageAI application.

Added Indexes:
- Task table:
  - idx_task_client_status: Composite index on (client_email, status)
  - idx_task_status_created: Composite index on (status, created_at)

- Bid table:
  - idx_bid_status: Single index on status
  - idx_bid_marketplace_status: Composite index on (marketplace, status)
  - idx_bid_created_at: Single index on created_at

These indexes support the following query patterns:
1. Dashboard queries filtering by client_email and status
2. Admin metrics aggregations by status
3. Time-range queries for both Task and Bid tables
4. Marketplace-specific bid queries
5. Bid deduplication with status filtering

Performance Impact:
- Expected 2-5x speedup on indexed queries
- Reduced CPU usage during aggregations
- Better query plan selectivity
"""

from sqlalchemy import text


def upgrade(db_session):
    """Apply the migration."""
    connection = db_session.connection()

    # Add composite index for client dashboard queries
    # This is used in get_client_tasks_optimized to filter by client_email and status
    try:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_task_client_status "
                "ON tasks(client_email, status)"
            )
        )
    except Exception as e:
        print(f"Index idx_task_client_status creation info: {e}")

    # Add composite index for admin metrics aggregations
    # This is used in admin metrics to filter by status and sort by created_at
    try:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_task_status_created "
                "ON tasks(status, created_at)"
            )
        )
    except Exception as e:
        print(f"Index idx_task_status_created creation info: {e}")

    # Add index on Bid status for filtering
    try:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS idx_bid_status ON bids(status)")
        )
    except Exception as e:
        print(f"Index idx_bid_status creation info: {e}")

    # Add composite index for marketplace-specific bid queries
    # This is used in get_active_bids_optimized and get_recent_bids_optimized
    try:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_bid_marketplace_status "
                "ON bids(marketplace, status)"
            )
        )
    except Exception as e:
        print(f"Index idx_bid_marketplace_status creation info: {e}")

    # Add index on Bid created_at for time-range queries
    try:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS idx_bid_created_at ON bids(created_at)")
        )
    except Exception as e:
        print(f"Index idx_bid_created_at creation info: {e}")

    connection.commit()


def downgrade(db_session):
    """Revert the migration."""
    connection = db_session.connection()

    indexes_to_drop = [
        "idx_task_client_status",
        "idx_task_status_created",
        "idx_bid_status",
        "idx_bid_marketplace_status",
        "idx_bid_created_at",
    ]

    for index_name in indexes_to_drop:
        try:
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        except Exception as e:
            print(f"Index {index_name} drop info: {e}")

    connection.commit()
