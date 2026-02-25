import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

# Get the database URL from environment variable or use default SQLite path
# Use absolute path to ensure data directory is at project root
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{os.path.join(PROJECT_ROOT, 'data', 'tasks.db')}"
)

# Create engine based on database type
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
        if "check_same_thread" not in DATABASE_URL
        else {},
        echo=False,
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

# Create SessionLocal class for creating database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize the database by creating all tables."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
