"""
Tests for Confidence Tracker Module (Issue #96)
"""

import pytest
from src.api.database import SessionLocal
from src.agent_execution.confidence_tracker import (
    ConfidenceTracker,
    get_confidence_tracker,
    reset_confidence_tracker,
)
from src.api.models import ConfidenceEntry
from src.config.config_manager import reset_instance


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_instance()
    reset_confidence_tracker()
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
def confidence_tracker():
    """Provide a confidence tracker instance."""
    tracker = ConfidenceTracker()
    return tracker


class TestConfidenceTracker:
    """Test suite for Confidence Tracker module."""

    def test_initialization(self, confidence_tracker):
        """Test that confidence tracker initializes correctly."""
        assert confidence_tracker is not None
        assert hasattr(confidence_tracker, "current_streak_wins")
        assert hasattr(confidence_tracker, "current_streak_losses")

    def test_record_bid(self, confidence_tracker):
        """Test recording a bid."""
        entry = confidence_tracker.record_bid(
            threshold=50,
            bid_amount_cents=10000,  # $100
            job_title="Python Data Analysis",
            marketplace="upwork",
            evaluation_confidence=80,
            strategy_type="balanced",
        )

        assert entry is not None
        assert entry.id is not None
        assert entry.threshold == 50
        assert entry.bid_amount_cents == 10000
        assert entry.won is False  # Initially false
        assert entry.strategy_type == "balanced"

    def test_update_outcome_win(self, confidence_tracker):
        """Test updating bid outcome as win."""
        # Record a bid
        entry = confidence_tracker.record_bid(
            threshold=50,
            bid_amount_cents=10000,
            job_title="Test Job",
        )

        # Update outcome as win
        success = confidence_tracker.update_outcome(
            entry_id=entry.id,
            won=True,
            profit_cents=5000,  # $50 profit
        )

        assert success is True
        assert confidence_tracker.current_streak_wins == 1
        assert confidence_tracker.current_streak_losses == 0

    def test_update_outcome_loss(self, confidence_tracker):
        """Test updating bid outcome as loss."""
        # Record a bid
        entry = confidence_tracker.record_bid(
            threshold=50,
            bid_amount_cents=10000,
            job_title="Test Job",
        )

        # Update outcome as loss
        success = confidence_tracker.update_outcome(
            entry_id=entry.id,
            won=False,
            profit_cents=None,
        )

        assert success is True
        assert confidence_tracker.current_streak_wins == 0
        assert confidence_tracker.current_streak_losses == 1

    def test_calculate_confidence_score(self, confidence_tracker):
        """Test calculating confidence score."""
        # Record multiple bids with outcomes
        for i in range(10):
            entry = confidence_tracker.record_bid(
                threshold=50,
                bid_amount_cents=10000,
                job_title=f"Job {i}",
            )
            confidence_tracker.update_outcome(
                entry_id=entry.id,
                won=(i < 7),  # 70% win rate
                profit_cents=5000 if i < 7 else None,
            )

        # Calculate confidence score
        score = confidence_tracker.calculate_confidence_score(50)

        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_get_recommended_threshold(self, confidence_tracker):
        """Test getting recommended threshold."""
        # Need at least 10 entries for recommendation
        for i in range(15):
            entry = confidence_tracker.record_bid(
                threshold=50 if i < 10 else 60,
                bid_amount_cents=10000,
                job_title=f"Job {i}",
            )
            confidence_tracker.update_outcome(
                entry_id=entry.id,
                won=(i < 10),  # Better performance at threshold 50
                profit_cents=5000 if i < 10 else 3000,
            )

        # Get recommendation
        recommendation = confidence_tracker.get_recommended_threshold()

        assert "recommended_threshold" in recommendation
        assert "confidence" in recommendation
        assert "reasoning" in recommendation

    def test_get_threshold_summary(self, confidence_tracker):
        """Test getting threshold summary."""
        # Record bids at a specific threshold
        for i in range(10):
            entry = confidence_tracker.record_bid(
                threshold=75,
                bid_amount_cents=10000,
                job_title=f"Job {i}",
            )
            confidence_tracker.update_outcome(
                entry_id=entry.id,
                won=(i < 6),  # 60% win rate
                profit_cents=5000 if i < 6 else None,
            )

        # Get summary
        summary = confidence_tracker.get_threshold_summary(75)

        assert "threshold" in summary
        assert summary["threshold"] == 75
        assert "total_bids" in summary
        assert summary["total_bids"] == 10
        assert "win_rate_percentage" in summary

    def test_get_recent_history(self, confidence_tracker):
        """Test getting recent history."""
        # Record multiple bids
        for i in range(20):
            entry = confidence_tracker.record_bid(
                threshold=50,
                bid_amount_cents=10000,
                job_title=f"Job {i}",
            )

        # Get recent history
        history = confidence_tracker.get_recent_history(limit=10)

        assert len(history) == 10
        assert all(isinstance(entry, dict) for entry in history)

    def test_streak_tracking(self, confidence_tracker):
        """Test that win/loss streaks are tracked correctly."""
        # Record winning streak
        entries = []
        for i in range(3):
            entry = confidence_tracker.record_bid(
                threshold=50,
                bid_amount_cents=10000,
                job_title=f"Win {i}",
            )
            entries.append(entry)
            confidence_tracker.update_outcome(
                entry_id=entry.id, won=True, profit_cents=5000
            )

        assert confidence_tracker.current_streak_wins == 3
        assert confidence_tracker.current_streak_losses == 0

        # Record loss
        entry = confidence_tracker.record_bid(
            threshold=50,
            bid_amount_cents=10000,
            job_title="Loss",
        )
        entries.append(entry)
        confidence_tracker.update_outcome(
            entry_id=entry.id, won=False, profit_cents=None
        )

        # Win streak should reset, loss streak should start
        assert confidence_tracker.current_streak_wins == 0
        assert confidence_tracker.current_streak_losses == 1

    def test_singleton_instance(self):
        """Test that get_confidence_tracker returns singleton."""
        tracker1 = get_confidence_tracker()
        tracker2 = get_confidence_tracker()

        assert tracker1 is tracker2


class TestConfidenceEntryModel:
    """Test suite for ConfidenceEntry database model."""

    def test_confidence_entry_creation(self, db_session):
        """Test creating a ConfidenceEntry record."""
        entry = ConfidenceEntry(
            id="conf-1",
            threshold=50,
            bid_amount_cents=10000,
            job_title="Python Developer",
            marketplace="upwork",
            won=True,
            profit_cents=5000,
            profit_dollars=50.0,
            confidence_score=75,
            win_streak_before=2,
            loss_streak_before=0,
            consecutive_wins_after=3,
            consecutive_losses_after=0,
            strategy_type="balanced",
        )

        db_session.add(entry)
        db_session.commit()

        # Verify it was saved
        saved_entry = db_session.query(ConfidenceEntry).filter_by(id="conf-1").first()
        assert saved_entry is not None
        assert saved_entry.threshold == 50
        assert saved_entry.won is True

    def test_confidence_entry_to_dict(self):
        """Test to_dict method of ConfidenceEntry."""
        entry = ConfidenceEntry(
            id="conf-2",
            threshold=75,
            bid_amount_cents=15000,
            won=False,
            confidence_score=60,
        )

        entry_dict = entry.to_dict()

        assert "id" in entry_dict
        assert "bid_amount_dollars" in entry_dict
        assert entry_dict["bid_amount_dollars"] == 150.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
