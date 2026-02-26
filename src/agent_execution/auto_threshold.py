"""
Auto-Threshold Increase Module

Implements automatic threshold increase when the agent consistently
performs well. Evaluates performance periodically and creates
petitions for human approval when criteria are met.

Issue #99: Auto-Threshold Increase (Option C)

Features:
- Periodic evaluation of agent performance
- Auto-creation of petitions when criteria met
- Configurable thresholds for evaluation
- Logging of all auto-increase attempts
"""

from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy.orm import Session

from ..api.database import SessionLocal
from ..api.models import ThresholdPetition, ConfidenceEntry
from ..config.config_manager import ConfigManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AutoThresholdStatus(PyEnum):
    """Status of auto-threshold evaluation."""

    MET_CRITERIA = "MET_CRITERIA"  # Ready for threshold increase
    NOT_MET = "NOT_MET"  # Criteria not met
    PENDING_PETITION = "PENDING_PETITION"  # Petition already exists
    DISABLED = "DISABLED"  # Feature disabled
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # Not enough data


class AutoThresholdManager:
    """
    Auto-Threshold Increase Manager

    Evaluates agent performance periodically and creates petitions
    for threshold increases when the agent consistently performs well.
    """

    def __init__(self):
        """Initialize Auto-Threshold Manager."""
        self.enabled = ConfigManager.get("AUTO_THRESHOLD_INCREASE", True)
        self.win_rate_threshold = ConfigManager.get(
            "AUTO_THRESHOLD_WIN_RATE_THRESHOLD", 70
        )
        self.profit_margin_threshold = ConfigManager.get(
            "AUTO_THRESHOLD_PROFIT_MARGIN_THRESHOLD", 50
        )
        self.consecutive_periods = ConfigManager.get(
            "AUTO_THRESHOLD_CONSECUTIVE_PERIODS", 4
        )

        logger.info(
            f"Auto-Threshold Manager initialized - "
            f"Enabled: {self.enabled}, "
            f"Win Rate Threshold: {self.win_rate_threshold}%, "
            f"Profit Margin: ${self.profit_margin_threshold / 100:.2f}, "
            f"Consecutive Periods: {self.consecutive_periods}"
        )

    def evaluate_and_petition(self) -> Dict[str, Any]:
        """
        Evaluate performance and create petition if criteria met.

        Returns:
            Dictionary with evaluation results
        """
        if not self.enabled:
            logger.info("Auto-threshold increase is disabled")
            return {
                "status": AutoThresholdStatus.DISABLED.value,
                "message": "Auto-threshold increase is disabled in configuration",
            }

        db = SessionLocal()
        try:
            # Check for pending petitions
            pending_petition = (
                db.query(ThresholdPetition)
                .filter_by(status="PENDING")
                .order_by(ThresholdPetition.created_at.desc())
                .first()
            )

            if pending_petition:
                logger.info(
                    "Pending petition exists, skipping auto-threshold evaluation"
                )
                return {
                    "status": AutoThresholdStatus.PENDING_PETITION.value,
                    "pending_petition_id": pending_petition.id,
                    "message": "Pending petition exists, skipping evaluation",
                }

            # Get recent performance data
            evaluation = self._evaluate_performance(db)

            if evaluation["status"] != AutoThresholdStatus.MET_CRITERIA.value:
                return evaluation

            # Criteria met - create petition
            petition = self._create_petition(db, evaluation)

            # Log the auto-increase attempt
            self._log_auto_increase(db, evaluation, petition)

            return {
                "status": AutoThresholdStatus.MET_CRITERIA.value,
                "petition": petition.to_dict(),
                "evaluation": evaluation,
                "message": "Auto-threshold criteria met, petition created",
            }

        except Exception as e:
            logger.error(f"Failed to evaluate auto-threshold: {e}")
            return {
                "status": "ERROR",
                "error": str(e),
                "message": "Failed to evaluate auto-threshold",
            }
        finally:
            db.close()

    def _evaluate_performance(self, db: Session) -> Dict[str, Any]:
        """
        Evaluate agent performance against auto-threshold criteria.

        Args:
            db: Database session

        Returns:
            Dictionary with evaluation results
        """
        # Get confidence entries from the last N periods
        # For simplicity, we'll look at the last 50 entries
        entries = (
            db.query(ConfidenceEntry)
            .order_by(ConfidenceEntry.created_at.desc())
            .limit(50)
            .all()
        )

        if len(entries) < 20:
            return {
                "status": AutoThresholdStatus.INSUFFICIENT_DATA.value,
                "message": f"Insufficient data: {len(entries)} entries (minimum 20)",
                "entries_count": len(entries),
            }

        # Calculate metrics
        total = len(entries)
        wins = sum(1 for e in entries if e.won)

        if wins == 0:
            return {
                "status": AutoThresholdStatus.NOT_MET.value,
                "message": "No wins in recent history",
                "total_bids": total,
                "wins": 0,
                "win_rate": 0,
            }

        win_rate = (wins / total) * 100

        # Calculate average profit
        profitable_entries = [e for e in entries if e.won and e.profit_cents]
        if not profitable_entries:
            return {
                "status": AutoThresholdStatus.NOT_MET.value,
                "message": "No profitable bids in recent history",
                "total_bids": total,
                "wins": wins,
                "win_rate": win_rate,
            }

        avg_profit = sum(e.profit_cents for e in profitable_entries) / len(
            profitable_entries
        )

        # Check consecutive periods (simplified as recent wins)
        recent_entries = entries[:20]  # Last 20 entries
        recent_wins = sum(1 for e in recent_entries if e.won)
        recent_win_rate = (
            (recent_wins / len(recent_entries)) * 100 if recent_entries else 0
        )

        # Evaluate criteria
        criteria_met = (
            win_rate >= self.win_rate_threshold
            and avg_profit >= self.profit_margin_threshold
            and recent_win_rate >= self.win_rate_threshold * 0.8  # 80% of threshold
        )

        return {
            "total_bids": total,
            "wins": wins,
            "win_rate": win_rate,
            "avg_profit_cents": avg_profit,
            "recent_wins": recent_wins,
            "recent_win_rate": recent_win_rate,
            "criteria": {
                "win_rate_met": win_rate >= self.win_rate_threshold,
                "profit_margin_met": avg_profit >= self.profit_margin_threshold,
                "recent_performance_met": recent_win_rate
                >= self.win_rate_threshold * 0.8,
            },
            "thresholds": {
                "win_rate_threshold": self.win_rate_threshold,
                "profit_margin_threshold": self.profit_margin_threshold,
            },
            "status": (
                AutoThresholdStatus.MET_CRITERIA.value
                if criteria_met
                else AutoThresholdStatus.NOT_MET.value
            ),
            "message": (
                "All criteria met for auto-threshold increase"
                if criteria_met
                else f"Criteria not met: Win rate {win_rate:.1f}% (need {self.win_rate_threshold}%), "
                f"Avg profit ${avg_profit / 100:.2f} (need ${self.profit_margin_threshold / 100:.2f})"
            ),
        }

    def _create_petition(
        self, db: Session, evaluation: Dict[str, Any]
    ) -> ThresholdPetition:
        """
        Create a threshold petition based on evaluation.

        Args:
            db: Database session
            evaluation: Performance evaluation results

        Returns:
            Created ThresholdPetition
        """
        import uuid

        # Calculate new threshold (increase by 20%)
        current_threshold_cents = int(evaluation.get("avg_profit_cents", 50) * 100)
        requested_threshold_cents = int(current_threshold_cents * 1.2)

        petition = ThresholdPetition(
            id=str(uuid.uuid4()),
            current_threshold_cents=current_threshold_cents,
            requested_threshold_cents=requested_threshold_cents,
            confidence_score=int(evaluation.get("win_rate", 50)),
            win_rate=evaluation.get("win_rate", 0) / 100,
            avg_profit_cents=int(evaluation.get("avg_profit_cents", 0)),
            current_streak=evaluation.get("recent_wins", 0),
            supporting_data=evaluation,
            status="PENDING",
            created_at=datetime.utcnow(),
        )

        db.add(petition)
        db.commit()
        db.refresh(petition)

        # Send Telegram notification
        try:
            from ..utils.notifications import TelegramNotifier

            notifier = TelegramNotifier()

            message = (
                f"🤖 AUTO-THRESHOLD INCREASE\n\n"
                f"Agent has met performance criteria!\n\n"
                f"Current: ${petition.current_threshold_cents / 100:.2f}\n"
                f"Requested: ${petition.requested_threshold_cents / 100:.2f}\n"
                f"Win Rate: {petition.win_rate * 100:.1f}% (threshold: {self.win_rate_threshold}%)\n"
                f"Avg Profit: ${petition.avg_profit_cents / 100:.2f} (threshold: ${self.profit_margin_threshold / 100:.2f})\n"
                f"Recent Wins: {petition.current_streak}\n\n"
                f"This is an automatic increase based on consistent performance.\n"
                f"Reply APPROVE or REJECT to roll back."
            )

            msg_id = notifier.send_alert(message)

            if msg_id:
                petition.telegram_message_id = str(msg_id)
                petition.telegram_sent_at = datetime.utcnow()
                db.commit()

            logger.info(f"Auto-threshold petition created: {petition.id}")

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

        return petition

    def _log_auto_increase(
        self, db: Session, evaluation: Dict[str, Any], petition: ThresholdPetition
    ):
        """
        Log auto-threshold increase attempt for audit trail.

        Args:
            db: Database session
            evaluation: Performance evaluation results
            petition: Created petition
        """
        logger.info(
            f"Auto-threshold increase attempt:\n"
            f"  Petition ID: {petition.id}\n"
            f"  Win Rate: {evaluation.get('win_rate', 0):.1f}%\n"
            f"  Avg Profit: ${evaluation.get('avg_profit_cents', 0) / 100:.2f}\n"
            f"  Threshold Increase: {petition.current_threshold_cents} -> {petition.requested_threshold_cents} cents\n"
            f"  Criteria Met: {evaluation.get('status') == AutoThresholdStatus.MET_CRITERIA.value}"
        )

    def rollback_auto_increase(self, petition_id: str, reasoning: str) -> bool:
        """
        Roll back an auto-increased threshold.

        Allows human to undo an auto-increase if it was incorrect.

        Args:
            petition_id: ID of the petition to rollback
            reasoning: Reason for rollback

        Returns:
            True if rollback successful
        """
        db = SessionLocal()
        try:
            # Find petition
            petition = db.query(ThresholdPetition).filter_by(id=petition_id).first()

            if not petition:
                logger.error(f"Petition not found: {petition_id}")
                return False

            # Update petition to rejected
            petition.status = "REJECTED"
            petition.human_decision = "REJECTED"
            petition.decided_at = datetime.utcnow()
            petition.decision_reasoning = reasoning

            db.commit()

            # Log rollback
            logger.info(
                f"Auto-threshold increase rolled back:\n"
                f"  Petition ID: {petition_id}\n"
                f"  Reasoning: {reasoning}"
            )

            # Send notification
            try:
                from ..utils.notifications import TelegramNotifier

                notifier = TelegramNotifier()
                notifier.send_alert(
                    f"🔄 AUTO-THRESHOLD ROLLED BACK\n\n"
                    f"Petition {petition_id}\n"
                    f"Threshold remains at ${petition.current_threshold_cents / 100:.2f}\n"
                    f"Reason: {reasoning}"
                )

            except Exception as e:
                logger.error(f"Failed to send rollback notification: {e}")

            return True

        except Exception as e:
            logger.error(f"Failed to rollback auto-increase: {e}")
            db.rollback()
            return False
        finally:
            db.close()


# Global singleton instance
_auto_threshold_manager: Optional[AutoThresholdManager] = None


def get_auto_threshold_manager() -> AutoThresholdManager:
    """Get or create global Auto-Threshold Manager singleton."""
    global _auto_threshold_manager

    if _auto_threshold_manager is None:
        _auto_threshold_manager = AutoThresholdManager()

    return _auto_threshold_manager


def reset_auto_threshold_manager():
    """Reset auto-threshold manager singleton (useful for testing)."""
    global _auto_threshold_manager
    _auto_threshold_manager = None
