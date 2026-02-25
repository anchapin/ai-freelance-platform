"""Add database indexes for query optimization - Issue #38"""

from sqlalchemy import text
from src.api.database import engine


def add_indexes():
    """Add indexes on frequently queried columns"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_task_client_email ON task(client_email);",
        "CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);",
        "CREATE INDEX IF NOT EXISTS idx_task_created_at ON task(created_at);",
        "CREATE INDEX IF NOT EXISTS idx_bid_posting_id ON bid(posting_id);",
        "CREATE INDEX IF NOT EXISTS idx_bid_agent_id ON bid(agent_id);",
    ]

    with engine.connect() as conn:
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
        conn.commit()

    print("Database indexes created successfully")


if __name__ == "__main__":
    add_indexes()
