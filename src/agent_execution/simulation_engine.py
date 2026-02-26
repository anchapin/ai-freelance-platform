"""

Simulation Engine Module for Training Mode

Provides functionality to track hypothetical bids and calculate simulation profits
when the system operates in training mode without making real financial commitments.

Issue #89, #91: Training Mode & Simulation Engine

Features:
- Record hypothetical bid outcomes to SimulationBid table
- Calculate total simulation profit/loss
- Compare different bidding strategies (aggressive vs conservative)
- Generate insights for bidding optimization

When TRAINING_MODE is enabled:
- Bids are evaluated and generated normally
- Bids are marked with status='SIMULATED' (not submitted to marketplace)
- Results are tracked in simulation_bids table
- Enables analysis of strategy effectiveness without financial risk
"""

import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

# Load environment variables
from dotenv import load_dotenv

# Import logger
from src.utils.logger import get_logger

# Import database and models
from src.api.database import SessionLocal
from src.api.models import SimulationBid

# Import ConfigManager
from src.config.config_manager import ConfigManager

# Load environment variables
load_dotenv()

# Initialize logger
logger = get_logger(__name__)


class SimulationEngine:
    """
    Simulation Engine for Tracking Hypothetical Bids

    Manages simulation bids made during training mode when no real financial
    commitment is made. Provides tools for analyzing bidding strategies
    and learning optimal approaches.

    Issue #89: Simulation Engine Module
    Issue #91: Strategy Comparison for Bidding
    """

    def __init__(self):
        """Initialize the Simulation Engine."""
        self.training_mode = ConfigManager.get("TRAINING_MODE", False)
        logger.info(
            f"Simulation Engine initialized - Training Mode: {self.training_mode}"
        )

    def record_simulation_bid(
        self,
        job_title: str,
        job_description: str,
        job_url: str,
        bid_amount_cents: int,
        strategy_type: str = "balanced",
        confidence: Optional[int] = None,
        would_have_won: Optional[bool] = None,
        outcome_reasoning: Optional[str] = None,
        job_marketplace: Optional[str] = None,
        skills_matched: Optional[List[str]] = None,
    ) -> SimulationBid:
        """
        Record a hypothetical bid to the simulation database.

        When in training mode, this method saves a bid without submitting it
        to the actual marketplace. This allows for analysis and strategy testing.

        Args:
            job_title: Job title from marketplace
            job_description: Job description text
            job_url: URL to the job posting
            bid_amount_cents: Bid amount in cents
            strategy_type: Type of bidding strategy (aggressive, conservative, balanced)
            confidence: Evaluation confidence (0-100)
            would_have_won: Simulated outcome (True if would have won)
            outcome_reasoning: Reasoning for why bid would have won/lost
            job_marketplace: Marketplace identifier (upwork, fiverr, etc.)
            skills_matched: List of matched skills

        Returns:
            SimulationBid: The created simulation bid record
        """
        db = SessionLocal()
        try:
            # Create simulation bid record
            simulation_bid = SimulationBid(
                id=str(uuid.uuid4()),
                job_title=job_title,
                job_description=job_description[:1000],  # Limit to prevent overflow
                job_url=job_url,
                bid_amount=bid_amount_cents,
                strategy_type=strategy_type,
                confidence=confidence,
                would_have_won=would_have_won,
                outcome_reasoning=outcome_reasoning,
                job_marketplace=job_marketplace,
                skills_matched=skills_matched,
                created_at=datetime.utcnow(),
            )

            db.add(simulation_bid)
            db.commit()
            db.refresh(simulation_bid)

            logger.info(
                f"Recorded simulation bid: {job_title} (${bid_amount_cents / 100:.2f}) "
                f"Strategy: {strategy_type}, Would have won: {would_have_won}"
            )

            return simulation_bid

        except Exception as e:
            logger.error(f"Failed to record simulation bid: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def calculate_total_profit(
        self,
        strategy_type: Optional[str] = None,
        date_filter: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate total simulated profit/loss from simulation bids.

        Calculates the total profit/loss based on simulated outcomes.
        If would_have_won=True, adds bid_amount to profit.
        If would_have_won=False, subtracts bid_amount from profit.

        Args:
            strategy_type: Filter by strategy type (aggressive, conservative, balanced)
            date_filter: Optional date range filter (e.g., {"start": "2026-02-01", "end": "2026-02-28"})

        Returns:
            Dictionary with total profit, total bids, and win rate
        """
        db = SessionLocal()
        try:
            # Build query
            query = db.query(SimulationBid)

            # Filter by strategy type if provided
            if strategy_type:
                query = query.filter(SimulationBid.strategy_type == strategy_type)

            # Filter by date range if provided
            if date_filter:
                if "start" in date_filter:
                    query = query.filter(
                        SimulationBid.created_at
                        >= datetime.fromisoformat(date_filter["start"])
                    )
                if "end" in date_filter:
                    query = query.filter(
                        SimulationBid.created_at
                        <= datetime.fromisoformat(date_filter["end"])
                    )

            # Get all simulation bids
            simulation_bids = query.all()

            # Calculate totals
            total_profit = 0
            total_bids = len(simulation_bids)
            wins = 0
            losses = 0

            for bid in simulation_bids:
                if bid.would_have_won:
                    total_profit += bid.bid_amount
                    wins += 1
                else:
                    total_profit -= bid.bid_amount
                    losses += 1

            # Calculate win rate
            win_rate = (wins / total_bids * 100) if total_bids > 0 else 0

            # Calculate average bid
            avg_bid = (
                sum(b.bid_amount for b in simulation_bids) / total_bids
                if total_bids > 0
                else 0
            )

            return {
                "total_profit_cents": total_profit,
                "total_profit_dollars": total_profit / 100,
                "total_bids": total_bids,
                "wins": wins,
                "losses": losses,
                "win_rate_percentage": win_rate,
                "average_bid_cents": avg_bid,
                "average_bid_dollars": avg_bid / 100,
                "strategy_type": strategy_type,
            }

        except Exception as e:
            logger.error(f"Failed to calculate total profit: {e}")
            raise
        finally:
            db.close()

    def compare_strategies(
        self,
        date_filter: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Compare performance of different bidding strategies.

        Compares aggressive, conservative, and balanced strategies to determine
        which performs better. Generates insights for bidding optimization.

        Args:
            date_filter: Optional date range filter

        Returns:
            Dictionary with strategy comparison results
        """
        strategies = ["aggressive", "conservative", "balanced"]

        # Calculate stats for each strategy
        results = {}
        for strategy in strategies:
            results[strategy] = self.calculate_total_profit(
                strategy_type=strategy, date_filter=date_filter
            )

        # Determine best strategy
        best_strategy = None
        best_win_rate = 0
        best_profit = 0

        for strategy, stats in results.items():
            if stats["win_rate_percentage"] > best_win_rate:
                best_win_rate = stats["win_rate_percentage"]
                best_profit = stats["total_profit_dollars"]
                best_strategy = strategy

        # Generate insights
        insights = self._generate_insights(results)

        return {
            "strategies": results,
            "best_strategy": best_strategy,
            "best_win_rate": best_win_rate,
            "best_profit_dollars": best_profit,
            "insights": insights,
        }

    def _generate_insights(self, results: Dict[str, Any]) -> List[str]:
        """
        Generate actionable insights from simulation results.

        Analyzes simulation data to provide recommendations for bidding optimization.

        Args:
            results: Strategy comparison results

        Returns:
            List of insight strings
        """
        insights = []

        # Check each strategy
        for strategy, stats in results.items():
            win_rate = stats["win_rate_percentage"]
            profit = stats["total_profit_dollars"]

            if win_rate > 60:
                insights.append(
                    f"{strategy.title()} strategy performing well: "
                    f"{win_rate:.1f}% win rate with ${profit:.2f} total profit"
                )
            elif win_rate < 30:
                insights.append(
                    f"{strategy.title()} strategy needs improvement: "
                    f"only {win_rate:.1f}% win rate"
                )

            # Profit analysis
            if profit > 0:
                insights.append(
                    f"{strategy.title()} strategy is profitable: "
                    f"${profit:.2f} total profit across {stats['total_bids']} bids"
                )
            else:
                insights.append(
                    f"{strategy.title()} strategy is not profitable: "
                    f"-${abs(profit):.2f} loss across {stats['total_bids']} bids"
                )

        # Compare aggressive vs conservative
        aggressive = results.get("aggressive", {})
        conservative = results.get("conservative", {})

        if aggressive["total_bids"] > 0 and conservative["total_bids"] > 0:
            if aggressive["win_rate_percentage"] > conservative["win_rate_percentage"]:
                insights.append(
                    "Aggressive bidding appears more effective than conservative bidding"
                )
            elif (
                conservative["win_rate_percentage"] > aggressive["win_rate_percentage"]
            ):
                insights.append(
                    "Conservative bidding appears more effective than aggressive bidding"
                )
            else:
                insights.append(
                    "Both strategies have similar effectiveness - consider other factors"
                )

        return insights

    def get_strategy_summary(
        self,
        strategy_type: str,
        date_filter: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Get a summary of performance for a specific strategy.

        Args:
            strategy_type: Strategy type to analyze (aggressive, conservative, balanced)
            date_filter: Optional date range filter

        Returns:
            Dictionary with detailed strategy summary
        """
        stats = self.calculate_total_profit(
            strategy_type=strategy_type, date_filter=date_filter
        )

        # Add strategy details
        summary = {
            "strategy_type": strategy_type,
            "win_rate_percentage": stats["win_rate_percentage"],
            "total_profit_dollars": stats["total_profit_dollars"],
            "total_profit_cents": stats["total_profit_cents"],
            "total_bids": stats["total_bids"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "average_bid_dollars": stats["average_bid_dollars"],
            "average_bid_cents": stats["average_bid_cents"],
        }

        return summary

    def get_recent_simulations(
        self, limit: int = 100, date_filter: Optional[Dict[str, str]] = None
    ) -> List[SimulationBid]:
        """
        Get recent simulation bids for review and analysis.

        Args:
            limit: Maximum number of simulations to return
            date_filter: Optional date range filter

        Returns:
            List of recent SimulationBid objects
        """
        db = SessionLocal()
        try:
            query = db.query(SimulationBid)

            # Filter by date range if provided
            if date_filter:
                if "start" in date_filter:
                    query = query.filter(
                        SimulationBid.created_at
                        >= datetime.fromisoformat(date_filter["start"])
                    )
                if "end" in date_filter:
                    query = query.filter(
                        SimulationBid.created_at
                        <= datetime.fromisoformat(date_filter["end"])
                    )

            # Order by created_at desc and limit
            query = query.order_by(SimulationBid.created_at.desc()).limit(limit)

            return query.all()

        except Exception as e:
            logger.error(f"Failed to get recent simulations: {e}")
            raise
        finally:
            db.close()


# Global singleton instance
_sim_engine_instance: Optional["SimulationEngine"] = None


def get_simulation_engine() -> SimulationEngine:
    """
    Get or create the global Simulation Engine singleton.

    Returns:
        SimulationEngine: Global instance of the simulation engine
    """
    global _sim_engine_instance

    if _sim_engine_instance is None:
        _sim_engine_instance = SimulationEngine()

    return _sim_engine_instance


def reset_simulation_engine():
    """Reset the simulation engine singleton (useful for testing)."""
    global _sim_engine_instance
    _sim_engine_instance = None


if __name__ == "__main__":
    """
    Test the Simulation Engine
    """

    async def test_simulation_engine():
        """Test all simulation engine functionality."""
        print("=" * 60)
        print("Simulation Engine - Test Run")
        print("=" * 60)

        # Initialize engine
        engine = SimulationEngine()
        print(f"\nTraining Mode: {engine.training_mode}")

        # Record some test simulation bids
        print("\nRecording test simulation bids...")

        engine.record_simulation_bid(
            job_title="Python Data Analysis Script",
            job_description="Need Python developer for data analysis",
            job_url="https://example.com/job1",
            bid_amount_cents=10000,  # $100
            strategy_type="aggressive",
            confidence=80,
            would_have_won=True,
            outcome_reasoning="Strong skills match, reasonable budget",
            job_marketplace="example",
            skills_matched=["Python", "pandas"],
        )

        engine.record_simulation_bid(
            job_title="React Dashboard Development",
            job_description="Build dashboard with charts",
            job_url="https://example.com/job2",
            bid_amount_cents=50000,  # $500
            strategy_type="conservative",
            confidence=70,
            would_have_won=False,
            outcome_reasoning="Overpriced for the scope",
            job_marketplace="example",
            skills_matched=["React", "D3.js"],
        )

        engine.record_simulation_bid(
            job_title="Excel Spreadsheet Automation",
            job_description="VBA macros for automation",
            job_url="https://example.com/job3",
            bid_amount_cents=15000,  # $150
            strategy_type="balanced",
            confidence=90,
            would_have_won=True,
            outcome_reasoning="Good fit, competitive bid",
            job_marketplace="example",
            skills_matched=["Excel", "VBA"],
        )

        # Calculate total profit
        print("\n" + "=" * 60)
        print("Total Profit Calculation")
        print("=" * 60)
        total_profit = engine.calculate_total_profit()
        print(f"Total Profit: ${total_profit['total_profit_dollars']:.2f}")
        print(f"Total Bids: {total_profit['total_bids']}")
        print(f"Win Rate: {total_profit['win_rate_percentage']:.1f}%")
        print(f"Average Bid: ${total_profit['average_bid_dollars']:.2f}")

        # Compare strategies
        print("\n" + "=" * 60)
        print("Strategy Comparison")
        print("=" * 60)
        comparison = engine.compare_strategies()
        print(f"Best Strategy: {comparison['best_strategy']}")
        print(f"Best Win Rate: {comparison['best_win_rate']:.1f}%")
        print(f"Best Profit: ${comparison['best_profit_dollars']:.2f}")

        print("\nInsights:")
        for insight in comparison["insights"]:
            print(f"  - {insight}")

        # Get strategy summary
        print("\n" + "=" * 60)
        print("Strategy Summary - Aggressive")
        print("=" * 60)
        aggressive_summary = engine.get_strategy_summary("aggressive")
        print(f"Strategy: {aggressive_summary['strategy_type']}")
        print(f"Win Rate: {aggressive_summary['win_rate_percentage']:.1f}%")
        print(f"Total Profit: ${aggressive_summary['total_profit_dollars']:.2f}")
        print(f"Total Bids: {aggressive_summary['total_bids']}")
        print(
            f"Wins: {aggressive_summary['wins']}, Losses: {aggressive_summary['losses']}"
        )

        print("\n" + "=" * 60)
        print("Simulation Engine Test Complete")
        print("=" * 60)

    # Run test
    asyncio.run(test_simulation_engine())
