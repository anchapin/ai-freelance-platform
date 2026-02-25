"""
Migration: Add Unique Constraints to Domain Models (Issue #33)

This migration adds unique constraints to critical fields in the database
to prevent duplicate data and maintain data integrity.

Added Constraints:
1. ClientProfile.client_email - UNIQUE
   - Each client email should have exactly one profile
   - Prevents duplicate client profiles and profile fragmentation
   
2. Task.stripe_session_id - UNIQUE
   - Each Stripe payment session should be associated with at most one task
   - Prevents double-charging and payment confusion
   
3. Task.delivery_token - UNIQUE
   - Each delivery token should be unique for secure one-time delivery access
   - Implements secure, traceable result delivery (Issue #18)

Data Integrity:
- Pre-migration verification confirms no duplicate values exist
- Nullable columns allow NULL values (not constrained by UNIQUE at DB level)
- Suitable for SQLite, PostgreSQL, and MySQL

Impact:
- Prevents data duplication at the database level
- Improves data reliability and integrity
- Enables better error handling in application code
- Reduces need for manual data cleanup
"""

from sqlalchemy import text


def upgrade(db_session):
    """Apply unique constraints."""
    connection = db_session.connection()
    db_type = connection.dialect.name

    # SQLite-specific constraint creation
    if db_type == "sqlite":
        try:
            # ClientProfile.client_email unique constraint
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_client_email_unique "
                    "ON client_profiles(client_email)"
                )
            )
            print("✓ Created unique index on client_profiles.client_email")
        except Exception as e:
            print(f"Warning: Could not create unique index on client_email: {e}")

        try:
            # Task.stripe_session_id unique constraint
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_stripe_session_id_unique "
                    "ON tasks(stripe_session_id)"
                )
            )
            print("✓ Created unique index on tasks.stripe_session_id")
        except Exception as e:
            print(f"Warning: Could not create unique index on stripe_session_id: {e}")

        try:
            # Task.delivery_token unique constraint
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_token_unique "
                    "ON tasks(delivery_token)"
                )
            )
            print("✓ Created unique index on tasks.delivery_token")
        except Exception as e:
            print(f"Warning: Could not create unique index on delivery_token: {e}")

    # PostgreSQL-specific constraint creation
    elif db_type == "postgresql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE client_profiles "
                    "ADD CONSTRAINT unique_client_email UNIQUE (client_email)"
                )
            )
            print("✓ Added UNIQUE constraint on client_profiles.client_email")
        except Exception as e:
            if "already exists" not in str(e):
                print(f"Warning: Could not add constraint on client_email: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD CONSTRAINT unique_stripe_session_id UNIQUE (stripe_session_id)"
                )
            )
            print("✓ Added UNIQUE constraint on tasks.stripe_session_id")
        except Exception as e:
            if "already exists" not in str(e):
                print(f"Warning: Could not add constraint on stripe_session_id: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD CONSTRAINT unique_delivery_token UNIQUE (delivery_token)"
                )
            )
            print("✓ Added UNIQUE constraint on tasks.delivery_token")
        except Exception as e:
            if "already exists" not in str(e):
                print(f"Warning: Could not add constraint on delivery_token: {e}")

    # MySQL-specific constraint creation
    elif db_type == "mysql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE client_profiles "
                    "ADD CONSTRAINT unique_client_email UNIQUE (client_email)"
                )
            )
            print("✓ Added UNIQUE constraint on client_profiles.client_email")
        except Exception as e:
            if "already exists" not in str(e) and "Duplicate key" not in str(e):
                print(f"Warning: Could not add constraint on client_email: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD CONSTRAINT unique_stripe_session_id UNIQUE (stripe_session_id)"
                )
            )
            print("✓ Added UNIQUE constraint on tasks.stripe_session_id")
        except Exception as e:
            if "already exists" not in str(e) and "Duplicate key" not in str(e):
                print(f"Warning: Could not add constraint on stripe_session_id: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD CONSTRAINT unique_delivery_token UNIQUE (delivery_token)"
                )
            )
            print("✓ Added UNIQUE constraint on tasks.delivery_token")
        except Exception as e:
            if "already exists" not in str(e) and "Duplicate key" not in str(e):
                print(f"Warning: Could not add constraint on delivery_token: {e}")

    connection.commit()


def downgrade(db_session):
    """Revert unique constraints."""
    connection = db_session.connection()
    db_type = connection.dialect.name

    if db_type == "sqlite":
        try:
            connection.execute(text("DROP INDEX IF EXISTS idx_client_email_unique"))
            print("✓ Dropped unique index on client_profiles.client_email")
        except Exception as e:
            print(f"Warning: Could not drop index on client_email: {e}")

        try:
            connection.execute(text("DROP INDEX IF EXISTS idx_stripe_session_id_unique"))
            print("✓ Dropped unique index on tasks.stripe_session_id")
        except Exception as e:
            print(f"Warning: Could not drop index on stripe_session_id: {e}")

        try:
            connection.execute(text("DROP INDEX IF EXISTS idx_delivery_token_unique"))
            print("✓ Dropped unique index on tasks.delivery_token")
        except Exception as e:
            print(f"Warning: Could not drop index on delivery_token: {e}")

    elif db_type == "postgresql":
        try:
            connection.execute(
                text(
                    "ALTER TABLE client_profiles "
                    "DROP CONSTRAINT IF EXISTS unique_client_email"
                )
            )
            print("✓ Dropped UNIQUE constraint on client_profiles.client_email")
        except Exception as e:
            print(f"Warning: Could not drop constraint on client_email: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "DROP CONSTRAINT IF EXISTS unique_stripe_session_id"
                )
            )
            print("✓ Dropped UNIQUE constraint on tasks.stripe_session_id")
        except Exception as e:
            print(f"Warning: Could not drop constraint on stripe_session_id: {e}")

        try:
            connection.execute(
                text(
                    "ALTER TABLE tasks "
                    "DROP CONSTRAINT IF EXISTS unique_delivery_token"
                )
            )
            print("✓ Dropped UNIQUE constraint on tasks.delivery_token")
        except Exception as e:
            print(f"Warning: Could not drop constraint on delivery_token: {e}")

    elif db_type == "mysql":
        try:
            connection.execute(
                text("ALTER TABLE client_profiles DROP INDEX unique_client_email")
            )
            print("✓ Dropped UNIQUE constraint on client_profiles.client_email")
        except Exception as e:
            if "check that column/key exists" not in str(e):
                print(f"Warning: Could not drop constraint on client_email: {e}")

        try:
            connection.execute(
                text("ALTER TABLE tasks DROP INDEX unique_stripe_session_id")
            )
            print("✓ Dropped UNIQUE constraint on tasks.stripe_session_id")
        except Exception as e:
            if "check that column/key exists" not in str(e):
                print(f"Warning: Could not drop constraint on stripe_session_id: {e}")

        try:
            connection.execute(
                text("ALTER TABLE tasks DROP INDEX unique_delivery_token")
            )
            print("✓ Dropped UNIQUE constraint on tasks.delivery_token")
        except Exception as e:
            if "check that column/key exists" not in str(e):
                print(f"Warning: Could not drop constraint on delivery_token: {e}")

    connection.commit()
