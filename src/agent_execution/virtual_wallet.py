"""
Virtual Wallet Module for Financial Control

Tracks seed money, operational budget, and revenue from completed tasks.
Enforces budget caps and provides financial visibility for human oversight.

Issue #92: Virtual Wallet Module
Issue #93: Budget Management System

Features:
- Track balance, spending, and earnings
- Enforce budget caps with alerts
- Automatic budget reset on configured period
- Integration with Telegram notifications for low budget alerts
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum as PyEnum
import json

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    JSON,
)

from ..api.database import SessionLocal
from ..api.models import Base
from ..config.config_manager import ConfigManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class BudgetResetPeriod(PyEnum):
    """Budget reset period options."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class VirtualWallet(Base):
    """
    Virtual Wallet Database Model

    Stores wallet state including balance, spending, and budget configuration.
    Persists wallet state across restarts.
    """

    __tablename__ = "virtual_wallets"

    id = Column(String, primary_key=True)

    # Financial state
    balance_cents = Column(Integer, default=0, nullable=False)
    total_spent_cents = Column(Integer, default=0, nullable=False)
    total_earned_cents = Column(Integer, default=0, nullable=False)

    # Budget configuration
    budget_cap_cents = Column(Integer, default=50000, nullable=False)
    budget_reset_period = Column(String, default="weekly", nullable=False)

    # Budget tracking
    budget_start_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    budget_spent_cents = Column(Integer, default=0, nullable=False)

    # Threshold alerts
    low_budget_threshold_percent = Column(Integer, default=25, nullable=False)
    critical_budget_threshold_percent = Column(Integer, default=10, nullable=False)

    # Alert tracking
    low_budget_alert_sent = Column(Boolean, default=False, nullable=False)
    critical_budget_alert_sent = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert wallet to dictionary."""
        return {
            "id": self.id,
            "balance_dollars": self.balance_cents / 100,
            "balance_cents": self.balance_cents,
            "total_spent_dollars": self.total_spent_cents / 100,
            "total_spent_cents": self.total_spent_cents,
            "total_earned_dollars": self.total_earned_cents / 100,
            "total_earned_cents": self.total_earned_cents,
            "budget_cap_dollars": self.budget_cap_cents / 100,
            "budget_cap_cents": self.budget_cap_cents,
            "budget_reset_period": self.budget_reset_period,
            "budget_spent_dollars": self.budget_spent_cents / 100,
            "budget_spent_cents": self.budget_spent_cents,
            "budget_remaining_dollars": (
                self.budget_cap_cents - self.budget_spent_cents
            )
            / 100,
            "budget_remaining_cents": self.budget_cap_cents - self.budget_spent_cents,
            "budget_percentage_used": (
                self.budget_spent_cents / self.budget_cap_cents * 100
            )
            if self.budget_cap_cents > 0
            else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class VirtualWalletManager:
    """
    Virtual Wallet Manager

    Manages wallet operations including balance tracking, budget enforcement,
    and automatic budget resets. Provides API for financial control.
    """

    def __init__(self):
        """Initialize wallet manager."""
        self.wallet_id = "default"
        self._wallet: Optional[VirtualWallet] = None
        self._load_wallet()

    def _load_wallet(self):
        """Load wallet from database or create default."""
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                wallet = self._create_default_wallet(db)

            self._wallet = wallet
            logger.info(
                f"Wallet loaded - Balance: ${self._wallet.balance_cents / 100:.2f}, "
                f"Budget Remaining: ${(self._wallet.budget_cap_cents - self._wallet.budget_spent_cents) / 100:.2f}"
            )
        finally:
            db.close()

    def _create_default_wallet(self, db) -> VirtualWallet:
        """Create default wallet with configured values."""
        initial_seed_cents = ConfigManager.get("INITIAL_SEED_MONEY", 10000)
        budget_cap_cents = ConfigManager.get("BUDGET_CAP_WEEKLY", 50000)
        reset_period = ConfigManager.get("BUDGET_RESET_PERIOD", "weekly")

        wallet = VirtualWallet(
            id=self.wallet_id,
            balance_cents=initial_seed_cents,
            budget_cap_cents=budget_cap_cents,
            budget_reset_period=reset_period,
            budget_start_at=datetime.utcnow(),
        )

        db.add(wallet)
        db.commit()
        db.refresh(wallet)

        logger.info(
            f"Created default wallet - Initial seed: ${initial_seed_cents / 100:.2f}, "
            f"Budget cap: ${budget_cap_cents / 100:.2f}/{reset_period}"
        )

        return wallet

    def deduct(
        self,
        cost_type: str,
        amount_cents: int,
        task_id: Optional[str] = None,
    ) -> bool:
        """
        Deduct cost from wallet and budget.

        Args:
            cost_type: Type of cost (e.g., "llm", "sandbox", "bid")
            amount_cents: Amount in cents
            task_id: Optional task ID for tracking

        Returns:
            True if deduction successful, False if over budget
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                logger.error(f"Wallet not found: {self.wallet_id}")
                return False

            # Check budget
            self._reset_budget_if_needed(db, wallet)

            available_budget = wallet.budget_cap_cents - wallet.budget_spent_cents
            available_balance = wallet.balance_cents

            if available_budget < amount_cents or available_balance < amount_cents:
                logger.warning(
                    f"Budget/Insufficient balance for {cost_type}: "
                    f"Needed ${amount_cents / 100:.2f}, "
                    f"Available budget: ${available_budget / 100:.2f}, "
                    f"Available balance: ${available_balance / 100:.2f}"
                )
                return False

            # Deduct from balance and budget
            wallet.balance_cents -= amount_cents
            wallet.total_spent_cents += amount_cents
            wallet.budget_spent_cents += amount_cents
            wallet.updated_at = datetime.utcnow()

            db.commit()
            self._wallet = wallet

            logger.info(
                f"Deducted ${amount_cents / 100:.2f} for {cost_type} - "
                f"Balance: ${wallet.balance_cents / 100:.2f}, "
                f"Budget spent: ${wallet.budget_spent_cents / 100:.2f}/${wallet.budget_cap_cents / 100:.2f}"
            )

            # Check if we need to send alerts
            self._check_budget_alerts(db, wallet)

            return True

        except Exception as e:
            logger.error(f"Failed to deduct from wallet: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def add_revenue(self, amount_cents: int, task_id: Optional[str] = None) -> bool:
        """
        Add revenue from completed task to wallet.

        Args:
            amount_cents: Revenue amount in cents
            task_id: Optional task ID for tracking

        Returns:
            True if revenue added successfully
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                logger.error(f"Wallet not found: {self.wallet_id}")
                return False

            # Add to balance and total earned
            wallet.balance_cents += amount_cents
            wallet.total_earned_cents += amount_cents
            wallet.updated_at = datetime.utcnow()

            db.commit()
            self._wallet = wallet

            logger.info(
                f"Added revenue ${amount_cents / 100:.2f} - "
                f"Balance: ${wallet.balance_cents / 100:.2f}, "
                f"Total earned: ${wallet.total_earned_cents / 100:.2f}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to add revenue to wallet: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_available_budget(self) -> Dict[str, Any]:
        """
        Get available budget information.

        Returns:
            Dictionary with budget details
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                return {"error": "Wallet not found"}

            self._reset_budget_if_needed(db, wallet)

            return {
                "budget_cap_cents": wallet.budget_cap_cents,
                "budget_cap_dollars": wallet.budget_cap_cents / 100,
                "budget_spent_cents": wallet.budget_spent_cents,
                "budget_spent_dollars": wallet.budget_spent_cents / 100,
                "budget_remaining_cents": wallet.budget_cap_cents
                - wallet.budget_spent_cents,
                "budget_remaining_dollars": (
                    wallet.budget_cap_cents - wallet.budget_spent_cents
                )
                / 100,
                "budget_percentage_used": (
                    wallet.budget_spent_cents / wallet.budget_cap_cents * 100
                    if wallet.budget_cap_cents > 0
                    else 0
                ),
                "budget_reset_period": wallet.budget_reset_period,
                "budget_start_at": wallet.budget_start_at.isoformat()
                if wallet.budget_start_at
                else None,
            }

        finally:
            db.close()

    def get_wallet_status(self) -> Dict[str, Any]:
        """
        Get complete wallet status.

        Returns:
            Dictionary with full wallet details
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                return {"error": "Wallet not found"}

            self._reset_budget_if_needed(db, wallet)

            return wallet.to_dict()

        finally:
            db.close()

    def add_seed_money(self, amount_cents: int) -> bool:
        """
        Add seed money to wallet.

        Args:
            amount_cents: Amount to add in cents

        Returns:
            True if seed money added successfully
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                logger.error(f"Wallet not found: {self.wallet_id}")
                return False

            wallet.balance_cents += amount_cents
            wallet.updated_at = datetime.utcnow()

            db.commit()
            self._wallet = wallet

            logger.info(
                f"Added seed money ${amount_cents / 100:.2f} - New balance: ${wallet.balance_cents / 100:.2f}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to add seed money: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def set_budget_cap(
        self,
        budget_cap_cents: int,
        reset_period: Optional[str] = None,
    ) -> bool:
        """
        Set budget cap and reset period.

        Args:
            budget_cap_cents: New budget cap in cents
            reset_period: New reset period (daily, weekly, monthly)

        Returns:
            True if budget updated successfully
        """
        db = SessionLocal()
        try:
            wallet = db.query(VirtualWallet).filter_by(id=self.wallet_id).first()

            if not wallet:
                logger.error(f"Wallet not found: {self.wallet_id}")
                return False

            wallet.budget_cap_cents = budget_cap_cents
            if reset_period:
                wallet.budget_reset_period = reset_period

            # Reset budget tracking when cap changes
            wallet.budget_spent_cents = 0
            wallet.budget_start_at = datetime.utcnow()
            wallet.low_budget_alert_sent = False
            wallet.critical_budget_alert_sent = False
            wallet.updated_at = datetime.utcnow()

            db.commit()
            self._wallet = wallet

            logger.info(
                f"Budget updated - Cap: ${budget_cap_cents / 100:.2f}, "
                f"Period: {reset_period or wallet.budget_reset_period}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to set budget cap: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def _reset_budget_if_needed(self, db, wallet: VirtualWallet):
        """Reset budget tracking if reset period has elapsed."""
        now = datetime.utcnow()

        # Calculate when budget should reset
        reset_delta = None
        if wallet.budget_reset_period == "daily":
            reset_delta = timedelta(days=1)
        elif wallet.budget_reset_period == "weekly":
            reset_delta = timedelta(weeks=1)
        elif wallet.budget_reset_period == "monthly":
            reset_delta = timedelta(days=30)

        if reset_delta and (now - wallet.budget_start_at) >= reset_delta:
            wallet.budget_spent_cents = 0
            wallet.budget_start_at = now
            wallet.low_budget_alert_sent = False
            wallet.critical_budget_alert_sent = False
            wallet.updated_at = now

            db.commit()
            logger.info(
                f"Budget reset - Period: {wallet.budget_reset_period}, "
                f"New cap: ${wallet.budget_cap_cents / 100:.2f}"
            )

    def _check_budget_alerts(self, db, wallet: VirtualWallet):
        """Check if budget alerts need to be sent."""
        budget_used_pct = (
            wallet.budget_spent_cents / wallet.budget_cap_cents * 100
            if wallet.budget_cap_cents > 0
            else 0
        )

        # Low budget alert (25% threshold)
        if (
            budget_used_pct >= wallet.low_budget_threshold_percent
            and not wallet.low_budget_alert_sent
        ):
            wallet.low_budget_alert_sent = True
            wallet.updated_at = datetime.utcnow()
            db.commit()

            # Send Telegram notification
            try:
                from ..utils.notifications import TelegramNotifier

                notifier = TelegramNotifier()
                notifier.send_alert(
                    f"⚠️ LOW BUDGET ALERT\n\n"
                    f"Budget: ${wallet.budget_spent_cents / 100:.2f} / ${wallet.budget_cap_cents / 100:.2f}\n"
                    f"Used: {budget_used_pct:.1f}%\n"
                    f"Period: {wallet.budget_reset_period}\n\n"
                    f"Agent will stop bidding when budget is exhausted."
                )
                logger.info(f"Low budget alert sent at {budget_used_pct:.1f}%")
            except Exception as e:
                logger.warning(f"Failed to send low budget alert: {e}")

        # Critical budget alert (10% threshold)
        if (
            budget_used_pct >= wallet.critical_budget_threshold_percent
            and not wallet.critical_budget_alert_sent
        ):
            wallet.critical_budget_alert_sent = True
            wallet.updated_at = datetime.utcnow()
            db.commit()

            # Send Telegram notification
            try:
                from ..utils.notifications import TelegramNotifier

                notifier = TelegramNotifier()
                notifier.send_alert(
                    f"🚨 CRITICAL BUDGET ALERT\n\n"
                    f"Budget: ${wallet.budget_spent_cents / 100:.2f} / ${wallet.budget_cap_cents / 100:.2f}\n"
                    f"Used: {budget_used_pct:.1f}%\n"
                    f"Period: {wallet.budget_reset_period}\n\n"
                    f"Agent will STOP bidding soon. Add seed money immediately."
                )
                logger.info(f"Critical budget alert sent at {budget_used_pct:.1f}%")
            except Exception as e:
                logger.warning(f"Failed to send critical budget alert: {e}")


# Global singleton instance
_wallet_manager_instance: Optional[VirtualWalletManager] = None


def get_virtual_wallet() -> VirtualWalletManager:
    """Get or create global Virtual Wallet Manager singleton."""
    global _wallet_manager_instance

    if _wallet_manager_instance is None:
        _wallet_manager_instance = VirtualWalletManager()

    return _wallet_manager_instance


def reset_virtual_wallet():
    """Reset virtual wallet singleton (useful for testing)."""
    global _wallet_manager_instance
    _wallet_manager_instance = None
