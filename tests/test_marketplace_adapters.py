"""
Standalone tests for Marketplace Adapters

These tests import marketplace adapters directly to avoid circular dependencies
with the main agent_execution module.
"""

import pytest
import asyncio
import sys
from datetime import datetime
from typing import List
from unittest.mock import Mock, AsyncMock, patch
import httpx
import os

# Add src to path for direct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import directly from base module to avoid circular imports
from src.agent_execution.marketplace_adapters.base import (
    MarketplaceAdapter,
    SearchQuery,
    SearchResult,
    BidProposal,
    BidStatus,
    BidStatusUpdate,
    PlacedBid,
    PricingModel,
    InboxMessage,
    MarketplaceError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
)

# Import registry
from src.agent_execution.marketplace_adapters.registry import MarketplaceRegistry

# Import adapters
from src.agent_execution.marketplace_adapters.fiverr_adapter import FiverrAdapter
from src.agent_execution.marketplace_adapters.upwork_adapter import UpworkAdapter
from src.agent_execution.marketplace_adapters.peoplehour_adapter import (
    PeoplePerHourAdapter,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def registry():
    """Clear and return registry for testing."""
    MarketplaceRegistry.clear()
    return MarketplaceRegistry


@pytest.fixture
def search_query():
    """Sample search query."""
    return SearchQuery(
        keywords="python django developer",
        min_budget=500,
        max_budget=2000,
        skills=["python", "django", "rest-api"],
        job_type="fixed",
        limit=10,
    )


@pytest.fixture
def bid_proposal():
    """Sample bid proposal."""
    return BidProposal(
        marketplace_name="fiverr",
        job_id="job123",
        amount=1000,
        pricing_model=PricingModel.FIXED,
        proposal_text="I am an expert Python developer with 5+ years experience",
        cover_letter="Looking forward to discussing this project",
    )


# ============================================================================
# DATA MODEL TESTS
# ============================================================================


class TestDataModels:
    """Test data classes and models."""

    def test_search_query_creation(self, search_query):
        """Test creating search query."""
        assert search_query.keywords == "python django developer"
        assert search_query.min_budget == 500
        assert search_query.max_budget == 2000
        assert search_query.page == 1
        assert search_query.limit == 10

    def test_search_query_defaults(self):
        """Test search query with defaults."""
        query = SearchQuery(keywords="test")
        assert query.keywords == "test"
        assert query.page == 1
        assert query.limit == 10
        assert query.sort_by == "relevance"

    def test_search_result_creation(self):
        """Test creating search result."""
        result = SearchResult(
            marketplace_name="fiverr",
            job_id="job123",
            title="Python Project",
            description="Need a Python developer",
            budget=1000,
            pricing_model=PricingModel.FIXED,
            client_name="Client Name",
            client_rating=4.5,
        )
        assert result.job_id == "job123"
        assert result.marketplace_name == "fiverr"

    def test_bid_proposal_creation(self, bid_proposal):
        """Test creating bid proposal."""
        assert bid_proposal.job_id == "job123"
        assert bid_proposal.amount == 1000
        assert bid_proposal.marketplace_name == "fiverr"

    def test_bid_status_enum(self):
        """Test BidStatus enum."""
        assert BidStatus.PENDING.value == "PENDING"
        assert BidStatus.SUBMITTED.value == "SUBMITTED"
        assert BidStatus.ACCEPTED.value == "ACCEPTED"
        assert BidStatus.REJECTED.value == "REJECTED"
        assert BidStatus.WITHDRAWN.value == "WITHDRAWN"

    def test_pricing_model_enum(self):
        """Test PricingModel enum."""
        assert PricingModel.FIXED.value == "FIXED"
        assert PricingModel.HOURLY.value == "HOURLY"
        assert PricingModel.VALUE_BASED.value == "VALUE_BASED"


# ============================================================================
# REGISTRY TESTS
# ============================================================================


class TestMarketplaceRegistry:
    """Test the marketplace registry factory pattern."""

    def test_register_adapter(self, registry):
        """Test registering a marketplace adapter."""
        registry.register("test", FiverrAdapter)
        assert registry.is_registered("test")
        assert registry.get("test") == FiverrAdapter

    def test_register_case_insensitive(self, registry):
        """Test that marketplace names are case-insensitive."""
        registry.register("FIVERR", FiverrAdapter)
        assert registry.is_registered("fiverr")
        assert registry.is_registered("FIVERR")
        assert registry.is_registered("FiVerr")

    def test_get_non_existent(self, registry):
        """Test getting non-existent adapter."""
        assert registry.get("nonexistent") is None

    def test_create_adapter(self, registry):
        """Test creating adapter instance."""
        registry.register("fiverr", FiverrAdapter)
        adapter = registry.create("fiverr", api_key="test_key")
        assert isinstance(adapter, FiverrAdapter)
        assert adapter.api_key == "test_key"

    def test_create_non_registered_raises(self, registry):
        """Test creating non-registered adapter raises error."""
        with pytest.raises(ValueError, match="not registered"):
            registry.create("nonexistent")

    def test_list_registered(self, registry):
        """Test listing registered adapters."""
        registry.register("fiverr", FiverrAdapter)
        registry.register("upwork", UpworkAdapter)
        registered = registry.list_registered()
        assert "fiverr" in registered
        assert "upwork" in registered

    def test_clear_registry(self, registry):
        """Test clearing all registrations."""
        registry.register("fiverr", FiverrAdapter)
        registry.register("upwork", UpworkAdapter)
        assert len(registry.list_registered()) >= 2

        registry.clear()
        assert len(registry.list_registered()) == 0

    def test_register_all_adapters(self, registry):
        """Test registering all marketplace adapters."""
        registry.register("fiverr", FiverrAdapter)
        registry.register("upwork", UpworkAdapter)
        registry.register("peoplehour", PeoplePerHourAdapter)

        assert registry.is_registered("fiverr")
        assert registry.is_registered("upwork")
        assert registry.is_registered("peoplehour")
        assert len(registry.list_registered()) == 3


# ============================================================================
# FIVERR ADAPTER TESTS
# ============================================================================


class TestFiverrAdapter:
    """Test Fiverr marketplace adapter."""

    def test_adapter_init(self):
        """Test adapter initialization."""
        adapter = FiverrAdapter(api_key="test_key")
        assert adapter.marketplace_name == "fiverr"
        assert adapter.api_key == "test_key"
        assert not adapter._authenticated

    @pytest.mark.asyncio
    async def test_authenticate_no_api_key(self):
        """Test authentication without API key."""
        adapter = FiverrAdapter()

        with pytest.raises(AuthenticationError):
            await adapter.authenticate()

    @pytest.mark.asyncio
    async def test_search_not_authenticated(self, search_query):
        """Test search when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.search(search_query)

    @pytest.mark.asyncio
    async def test_place_bid_not_authenticated(self, bid_proposal):
        """Test placing bid when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.place_bid(bid_proposal)

    @pytest.mark.asyncio
    async def test_get_bid_status_not_authenticated(self):
        """Test getting bid status when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.get_bid_status("bid123")

    @pytest.mark.asyncio
    async def test_withdraw_bid_not_authenticated(self):
        """Test withdrawing bid when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.withdraw_bid("bid123")

    @pytest.mark.asyncio
    async def test_check_inbox_not_authenticated(self):
        """Test checking inbox when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.check_inbox()

    @pytest.mark.asyncio
    async def test_sync_portfolio_not_authenticated(self):
        """Test syncing portfolio when not authenticated."""
        adapter = FiverrAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.sync_portfolio([])

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        """Test closing adapter with client."""
        adapter = FiverrAdapter(api_key="test_key")
        mock_client = AsyncMock()
        adapter.client = mock_client

        await adapter.close()

        mock_client.aclose.assert_called_once()
        assert adapter.client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        """Test closing adapter without client."""
        adapter = FiverrAdapter(api_key="test_key")
        adapter.client = None

        # Should not raise
        await adapter.close()
        assert adapter.client is None


# ============================================================================
# UPWORK ADAPTER TESTS
# ============================================================================


class TestUpworkAdapter:
    """Test Upwork marketplace adapter."""

    def test_adapter_init(self):
        """Test adapter initialization."""
        adapter = UpworkAdapter(access_token="test_token")
        assert adapter.marketplace_name == "upwork"
        assert adapter.access_token == "test_token"
        assert not adapter._authenticated

    @pytest.mark.asyncio
    async def test_authenticate_no_token(self):
        """Test authentication without access token."""
        adapter = UpworkAdapter()

        with pytest.raises(AuthenticationError, match="Access token required"):
            await adapter.authenticate()

    @pytest.mark.asyncio
    async def test_search_not_authenticated(self, search_query):
        """Test search when not authenticated."""
        adapter = UpworkAdapter(access_token="test_token")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.search(search_query)


# ============================================================================
# PEOPLEHOUR ADAPTER TESTS
# ============================================================================


class TestPeoplePerHourAdapter:
    """Test PeoplePerHour marketplace adapter."""

    def test_adapter_init(self):
        """Test adapter initialization."""
        adapter = PeoplePerHourAdapter(api_key="test_key")
        assert adapter.marketplace_name == "peoplehour"
        assert adapter.api_key == "test_key"
        assert not adapter._authenticated

    @pytest.mark.asyncio
    async def test_authenticate_no_api_key(self):
        """Test authentication without API key."""
        adapter = PeoplePerHourAdapter()

        with pytest.raises(AuthenticationError, match="API key required"):
            await adapter.authenticate()

    @pytest.mark.asyncio
    async def test_search_not_authenticated(self, search_query):
        """Test search when not authenticated."""
        adapter = PeoplePerHourAdapter(api_key="test_key")

        with pytest.raises(MarketplaceError, match="Not authenticated"):
            await adapter.search(search_query)


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


class TestErrorHandling:
    """Test error handling classes."""

    def test_marketplace_error(self):
        """Test MarketplaceError."""
        error = MarketplaceError("Test error")
        assert str(error) == "Test error"

    def test_authentication_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError("Invalid key")
        assert isinstance(error, MarketplaceError)
        assert str(error) == "Invalid key"

    def test_rate_limit_error(self):
        """Test RateLimitError."""
        error = RateLimitError("Too many requests")
        assert isinstance(error, MarketplaceError)
        assert str(error) == "Too many requests"

    def test_not_found_error(self):
        """Test NotFoundError."""
        error = NotFoundError("Job not found")
        assert isinstance(error, MarketplaceError)
        assert str(error) == "Job not found"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestMarketplaceIntegration:
    """Integration tests for marketplace adapters."""

    def test_multiple_adapters_instantiation(self, registry):
        """Test instantiating multiple adapters."""
        registry.register("fiverr", FiverrAdapter)
        registry.register("upwork", UpworkAdapter)
        registry.register("peoplehour", PeoplePerHourAdapter)

        fiverr = registry.create("fiverr", api_key="key1")
        upwork = registry.create("upwork", access_token="token1")
        peoplehour = registry.create("peoplehour", api_key="key3")

        assert isinstance(fiverr, FiverrAdapter)
        assert isinstance(upwork, UpworkAdapter)
        assert isinstance(peoplehour, PeoplePerHourAdapter)

        assert fiverr.marketplace_name == "fiverr"
        assert upwork.marketplace_name == "upwork"
        assert peoplehour.marketplace_name == "peoplehour"

    @pytest.mark.asyncio
    async def test_adapter_context_manager(self):
        """Test adapter as async context manager."""
        adapter = FiverrAdapter(api_key="test_key")

        # Mock authenticate and manually set authenticated
        async def mock_auth():
            adapter._authenticated = True
            return True

        adapter.authenticate = mock_auth
        adapter.close = AsyncMock()

        async with adapter:
            assert adapter._authenticated

        adapter.close.assert_called_once()

    def test_adapter_interface_completeness(self):
        """Test that all adapters implement required interface."""
        adapters = [FiverrAdapter, UpworkAdapter, PeoplePerHourAdapter]

        required_methods = [
            "authenticate",
            "search",
            "get_job_details",
            "place_bid",
            "get_bid_status",
            "withdraw_bid",
            "check_inbox",
            "mark_message_read",
            "sync_portfolio",
        ]

        for adapter_class in adapters:
            for method in required_methods:
                assert hasattr(adapter_class, method), (
                    f"{adapter_class.__name__} missing {method}"
                )


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
