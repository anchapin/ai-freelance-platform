"""
Cost Tracking Module for ROI Analysis

Tracks actual costs per bid/task and calculates ROI to identify
profitable strategies and marketplaces.

Issue #94: Cost Tracking Enhancement

Features:
- Track costs per task execution and bid
- Calculate ROI per marketplace
- Identify profitable vs losing strategies
- Store cost history in database
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Index,
)
from sqlalchemy.orm import declarative_base

from .database import SessionLocal
from ..api.models import Base
from ..config.config_manager import ConfigManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class CostType(PyEnum):
    """Types of costs that can be tracked."""

    LLM = "llm"
    SANDBOX = "sandbox"
    BID = "bid"
    MARKETPLACE = "marketplace"
    OTHER = "other"


class CostEntry(Base):
    """
    Cost Entry Database Model

    Stores individual cost entries for tracking financial operations
    and calculating ROI.
    """

    __tablename__ = "cost_entries"

    __table_args__ = (
        Index("idx_cost_task_id", "task_id"),
        Index("idx_cost_bid_id", "bid_id"),
        Index("idx_cost_type", "cost_type"),
        Index("idx_cost_marketplace", "marketplace"),
        Index("idx_cost_created_at", "created_at"),
    )

    id = Column(String, primary_key=True)

    # Reference to task or bid
    task_id = Column(String, nullable=True, index=True)
    bid_id = Column(String, nullable=True, index=True)

    # Cost details
    cost_type = Column(String, nullable=False, index=True)
    cost_cents = Column(Integer, nullable=False)
    cost_dollars = Column(Float, nullable=False)

    # Context
    description = Column(String, nullable=True)
    marketplace = Column(String, nullable=True, index=True)
    strategy_type = Column(String, nullable=True)

    # Revenue tracking for ROI calculation
    revenue_cents = Column(Integer, nullable=True)
    revenue_dollars = Column(Float, nullable=True)

    # Calculated ROI
    roi_cents = Column(Integer, nullable=True)
    roi_dollars = Column(Float, nullable=True)
    roi_percentage = Column(Float, nullable=True)

    # Metadata
    metadata = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert cost entry to dictionary."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "bid_id": self.bid_id,
            "cost_type": self.cost_type,
            "cost_cents": self.cost_cents,
            "cost_dollars": self.cost_dollars,
            "description": self.description,
            "marketplace": self.marketplace,
            "strategy_type": self.strategy_type,
            "revenue_cents": self.revenue_cents,
            "revenue_dollars": self.revenue_dollars,
            "roi_cents": self.roi_cents,
            "roi_dollars": self.roi_dollars,
            "roi_percentage": self.roi_percentage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CostTracker:
    """
    Cost Tracker for ROI Analysis

    Tracks costs and revenue to calculate ROI for bids, tasks, and strategies.
    Provides insights into profitable operations and areas for optimization.
    """

    def __init__(self):
        """Initialize Cost Tracker."""
        pass

    def track_cost(
        self,
        cost_type: str,
        cost_cents: int,
        description: Optional[str] = None,
        task_id: Optional[str] = None,
        bid_id: Optional[str] = None,
        marketplace: Optional[str] = None,
        strategy_type: Optional[str] = None,
        metadata: Optional[str] = None,
    ) -> CostEntry:
        """
        Track a cost entry.

        Args:
            cost_type: Type of cost (llm, sandbox, bid, marketplace, other)
            cost_cents: Cost amount in cents
            description: Description of the cost
            task_id: Optional task ID reference
            bid_id: Optional bid ID reference
            marketplace: Optional marketplace identifier
            strategy_type: Optional bidding strategy type
            metadata: Optional additional metadata (JSON string)

        Returns:
            CostEntry: The created cost entry
        """
        db = SessionLocal()
        try:
            import uuid

            cost_entry = CostEntry(
                id=str(uuid.uuid4()),
                task_id=task_id,
                bid_id=bid_id,
                cost_type=cost_type,
                cost_cents=cost_cents,
                cost_dollars=cost_cents / 100,
                description=description,
                marketplace=marketplace,
                strategy_type=strategy_type,
                metadata=metadata,
                created_at=datetime.utcnow(),
            )

            db.add(cost_entry)
            db.commit()
            db.refresh(cost_entry)

            logger.info(
                f"Tracked cost: ${cost_cents / 100:.2f} ({cost_type}) - "
                f"Task: {task_id}, Bid: {bid_id}, Marketplace: {marketplace}"
            )

            return cost_entry

        except Exception as e:
            logger.error(f"Failed to track cost: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def add_revenue(
        self,
        revenue_cents: int,
        task_id: Optional[str] = None,
        bid_id: Optional[str] = None,
    ) -> bool:
        """
        Add revenue to a cost entry and calculate ROI.

        Args:
            revenue_cents: Revenue amount in cents
            task_id: Task ID to associate revenue with
            bid_id: Bid ID to associate revenue with

        Returns:
            True if revenue added successfully
        """
        db = SessionLocal()
        try:
            # Find all cost entries for the task or bid
            query = db.query(CostEntry)

            if task_id:
                query = query.filter(CostEntry.task_id == task_id)
            elif bid_id:
                query = query.filter(CostEntry.bid_id == bid_id)
            else:
                logger.error("Must provide either task_id or bid_id")
                return False

            cost_entries = query.all()

            if not cost_entries:
                logger.warning(
                    f"No cost entries found for task_id={task_id}, bid_id={bid_id}"
                )
                return False

            # Add revenue to all related cost entries
            for entry in cost_entries:
                entry.revenue_cents = revenue_cents
                entry.revenue_dollars = revenue_cents / 100
                entry.roi_cents = revenue_cents - entry.cost_cents
                entry.roi_dollars = entry.roi_cents / 100
                entry.roi_percentage = (
                    (entry.roi_cents / entry.cost_cents * 100)
                    if entry.cost_cents > 0
                    else 0
                )

            db.commit()

            logger.info(
                f"Added revenue ${revenue_cents / 100:.2f} to {len(cost_entries)} cost entries"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to add revenue: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def calculate_roi_by_marketplace(
        self,
        marketplace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate ROI by marketplace.

        Args:
            marketplace: Optional specific marketplace to filter

        Returns:
            Dictionary with ROI statistics per marketplace
        """
        db = SessionLocal()
        try:
            query = db.query(CostEntry)

            if marketplace:
                query = query.filter(CostEntry.marketplace == marketplace)

            cost_entries = query.all()

            # Group by marketplace
            marketplace_stats = {}

            for entry in cost_entries:
                mp = entry.marketplace or "unknown"

                if mp not in marketplace_stats:
                    marketplace_stats[mp] = {
                        "total_cost_cents": 0,
                        "total_revenue_cents": 0,
                        "total_roi_cents": 0,
                        "total_entries": 0,
                        "profitable_entries": 0,
                    }

                stats = marketplace_stats[mp]
                stats["total_cost_cents"] += entry.cost_cents
                stats["total_entries"] += 1

                if entry.revenue_cents:
                    stats["total_revenue_cents"] += entry.revenue_cents

                    if entry.roi_cents and entry.roi_cents > 0:
                        stats["profitable_entries"] += 1

            # Calculate final stats
            results = {}
            for mp, stats in marketplace_stats.items():
                stats["total_roi_cents"] = (
                    stats["total_revenue_cents"] - stats["total_cost_cents"]
                )
                stats["total_cost_dollars"] = stats["total_cost_cents"] / 100
                stats["total_revenue_dollars"] = stats["total_revenue_cents"] / 100
                stats["total_roi_dollars"] = stats["total_roi_cents"] / 100
                stats["roi_percentage"] = (
                    (stats["total_roi_cents"] / stats["total_cost_cents"] * 100)
                    if stats["total_cost_cents"] > 0
                    else 0
                )
                stats["profit_rate"] = (
                    (stats["profitable_entries"] / stats["total_entries"] * 100)
                    if stats["total_entries"] > 0
                    else 0
                )

                results[mp] = stats

            return results

        except Exception as e:
            logger.error(f"Failed to calculate ROI by marketplace: {e}")
            raise
        finally:
            db.close()

    def calculate_roi_by_strategy(
        self,
        strategy_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate ROI by bidding strategy.

        Args:
            strategy_type: Optional specific strategy to filter

        Returns:
            Dictionary with ROI statistics per strategy
        """
        db = SessionLocal()
        try:
            query = db.query(CostEntry)

            if strategy_type:
                query = query.filter(CostEntry.strategy_type == strategy_type)

            cost_entries = query.all()

            # Group by strategy
            strategy_stats = {}

            for entry in cost_entries:
                strategy = entry.strategy_type or "unknown"

                if strategy not in strategy_stats:
                    strategy_stats[strategy] = {
                        "total_cost_cents": 0,
                        "total_revenue_cents": 0,
                        "total_roi_cents": 0,
                        "total_entries": 0,
                        "profitable_entries": 0,
                    }

                stats = strategy_stats[strategy]
                stats["total_cost_cents"] += entry.cost_cents
                stats["total_entries"] += 1

                if entry.revenue_cents:
                    stats["total_revenue_cents"] += entry.revenue_cents

                    if entry.roi_cents and entry.roi_cents > 0:
                        stats["profitable_entries"] += 1

            # Calculate final stats
            results = {}
            for strategy, stats in strategy_stats.items():
                stats["total_roi_cents"] = (
                    stats["total_revenue_cents"] - stats["total_cost_cents"]
                )
                stats["total_cost_dollars"] = stats["total_cost_cents"] / 100
                stats["total_revenue_dollars"] = stats["total_revenue_cents"] / 100
                stats["total_roi_dollars"] = stats["total_roi_cents"] / 100
                stats["roi_percentage"] = (
                    (stats["total_roi_cents"] / stats["total_cost_cents"] * 100)
                    if stats["total_cost_cents"] > 0
                    else 0
                )
                stats["profit_rate"] = (
                    (stats["profitable_entries"] / stats["total_entries"] * 100)
                    if stats["total_entries"] > 0
                    else 0
                )

                results[strategy] = stats

            return results

        except Exception as e:
            logger.error(f"Failed to calculate ROI by strategy: {e}")
            raise
        finally:
            db.close()

    def get_profitable_strategies(
        self,
        min_entries: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get list of profitable strategies sorted by ROI.

        Args:
            min_entries: Minimum number of entries to consider a strategy valid

        Returns:
            List of strategies with ROI information
        """
        strategy_roi = self.calculate_roi_by_strategy()

        # Filter and sort by ROI
        profitable = []
        for strategy, stats in strategy_roi.items():
            if stats["total_entries"] >= min_entries:
                profitable.append(
                    {
                        "strategy_type": strategy,
                        "roi_percentage": stats["roi_percentage"],
                        "total_roi_dollars": stats["total_roi_dollars"],
                        "profit_rate": stats["profit_rate"],
                        "total_entries": stats["total_entries"],
                    }
                )

        # Sort by ROI percentage descending
        profitable.sort(key=lambda x: x["roi_percentage"], reverse=True)

        return profitable

    def get_cost_history(
        self,
        limit: int = 100,
        task_id: Optional[str] = None,
        bid_id: Optional[str] = None,
    ) -> List[CostEntry]:
        """
        Get cost history.

        Args:
            limit: Maximum number of entries to return
            task_id: Optional filter by task ID
            bid_id: Optional filter by bid ID

        Returns:
            List of cost entries
        """
        db = SessionLocal()
        try:
            query = db.query(CostEntry)

            if task_id:
                query = query.filter(CostEntry.task_id == task_id)
            if bid_id:
                query = query.filter(CostEntry.bid_id == bid_id)

            query = query.order_by(CostEntry.created_at.desc()).limit(limit)

            return query.all()

        finally:
            db.close()


# Global singleton instance
_cost_tracker_instance: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get or create global Cost Tracker singleton."""
    global _cost_tracker_instance

    if _cost_tracker_instance is None:
        _cost_tracker_instance = CostTracker()

    return _cost_tracker_instance


def reset_cost_tracker():
    """Reset cost tracker singleton (useful for testing)."""
    global _cost_tracker_instance
    _cost_tracker_instance = None
