"""
Tests for Cost Tracker Module (Issue #94)
"""

import pytest
from src.api.database import SessionLocal
from src.api.models import CostEntry
from src.agent_execution.cost_tracker import (
    CostTracker,
    get_cost_tracker,
    reset_cost_tracker,
)
from src.config.config_manager import reset_instance


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_instance()
    reset_cost_tracker()
    yield


@pytest.fixture
def db_session():
    """Provide a database session for tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def cost_tracker():
    """Provide a cost tracker instance."""
    tracker = CostTracker()
    return tracker


class TestCostTracker:
    """Test suite for Cost Tracker module."""

    def test_initialization(self, cost_tracker):
        """Test that cost tracker initializes correctly."""
        assert cost_tracker is not None

    def test_track_cost(self, cost_tracker, db_session):
        """Test tracking a cost entry."""
        # Track a cost
        entry = cost_tracker.track_cost(
            cost_type="llm",
            cost_cents=500,  # $5
            description="GPT-4 API call",
            task_id="task-123",
        )

        assert entry is not None
        assert entry.id is not None
        assert entry.cost_type == "llm"
        assert entry.cost_cents == 500
        assert entry.cost_dollars == 5.0
        assert entry.task_id == "task-123"

        # Verify it's in the database
        saved_entry = db_session.query(CostEntry).filter_by(id=entry.id).first()
        assert saved_entry is not None
        assert saved_entry.cost_type == "llm"

    def test_add_revenue(self, cost_tracker):
        """Test adding revenue to cost entries."""
        # Track a cost first
        entry = cost_tracker.track_cost(
            cost_type="sandbox",
            cost_cents=1000,  # $10
            description="E2B sandbox execution",
            task_id="task-456",
        )

        # Add revenue for that task
        success = cost_tracker.add_revenue(
            revenue_cents=15000,  # $150
            task_id="task-456",
        )

        assert success is True

    def test_calculate_roi_by_marketplace(self, cost_tracker):
        """Test calculating ROI by marketplace."""
        # Track costs for different marketplaces
        cost_tracker.track_cost(
            cost_type="bid",
            cost_cents=100,
            marketplace="upwork",
        )

        cost_tracker.track_cost(
            cost_type="bid",
            cost_cents=200,
            marketplace="fiverr",
        )

        # Add revenue
        cost_tracker.add_revenue(revenue_cents=1000, task_id="task-upwork")
        cost_tracker.add_revenue(revenue_cents=2000, task_id="task-fiverr")

        # Calculate ROI
        roi = cost_tracker.calculate_roi_by_marketplace()

        assert "upwork" in roi
        assert "fiverr" in roi
        assert "roi_percentage" in roi["upwork"]
        assert "total_roi_dollars" in roi["upwork"]

    def test_calculate_roi_by_strategy(self, cost_tracker):
        """Test calculating ROI by strategy."""
        # Track costs for different strategies
        cost_tracker.track_cost(
            cost_type="llm",
            cost_cents=500,
            strategy_type="aggressive",
        )

        cost_tracker.track_cost(
            cost_type="llm",
            cost_cents=300,
            strategy_type="conservative",
        )

        # Add revenue
        cost_tracker.add_revenue(revenue_cents=5000, bid_id="bid-agg")
        cost_tracker.add_revenue(revenue_cents=3000, bid_id="bid-cons")

        # Calculate ROI
        roi = cost_tracker.calculate_roi_by_strategy()

        assert "aggressive" in roi
        assert "conservative" in roi
        assert "roi_percentage" in roi["aggressive"]

    def test_get_profitable_strategies(self, cost_tracker):
        """Test getting profitable strategies."""
        # Track multiple costs for a strategy
        for i in range(10):
            cost_tracker.track_cost(
                cost_type="llm",
                cost_cents=500,
                strategy_type="aggressive",
            )

        # Add revenue
        cost_tracker.add_revenue(revenue_cents=8000, bid_id="bid-test")

        # Get profitable strategies
        profitable = cost_tracker.get_profitable_strategies(min_entries=10)

        assert isinstance(profitable, list)

    def test_get_cost_history(self, cost_tracker):
        """Test getting cost history."""
        # Track multiple costs
        for i in range(5):
            cost_tracker.track_cost(
                cost_type="llm",
                cost_cents=100 * i,
                task_id=f"task-{i}",
            )

        # Get history
        history = cost_tracker.get_cost_history(limit=3)

        assert len(history) <= 3
        assert all(isinstance(entry, CostEntry) for entry in history)

    def test_singleton_instance(self):
        """Test that get_cost_tracker returns singleton."""
        tracker1 = get_cost_tracker()
        tracker2 = get_cost_tracker()

        assert tracker1 is tracker2


class TestCostEntryModel:
    """Test suite for CostEntry database model."""

    def test_cost_entry_creation(self, db_session):
        """Test creating a CostEntry record."""
        entry = CostEntry(
            id="cost-1",
            cost_type="llm",
            cost_cents=500,
            cost_dollars=5.0,
            description="API call",
            task_id="task-123",
            revenue_cents=5000,
            revenue_dollars=50.0,
        )

        db_session.add(entry)
        db_session.commit()

        # Verify it was saved
        saved_entry = db_session.query(CostEntry).filter_by(id="cost-1").first()
        assert saved_entry is not None
        assert saved_entry.cost_type == "llm"

    def test_cost_entry_to_dict(self):
        """Test to_dict method of CostEntry."""
        entry = CostEntry(
            id="cost-2",
            cost_type="sandbox",
            cost_cents=1000,
            cost_dollars=10.0,
        )

        entry_dict = entry.to_dict()

        assert "id" in entry_dict
        assert "cost_dollars" in entry_dict
        assert entry_dict["cost_dollars"] == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
