"""
Tests for Training Mode & Simulation Engine (Issues #88, #89, #90, #91)
"""

import pytest
from datetime import datetime
from src.api.database import SessionLocal
from src.api.models import SimulationBid
from src.agent_execution.simulation_engine import (
    SimulationEngine,
    get_simulation_engine,
    reset_simulation_engine,
)
from src.config.config_manager import ConfigManager, reset_instance


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_instance()
    reset_simulation_engine()
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
def simulation_engine():
    """Provide a simulation engine instance."""
    engine = SimulationEngine()
    return engine


class TestSimulationEngine:
    """Test suite for Simulation Engine module."""

    def test_initialization(self, simulation_engine):
        """Test that simulation engine initializes correctly."""
        assert simulation_engine is not None
        assert hasattr(simulation_engine, "training_mode")

    def test_record_simulation_bid(self, simulation_engine, db_session):
        """Test recording a simulation bid."""
        # Record a simulation bid
        bid = simulation_engine.record_simulation_bid(
            job_title="Python Data Analysis",
            job_description="Need Python expert for data analysis",
            job_url="https://example.com/job/123",
            bid_amount_cents=10000,  # $100
            strategy_type="aggressive",
            confidence=80,
            would_have_won=True,
            outcome_reasoning="Good match",
            job_marketplace="upwork",
            skills_matched=["Python", "pandas"],
        )

        assert bid is not None
        assert bid.id is not None
        assert bid.job_title == "Python Data Analysis"
        assert bid.bid_amount == 10000
        assert bid.strategy_type == "aggressive"
        assert bid.would_have_won is True

        # Verify it's in the database
        saved_bid = db_session.query(SimulationBid).filter_by(id=bid.id).first()
        assert saved_bid is not None
        assert saved_bid.job_title == "Python Data Analysis"

    def test_calculate_total_profit(self, simulation_engine, db_session):
        """Test calculating total profit from simulations."""
        # Record multiple simulation bids
        simulation_engine.record_simulation_bid(
            job_title="Job 1",
            job_description="Description 1",
            job_url="https://example.com/1",
            bid_amount_cents=10000,
            strategy_type="aggressive",
            would_have_won=True,
        )

        simulation_engine.record_simulation_bid(
            job_title="Job 2",
            job_description="Description 2",
            job_url="https://example.com/2",
            bid_amount_cents=5000,
            strategy_type="conservative",
            would_have_won=False,
        )

        # Calculate total profit
        profit = simulation_engine.calculate_total_profit()

        assert profit["total_bids"] == 2
        assert profit["wins"] == 1
        assert profit["losses"] == 1
        assert profit["total_profit_cents"] == 5000  # $100 - $50
        assert profit["win_rate_percentage"] == 50.0

    def test_compare_strategies(self, simulation_engine, db_session):
        """Test comparing different bidding strategies."""
        # Record bids for different strategies
        for i in range(5):
            simulation_engine.record_simulation_bid(
                job_title=f"Aggressive Job {i}",
                job_description=f"Description {i}",
                job_url=f"https://example.com/agg{i}",
                bid_amount_cents=10000,
                strategy_type="aggressive",
                would_have_won=i < 3,  # 3 wins out of 5
            )

        for i in range(5):
            simulation_engine.record_simulation_bid(
                job_title=f"Conservative Job {i}",
                job_description=f"Description {i}",
                job_url=f"https://example.com/cons{i}",
                bid_amount_cents=5000,
                strategy_type="conservative",
                would_have_won=i < 2,  # 1 win out of 5
            )

        # Compare strategies
        comparison = simulation_engine.compare_strategies()

        assert "strategies" in comparison
        assert "best_strategy" in comparison
        assert "insights" in comparison
        assert len(comparison["insights"]) > 0

    def test_get_strategy_summary(self, simulation_engine):
        """Test getting summary for a specific strategy."""
        # Record bids for aggressive strategy
        for i in range(5):
            simulation_engine.record_simulation_bid(
                job_title=f"Job {i}",
                job_description=f"Description {i}",
                job_url=f"https://example.com/{i}",
                bid_amount_cents=10000,
                strategy_type="aggressive",
                would_have_won=i < 3,
            )

        # Get summary
        summary = simulation_engine.get_strategy_summary("aggressive")

        assert summary["strategy_type"] == "aggressive"
        assert summary["total_bids"] == 5
        assert summary["wins"] == 3
        assert summary["losses"] == 2
        assert "win_rate_percentage" in summary

    def test_get_recent_simulations(self, simulation_engine):
        """Test getting recent simulations."""
        # Record multiple bids
        for i in range(10):
            simulation_engine.record_simulation_bid(
                job_title=f"Job {i}",
                job_description=f"Description {i}",
                job_url=f"https://example.com/{i}",
                bid_amount_cents=5000,
                strategy_type="balanced",
                would_have_won=True,
            )

        # Get recent simulations with limit
        recent = simulation_engine.get_recent_simulations(limit=5)

        assert len(recent) == 5
        assert all(isinstance(sim, SimulationBid) for sim in recent)

    def test_date_filter(self, simulation_engine):
        """Test filtering simulations by date range."""
        # Record bid with specific date
        simulation_engine.record_simulation_bid(
            job_title="Job 1",
            job_description="Description 1",
            job_url="https://example.com/1",
            bid_amount_cents=5000,
            strategy_type="balanced",
            would_have_won=True,
        )

        # Calculate profit with date filter (should work without error)
        profit = simulation_engine.calculate_total_profit(
            date_filter={"start": "2026-01-01", "end": "2026-12-31"}
        )

        assert "total_profit_dollars" in profit


class TestTrainingMode:
    """Test suite for Training Mode functionality (Issue #88)."""

    def test_training_mode_config(self):
        """Test that training mode configuration exists."""
        training_mode = ConfigManager.get("TRAINING_MODE", False)
        assert isinstance(training_mode, bool)

    def test_set_training_mode(self):
        """Test setting training mode."""
        # Set to True
        ConfigManager._config_cache["TRAINING_MODE"] = True
        mode = ConfigManager.get("TRAINING_MODE", False)
        assert mode is True

        # Set to False
        ConfigManager._config_cache["TRAINING_MODE"] = False
        mode = ConfigManager.get("TRAINING_MODE", False)
        assert mode is False

    def test_singleton_instance(self):
        """Test that get_simulation_engine returns singleton."""
        engine1 = get_simulation_engine()
        engine2 = get_simulation_engine()

        assert engine1 is engine2


class TestSimulationBidModel:
    """Test suite for SimulationBid database model (Issue #90)."""

    def test_simulation_bid_creation(self, db_session):
        """Test creating a SimulationBid record."""
        bid = SimulationBid(
            id="test-id-1",
            job_title="Test Job",
            job_description="Test Description",
            job_url="https://example.com/test",
            bid_amount=10000,
            strategy_type="balanced",
            confidence=75,
            would_have_won=True,
            outcome_reasoning="Good fit",
            job_marketplace="upwork",
            skills_matched=["Python"],
            created_at=datetime.utcnow(),
        )

        db_session.add(bid)
        db_session.commit()

        # Verify it was saved
        saved_bid = db_session.query(SimulationBid).filter_by(id="test-id-1").first()
        assert saved_bid is not None
        assert saved_bid.job_title == "Test Job"
        assert saved_bid.strategy_type == "balanced"

    def test_simulation_bid_to_dict(self):
        """Test to_dict method of SimulationBid."""
        bid = SimulationBid(
            id="test-id-2",
            job_title="Test Job",
            job_description="Test Description",
            bid_amount=10000,
            strategy_type="balanced",
            would_have_won=True,
        )

        bid_dict = bid.to_dict()

        assert "id" in bid_dict
        assert "job_title" in bid_dict
        assert "bid_amount_dollars" in bid_dict
        assert bid_dict["bid_amount_dollars"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
