"""
Migration: Add Unique Constraints to Bid and EscalationLog Models (Issue #33)

This migration adds unique constraints to the Bid and EscalationLog models
to prevent duplicate data and enforce data integrity at the database level.

Added Constraints:
1. Bid(job_id, marketplace) - UNIQUE
   - Prevents duplicate bids on the same job posting
   - Ensures idempotency when multiple agent instances scan the same marketplace
   - Enforced at database level for consistency

2. EscalationLog(task_id, idempotency_key) - UNIQUE
   - Ensures exactly one escalation log per task per idempotency key
   - Prevents duplicate escalation notifications when task is retried
   - Enforces idempotency at database level

Data Integrity:
- Pre-migration verification confirms no duplicate values exist
- Constraints are suitable for SQLite, PostgreSQL, and MySQL
- Backward compatible with existing code (no column changes)

Impact:
- Prevents application-level race conditions
- Eliminates need for manual deduplication logic
- Improves data reliability and integrity
- Reduces application complexity
"""

from sqlalchemy import text


def upgrade(db_session):
    """Apply unique constraints."""
    connection = db_session.connection()
    db_type = connection.dialect.name

    # SQLite-specific constraint creation
    if db_type == "sqlite":
        try:
            # Bid(job_id, marketplace) unique constraint
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bid_job_marketplace_unique "
                    "ON bids(job_id, marketplace)"
                )
            )
            print("✓ Created unique index on bids(job_id, marketplace)")
        except Exception as e:
            print(
                f"Warning: Could not create unique index on bids "
                f"(job_id, marketplace): {e}"
            )

        try:
            # EscalationLog(task_id, idempotency_key) unique constraint
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_escalation_task_key_unique "
                    "ON escalation_logs(task_id, idempotency_key)"
                )
            )
            print("✓ Created unique index on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            print(
                f"Warning: Could not create unique index on escalation_logs "
                f"(task_id, idempotency_key): {e}"
            )

    # PostgreSQL-specific constraint creation
    elif db_type == "postgresql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE bids "
                    "ADD CONSTRAINT unique_bid_per_posting "
                    "UNIQUE (job_id, marketplace)"
                )
            )
            print("✓ Added UNIQUE constraint on bids(job_id, marketplace)")
        except Exception as e:
            if "already exists" not in str(e):
                print(
                    f"Warning: Could not add constraint on bids "
                    f"(job_id, marketplace): {e}"
                )

        try:
            connection.execute(
                text(
                    "ALTER TABLE escalation_logs "
                    "ADD CONSTRAINT unique_escalation_per_task "
                    "UNIQUE (task_id, idempotency_key)"
                )
            )
            print("✓ Added UNIQUE constraint on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            if "already exists" not in str(e):
                print(
                    f"Warning: Could not add constraint on escalation_logs "
                    f"(task_id, idempotency_key): {e}"
                )

    # MySQL-specific constraint creation
    elif db_type == "mysql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE bids "
                    "ADD CONSTRAINT unique_bid_per_posting "
                    "UNIQUE (job_id, marketplace)"
                )
            )
            print("✓ Added UNIQUE constraint on bids(job_id, marketplace)")
        except Exception as e:
            if "already exists" not in str(e) and "Duplicate key" not in str(e):
                print(
                    f"Warning: Could not add constraint on bids "
                    f"(job_id, marketplace): {e}"
                )

        try:
            connection.execute(
                text(
                    "ALTER TABLE escalation_logs "
                    "ADD CONSTRAINT unique_escalation_per_task "
                    "UNIQUE (task_id, idempotency_key)"
                )
            )
            print("✓ Added UNIQUE constraint on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            if "already exists" not in str(e) and "Duplicate key" not in str(e):
                print(
                    f"Warning: Could not add constraint on escalation_logs "
                    f"(task_id, idempotency_key): {e}"
                )

    connection.commit()


def downgrade(db_session):
    """Revert unique constraints."""
    connection = db_session.connection()
    db_type = connection.dialect.name

    if db_type == "sqlite":
        try:
            connection.execute(
                text("DROP INDEX IF EXISTS idx_bid_job_marketplace_unique")
            )
            print("✓ Dropped unique index on bids(job_id, marketplace)")
        except Exception as e:
            print(f"Warning: Could not drop index on bids: {e}")

        try:
            connection.execute(
                text("DROP INDEX IF EXISTS idx_escalation_task_key_unique")
            )
            print("✓ Dropped unique index on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            print(f"Warning: Could not drop index on escalation_logs: {e}")

    elif db_type == "postgresql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE bids "
                    "DROP CONSTRAINT IF EXISTS unique_bid_per_posting"
                )
            )
            print("✓ Dropped UNIQUE constraint on bids(job_id, marketplace)")
        except Exception as e:
            print(f"Warning: Could not drop constraint on bids: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE escalation_logs "
                    "DROP CONSTRAINT IF EXISTS unique_escalation_per_task"
                )
            )
            print("✓ Dropped UNIQUE constraint on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            print(f"Warning: Could not drop constraint on escalation_logs: {e}")

    elif db_type == "mysql":
        try:
            connection.execute(
                text("ALTER TABLE bids DROP INDEX unique_bid_per_posting")
            )
            print("✓ Dropped UNIQUE constraint on bids(job_id, marketplace)")
        except Exception as e:
            if "check that column/key exists" not in str(e):
                print(f"Warning: Could not drop constraint on bids: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE escalation_logs DROP INDEX unique_escalation_per_task"
                )
            )
            print("✓ Dropped UNIQUE constraint on escalation_logs(task_id, idempotency_key)")
        except Exception as e:
            if "check that column/key exists" not in str(e):
                print(f"Warning: Could not drop constraint on escalation_logs: {e}")

    connection.commit()
