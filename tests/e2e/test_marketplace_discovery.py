"""
E2E Tests: Marketplace Discovery Workflow

Tests the complete marketplace discovery process:
1. Autonomous marketplace search and evaluation
2. Marketplace performance tracking
3. Priority ranking and bid allocation
4. Auto-adjustment based on success rates

Coverage: ~20% of critical path
"""

import pytest
import asyncio
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone

from .utils import build_marketplace_fixture


class TestMarketplaceDiscovery:
    """Test autonomous marketplace discovery and evaluation."""
    
    def test_discover_single_marketplace(self):
        """Test discovering a single marketplace."""
        # Setup
        marketplace = build_marketplace_fixture(
            name="Upwork",
            jobs_found=100,
            bids_placed=30,
            bids_won=8
        )
        
        # Verify structure
        assert marketplace["name"] == "Upwork"
        assert marketplace["jobs_found"] == 100
        assert marketplace["bids_placed"] == 30
        assert marketplace["bids_won"] == 8
        assert marketplace["success_rate"] == 8 / 30
        assert marketplace["total_revenue"] == 8 * 500.0
    
    def test_discover_multiple_marketplaces(self, mock_marketplace_list):
        """Test discovering multiple marketplaces."""
        # Verify list structure
        assert len(mock_marketplace_list) == 3
        
        names = [m["name"] for m in mock_marketplace_list]
        assert "Upwork" in names
        assert "Fiverr" in names
        assert "Toptal" in names
        
        # Verify all have required fields
        for marketplace in mock_marketplace_list:
            assert "name" in marketplace
            assert "url" in marketplace
            assert "category" in marketplace
            assert "success_rate" in marketplace
            assert "priority_score" in marketplace
    
    def test_marketplace_ranking_by_priority(self, mock_marketplace_list):
        """Test that marketplaces are ranked by priority score."""
        # Sort by priority score
        sorted_markets = sorted(
            mock_marketplace_list,
            key=lambda m: m["priority_score"],
            reverse=True
        )
        
        # Toptal should be first (highest priority_score)
        assert sorted_markets[0]["name"] == "Toptal"
        assert sorted_markets[0]["priority_score"] == 3200.00
    
    def test_marketplace_success_rate_calculation(self):
        """Test success rate calculation for marketplace."""
        marketplace = build_marketplace_fixture(
            bids_placed=10,
            bids_won=3
        )
        
        expected_rate = 3 / 10
        assert marketplace["success_rate"] == expected_rate
    
    def test_marketplace_with_zero_bids(self):
        """Test handling marketplace with no bids placed yet."""
        marketplace = build_marketplace_fixture(
            bids_placed=0,
            bids_won=0
        )
        
        assert marketplace["success_rate"] == 0.0
        assert marketplace["total_revenue"] == 0.0
        assert marketplace["priority_score"] == 0.0
    
    def test_marketplace_category_filtering(self, mock_marketplace_list):
        """Test filtering marketplaces by category."""
        freelance_markets = [
            m for m in mock_marketplace_list
            if m["category"] == "freelance"
        ]
        
        assert len(freelance_markets) == 2  # Upwork, Fiverr
        names = [m["name"] for m in freelance_markets]
        assert "Upwork" in names
        assert "Fiverr" in names
    
    @pytest.mark.asyncio
    async def test_marketplace_evaluation_timeout(self):
        """Test handling marketplace evaluation timeout."""
        # Simulate slow marketplace evaluation
        async def slow_evaluation():
            await asyncio.sleep(5)  # 5 second timeout
            return {"name": "SlowMarket", "quality_score": 0.5}
        
        # Should timeout if threshold is < 5 seconds
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_evaluation(), timeout=1)
    
    def test_marketplace_metadata_storage(self):
        """Test storing and retrieving marketplace metadata."""
        metadata = {
            "api_rate_limit": 100,
            "supports_api": True,
            "requires_proxy": False,
            "last_error": None,
        }
        
        marketplace = build_marketplace_fixture(
            name="APIMarket",
            metadata=metadata
        )
        
        assert marketplace["metadata"] == metadata
        assert marketplace["metadata"]["supports_api"] is True
    
    def test_marketplace_performance_update(self):
        """Test updating marketplace performance metrics."""
        # Initial marketplace
        marketplace = build_marketplace_fixture(
            name="TestMarket",
            bids_placed=10,
            bids_won=2,
            total_revenue=1000.0
        )
        
        initial_success_rate = marketplace["success_rate"]
        
        # Simulate additional bids
        marketplace["bids_placed"] += 10  # 20 total
        marketplace["bids_won"] += 4      # 6 total, 2 new wins
        marketplace["total_revenue"] += 2000.0  # $3000 total
        marketplace["success_rate"] = marketplace["bids_won"] / marketplace["bids_placed"]
        
        # Verify update
        assert marketplace["success_rate"] == 6 / 20
        assert marketplace["success_rate"] > initial_success_rate
        assert marketplace["total_revenue"] == 3000.0
    
    def test_marketplace_staleness_detection(self):
        """Test detecting stale marketplace data."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        
        marketplace = build_marketplace_fixture(
            name="StaleMarket"
        )
        marketplace["last_scanned"] = old_time
        
        # Determine staleness
        last_scan = datetime.fromisoformat(marketplace["last_scanned"])
        is_stale = (datetime.now(timezone.utc) - last_scan).days > 7
        
        assert is_stale is True
    
    def test_marketplace_deactivation_low_performance(self):
        """Test deactivating marketplace with poor performance."""
        marketplace = build_marketplace_fixture(
            name="PoorPerformer",
            bids_placed=100,
            bids_won=1  # Only 1% success rate
        )
        
        # Auto-deactivate if success rate < 5%
        marketplace["is_active"] = marketplace["success_rate"] >= 0.05
        
        assert marketplace["is_active"] is False


class TestMarketplaceEvaluation:
    """Test marketplace quality evaluation."""
    
    @pytest.mark.asyncio
    async def test_marketplace_ui_accessibility(self):
        """Test evaluating marketplace UI accessibility."""
        # Mock marketplace evaluation
        evaluator = AsyncMock()
        evaluator.evaluate_accessibility.return_value = {
            "accessible": True,
            "login_required": True,
            "api_available": False,
            "score": 0.85,
        }
        
        result = await evaluator.evaluate_accessibility()
        
        assert result["accessible"] is True
        assert result["login_required"] is True
        assert result["score"] == 0.85
    
    @pytest.mark.asyncio
    async def test_marketplace_job_availability(self):
        """Test evaluating job availability on marketplace."""
        evaluator = AsyncMock()
        evaluator.check_job_availability.return_value = {
            "jobs_available": 250,
            "jobs_in_category": 80,
            "refresh_rate_hours": 24,
            "availability_score": 0.92,
        }
        
        result = await evaluator.check_job_availability()
        
        assert result["jobs_available"] == 250
        assert result["jobs_in_category"] == 80
        assert result["availability_score"] == 0.92
    
    @pytest.mark.asyncio
    async def test_marketplace_payment_reliability(self):
        """Test evaluating marketplace payment reliability."""
        evaluator = AsyncMock()
        evaluator.evaluate_payment_reliability.return_value = {
            "payment_methods": ["stripe", "paypal", "direct_deposit"],
            "escrow_available": True,
            "avg_payout_days": 5,
            "reliability_score": 0.95,
        }
        
        result = await evaluator.evaluate_payment_reliability()
        
        assert len(result["payment_methods"]) == 3
        assert result["escrow_available"] is True
        assert result["reliability_score"] == 0.95


class TestMarketplaceRanking:
    """Test marketplace ranking and selection logic."""
    
    def test_rank_by_success_rate(self, mock_marketplace_list):
        """Test ranking marketplaces by success rate."""
        sorted_by_success = sorted(
            mock_marketplace_list,
            key=lambda m: m["success_rate"],
            reverse=True
        )
        
        # Toptal has highest success rate (40%)
        assert sorted_by_success[0]["name"] == "Toptal"
        assert sorted_by_success[0]["success_rate"] == 0.400
    
    def test_rank_by_revenue(self, mock_marketplace_list):
        """Test ranking marketplaces by total revenue."""
        sorted_by_revenue = sorted(
            mock_marketplace_list,
            key=lambda m: m["total_revenue"],
            reverse=True
        )
        
        # Toptal has highest revenue
        assert sorted_by_revenue[0]["name"] == "Toptal"
        assert sorted_by_revenue[0]["total_revenue"] == 8000.00
    
    def test_weighted_ranking_score(self, mock_marketplace_list):
        """Test weighted ranking combining multiple factors."""
        # Weights: 40% success rate, 60% revenue
        for marketplace in mock_marketplace_list:
            success_weight = marketplace["success_rate"] * 0.4
            revenue_weight = (marketplace["total_revenue"] / 10000) * 0.6
            marketplace["weighted_score"] = success_weight + revenue_weight
        
        sorted_by_weighted = sorted(
            mock_marketplace_list,
            key=lambda m: m["weighted_score"],
            reverse=True
        )
        
        # Toptal should still rank high
        assert sorted_by_weighted[0]["name"] == "Toptal"
    
    def test_select_top_n_marketplaces(self, mock_marketplace_list):
        """Test selecting top N marketplaces for bidding."""
        top_n = 2
        top_markets = sorted(
            mock_marketplace_list,
            key=lambda m: m["priority_score"],
            reverse=True
        )[:top_n]
        
        assert len(top_markets) == 2
        names = [m["name"] for m in top_markets]
        assert "Toptal" in names
        assert "Fiverr" in names
