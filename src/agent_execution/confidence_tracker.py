"""
Confidence Tracker Module for Autonomy

Measures agent's performance and recommends bid thresholds based on
historical win rates, profit margins, and risk factors.

Issue #96: Confidence Tracker Module

Features:
- Track win history with confidence scores
- Calculate confidence scores based on multiple factors
- Recommend bid threshold adjustments
- Self-adjusting algorithm for continuous improvement
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Index,
)
from sqlalchemy.orm import declarative_base

from ..api.database import SessionLocal
from ..api.models import Base
from ..config.config_manager import ConfigManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ConfidenceEntry(Base):
    """
    Confidence Entry Database Model

    Stores bid history with outcomes for confidence calculation.
    Tracks win rates, profit margins, and streak information.
    """

    __tablename__ = "confidence_entries"

    __table_args__ = (
        Index("idx_conf_threshold", "threshold"),
        Index("idx_conf_won", "won"),
        Index("idx_conf_created_at", "created_at"),
    )

    id = Column(String, primary_key=True)

    # Bid details
    threshold = Column(Integer, nullable=False, index=True)
    bid_amount_cents = Column(Integer, nullable=False)
    job_title = Column(String, nullable=True)
    marketplace = Column(String, nullable=True)

    # Outcome
    won = Column(Boolean, nullable=False, index=True)
    profit_cents = Column(Integer, nullable=True)
    profit_dollars = Column(Float, nullable=True)

    # Confidence factors
    confidence_score = Column(Integer, nullable=True)
    evaluation_confidence = Column(Integer, nullable=True)

    # Streak tracking
    win_streak_before = Column(Integer, default=0)
    loss_streak_before = Column(Integer, default=0)
    consecutive_wins_after = Column(Integer, default=0)
    consecutive_losses_after = Column(Integer, default=0)

    # Metadata
    strategy_type = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert confidence entry to dictionary."""
        return {
            "id": self.id,
            "threshold": self.threshold,
            "bid_amount_dollars": self.bid_amount_cents / 100,
            "bid_amount_cents": self.bid_amount_cents,
            "job_title": self.job_title,
            "marketplace": self.marketplace,
            "won": self.won,
            "profit_dollars": self.profit_dollars,
            "profit_cents": self.profit_cents,
            "confidence_score": self.confidence_score,
            "evaluation_confidence": self.evaluation_confidence,
            "win_streak_before": self.win_streak_before,
            "loss_streak_before": self.loss_streak_before,
            "consecutive_wins_after": self.consecutive_wins_after,
            "consecutive_losses_after": self.consecutive_losses_after,
            "strategy_type": self.strategy_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ConfidenceTracker:
    """
    Confidence Tracker for Bid Threshold Optimization

    Calculates confidence scores based on historical performance and
    recommends optimal bid thresholds for maximum profitability.

    Factors considered:
    - Win rate at current threshold
    - Average profit margin per win
    - Consecutive wins/losses streaks
    - Risk adjustment (variance in outcomes)
    """

    def __init__(self):
        """Initialize Confidence Tracker."""
        self.current_streak_wins = 0
        self.current_streak_losses = 0
        self._load_current_streaks()

    def _load_current_streaks(self):
        """Load current win/loss streaks from database."""
        db = SessionLocal()
        try:
            # Get the most recent entry to determine current streaks
            last_entry = (
                db.query(ConfidenceEntry)
                .order_by(ConfidenceEntry.created_at.desc())
                .first()
            )

            if last_entry:
                self.current_streak_wins = last_entry.consecutive_wins_after
                self.current_streak_losses = last_entry.consecutive_losses_after

            logger.info(
                f"Loaded streaks - Wins: {self.current_streak_wins}, "
                f"Losses: {self.current_streak_losses}"
            )
        finally:
            db.close()

    def record_bid(
        self,
        threshold: int,
        bid_amount_cents: int,
        job_title: Optional[str] = None,
        marketplace: Optional[str] = None,
        evaluation_confidence: Optional[int] = None,
        strategy_type: Optional[str] = None,
    ) -> ConfidenceEntry:
        """
        Record a bid for confidence tracking.

        Args:
            threshold: Confidence threshold used for bid
            bid_amount_cents: Bid amount in cents
            job_title: Optional job title
            marketplace: Optional marketplace identifier
            evaluation_confidence: LLM evaluation confidence (0-100)
            strategy_type: Bidding strategy type

        Returns:
            ConfidenceEntry: The created confidence entry
        """
        db = SessionLocal()
        try:
            import uuid

            # Calculate confidence score
            confidence_score = self.calculate_confidence_score(threshold)

            # Create entry
            entry = ConfidenceEntry(
                id=str(uuid.uuid4()),
                threshold=threshold,
                bid_amount_cents=bid_amount_cents,
                job_title=job_title,
                marketplace=marketplace,
                won=False,  # Will be updated when outcome is known
                confidence_score=confidence_score,
                evaluation_confidence=evaluation_confidence,
                win_streak_before=self.current_streak_wins,
                loss_streak_before=self.current_streak_losses,
                strategy_type=strategy_type,
                created_at=datetime.utcnow(),
            )

            db.add(entry)
            db.commit()
            db.refresh(entry)

            logger.info(
                f"Recorded bid - Threshold: {threshold}, "
                f"Amount: ${bid_amount_cents / 100:.2f}, "
                f"Confidence: {confidence_score}"
            )

            return entry

        except Exception as e:
            logger.error(f"Failed to record bid: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def update_outcome(
        self,
        entry_id: str,
        won: bool,
        profit_cents: Optional[int] = None,
    ) -> bool:
        """
        Update bid outcome and recalculate streaks.

        Args:
            entry_id: ID of the confidence entry to update
            won: Whether the bid was won
            profit_cents: Profit amount in cents (if won)

        Returns:
            True if update successful
        """
        db = SessionLocal()
        try:
            # Find entry
            entry = db.query(ConfidenceEntry).filter_by(id=entry_id).first()

            if not entry:
                logger.error(f"Confidence entry not found: {entry_id}")
                return False

            # Update outcome
            entry.won = won
            entry.profit_cents = profit_cents
            entry.profit_dollars = profit_cents / 100 if profit_cents else None

            # Update streaks
            if won:
                self.current_streak_wins += 1
                self.current_streak_losses = 0
            else:
                self.current_streak_wins = 0
                self.current_streak_losses += 1

            entry.consecutive_wins_after = self.current_streak_wins
            entry.consecutive_losses_after = self.current_streak_losses

            db.commit()

            logger.info(
                f"Updated outcome - Won: {won}, "
                f"Profit: ${profit_cents / 100:.2f if profit_cents else 0}, "
                f"Win Streak: {self.current_streak_wins}, "
                f"Loss Streak: {self.current_streak_losses}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to update outcome: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def calculate_confidence_score(self, threshold: int) -> int:
        """
        Calculate confidence score for a threshold.

        Factors:
        - Historical win rate at this threshold
        - Average profit margin
        - Current win/loss streaks
        - Risk adjustment (variance)

        Args:
            threshold: Confidence threshold to evaluate

        Returns:
            Confidence score (0-100)
        """
        db = SessionLocal()
        try:
            # Get all entries for this threshold
            entries = (
                db.query(ConfidenceEntry)
                .filter(ConfidenceEntry.threshold == threshold)
                .all()
            )

            if not entries:
                # Default confidence for new thresholds
                return 50

            # Calculate win rate
            total = len(entries)
            wins = sum(1 for e in entries if e.won)
            win_rate = wins / total if total > 0 else 0

            # Calculate average profit margin
            profitable_entries = [e for e in entries if e.won and e.profit_cents]
            if profitable_entries:
                avg_profit = sum(e.profit_cents for e in profitable_entries) / len(
                    profitable_entries
                )
                profit_factor = min(avg_profit / 5000, 1.0)  # Normalize to $50 profit
            else:
                profit_factor = 0

            # Streak factor
            streak_factor = 0
            if self.current_streak_wins > 2:
                streak_factor = min(self.current_streak_wins / 10, 0.2)
            elif self.current_streak_losses > 2:
                streak_factor = -min(self.current_streak_losses / 10, 0.2)

            # Risk adjustment (variance in outcomes)
            variance = self._calculate_variance(entries)
            risk_factor = max(0, 1 - variance / 10000)  # Penalize high variance

            # Calculate final score (0-100)
            score = (
                win_rate * 60  # 60% weight on win rate
                + profit_factor * 20  # 20% weight on profit
                + streak_factor * 10  # 10% weight on current streak
                + risk_factor * 10  # 10% weight on risk
            )

            return int(max(0, min(100, score)))

        finally:
            db.close()

    def _calculate_variance(self, entries: List[ConfidenceEntry]) -> float:
        """Calculate variance in profit outcomes."""
        profits = [e.profit_cents for e in entries if e.profit_cents]

        if len(profits) < 2:
            return 0

        mean = sum(profits) / len(profits)
        variance = sum((p - mean) ** 2 for p in profits) / len(profits)

        return variance

    def get_recommended_threshold(self) -> Dict[str, Any]:
        """
        Get recommended bid threshold based on performance.

        Analyzes historical performance to recommend optimal threshold
        for maximizing profitability.

        Returns:
            Dictionary with recommended threshold and reasoning
        """
        db = SessionLocal()
        try:
            # Get all entries
            entries = db.query(ConfidenceEntry).all()

            if len(entries) < 10:
                return {
                    "recommended_threshold": 50,
                    "confidence": 50,
                    "reasoning": "Insufficient data - using default threshold of 50",
                    "min_entries_for_analysis": 10,
                    "current_entries": len(entries),
                }

            # Calculate stats for each threshold
            threshold_stats = {}

            for entry in entries:
                threshold = entry.threshold

                if threshold not in threshold_stats:
                    threshold_stats[threshold] = {
                        "total": 0,
                        "wins": 0,
                        "total_profit": 0,
                        "entries": [],
                    }

                stats = threshold_stats[threshold]
                stats["total"] += 1
                stats["entries"].append(entry)

                if entry.won:
                    stats["wins"] += 1
                    if entry.profit_cents:
                        stats["total_profit"] += entry.profit_cents

            # Calculate metrics for each threshold
            results = []

            for threshold, stats in threshold_stats.items():
                if stats["total"] < 5:
                    continue  # Skip thresholds with insufficient data

                win_rate = stats["wins"] / stats["total"]
                avg_profit = (
                    stats["total_profit"] / stats["wins"] if stats["wins"] > 0 else 0
                )
                expected_value = win_rate * avg_profit
                confidence_score = self.calculate_confidence_score(threshold)

                results.append(
                    {
                        "threshold": threshold,
                        "win_rate": win_rate,
                        "avg_profit_cents": avg_profit,
                        "expected_value_cents": expected_value,
                        "total_bids": stats["total"],
                        "confidence_score": confidence_score,
                    }
                )

            if not results:
                return {
                    "recommended_threshold": 50,
                    "confidence": 50,
                    "reasoning": "No thresholds with sufficient data - using default",
                }

            # Sort by expected value
            results.sort(key=lambda x: x["expected_value_cents"], reverse=True)

            best = results[0]

            # Generate reasoning
            reasoning = (
                f"Threshold {best['threshold']} has the highest expected value of "
                f"${best['expected_value_cents'] / 100:.2f} per bid with "
                f"{best['win_rate'] * 100:.1f}% win rate. "
                f"Confidence score: {best['confidence_score']}/100."
            )

            return {
                "recommended_threshold": best["threshold"],
                "confidence": best["confidence_score"],
                "win_rate": best["win_rate"],
                "expected_value_dollars": best["expected_value_cents"] / 100,
                "total_bids": best["total_bids"],
                "reasoning": reasoning,
                "all_thresholds": results[:5],  # Top 5 thresholds
            }

        finally:
            db.close()

    def get_threshold_summary(self, threshold: int) -> Dict[str, Any]:
        """
        Get detailed summary for a specific threshold.

        Args:
            threshold: Threshold to analyze

        Returns:
            Dictionary with threshold statistics
        """
        db = SessionLocal()
        try:
            entries = (
                db.query(ConfidenceEntry)
                .filter(ConfidenceEntry.threshold == threshold)
                .all()
            )

            if not entries:
                return {"error": f"No data found for threshold {threshold}"}

            total = len(entries)
            wins = sum(1 for e in entries if e.won)
            losses = total - wins

            win_rate = wins / total if total > 0 else 0

            profitable_entries = [e for e in entries if e.won and e.profit_cents]
            if profitable_entries:
                avg_profit = sum(e.profit_cents for e in profitable_entries) / len(
                    profitable_entries
                )
                max_profit = max(e.profit_cents for e in profitable_entries)
                min_profit = min(e.profit_cents for e in profitable_entries)
            else:
                avg_profit = 0
                max_profit = 0
                min_profit = 0

            # Get current confidence score
            confidence_score = self.calculate_confidence_score(threshold)

            return {
                "threshold": threshold,
                "total_bids": total,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "win_rate_percentage": win_rate * 100,
                "avg_profit_cents": avg_profit,
                "avg_profit_dollars": avg_profit / 100,
                "max_profit_cents": max_profit,
                "max_profit_dollars": max_profit / 100,
                "min_profit_cents": min_profit,
                "min_profit_dollars": min_profit / 100,
                "confidence_score": confidence_score,
            }

        finally:
            db.close()

    def get_recent_history(
        self,
        limit: int = 50,
        threshold: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent confidence tracking history.

        Args:
            limit: Maximum number of entries to return
            threshold: Optional filter by threshold

        Returns:
            List of confidence entries
        """
        db = SessionLocal()
        try:
            query = db.query(ConfidenceEntry)

            if threshold:
                query = query.filter(ConfidenceEntry.threshold == threshold)

            query = query.order_by(ConfidenceEntry.created_at.desc()).limit(limit)

            entries = query.all()

            return [entry.to_dict() for entry in entries]

        finally:
            db.close()


# Global singleton instance
_confidence_tracker_instance: Optional[ConfidenceTracker] = None


def get_confidence_tracker() -> ConfidenceTracker:
    """Get or create global Confidence Tracker singleton."""
    global _confidence_tracker_instance

    if _confidence_tracker_instance is None:
        _confidence_tracker_instance = ConfidenceTracker()

    return _confidence_tracker_instance


def reset_confidence_tracker():
    """Reset confidence tracker singleton (useful for testing)."""
    global _confidence_tracker_instance
    _confidence_tracker_instance = None
