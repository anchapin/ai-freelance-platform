"""
Base Marketplace Adapter

Defines abstract interface for all marketplace adapters.
Provides common data models, error handling, and retry logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================================
# ERROR HANDLING
# ============================================================================


class MarketplaceError(Exception):
    """Base exception for marketplace operations."""

    pass


class AuthenticationError(MarketplaceError):
    """Raised when authentication fails."""

    pass


class RateLimitError(MarketplaceError):
    """Raised when rate limit is exceeded."""

    pass


class NotFoundError(MarketplaceError):
    """Raised when resource is not found."""

    pass


# ============================================================================
# ENUMS
# ============================================================================


class BidStatus(str, Enum):
    """Bid status across all marketplaces."""

    PENDING = "PENDING"  # Bid created locally, not submitted yet
    SUBMITTED = "SUBMITTED"  # Bid submitted to marketplace
    ACCEPTED = "ACCEPTED"  # Bid accepted by client
    REJECTED = "REJECTED"  # Bid rejected by client
    WITHDRAWN = "WITHDRAWN"  # Bid withdrawn by user
    EXPIRED = "EXPIRED"  # Bid expired (time limit passed)
    DUPLICATED = "DUPLICATED"  # Duplicate bid detected


class PricingModel(str, Enum):
    """Pricing models supported across marketplaces."""

    FIXED = "FIXED"  # Fixed price project
    HOURLY = "HOURLY"  # Hourly rate
    VALUE_BASED = "VALUE_BASED"  # Value-based pricing


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SearchQuery:
    """Marketplace search parameters."""

    keywords: str
    min_budget: Optional[float] = None
    max_budget: Optional[float] = None
    skills: Optional[List[str]] = None
    experience_level: Optional[str] = None  # entry, intermediate, expert
    job_type: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    sort_by: str = "relevance"  # relevance, budget, deadline
    page: int = 1
    limit: int = 10
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Search result from marketplace."""

    marketplace_name: str
    job_id: str
    title: str
    description: str
    budget: float
    pricing_model: PricingModel
    client_name: str
    client_rating: Optional[float] = None
    proposals_count: Optional[int] = None
    created_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    skills_required: Optional[List[str]] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BidProposal:
    """Bid/offer to submit to marketplace."""

    marketplace_name: str
    job_id: str
    amount: float
    pricing_model: PricingModel
    proposal_text: str
    cover_letter: Optional[str] = None
    estimated_duration: Optional[int] = None  # in days
    availability: Optional[str] = None
    attachments: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlacedBid:
    """Response from placing a bid."""

    marketplace_name: str
    bid_id: str
    job_id: str
    status: BidStatus
    amount: float
    pricing_model: PricingModel
    submitted_at: datetime
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BidStatusUpdate:
    """Status update for a placed bid."""

    marketplace_name: str
    bid_id: str
    job_id: str
    status: BidStatus
    last_updated: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InboxMessage:
    """Message in marketplace inbox."""

    message_id: str
    sender_name: str
    subject: str
    body: str
    created_at: datetime
    is_read: bool = False
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# BASE ADAPTER CLASS
# ============================================================================


class MarketplaceAdapter(ABC):
    """
    Abstract base class for marketplace adapters.

    Defines the interface that all marketplace adapters must implement.
    Provides common functionality for error handling and retry logic.
    """

    def __init__(
        self,
        marketplace_name: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        """
        Initialize adapter.

        Args:
            marketplace_name: Name of the marketplace
            api_key: API key for authentication
            api_secret: API secret for authentication
        """
        self.marketplace_name = marketplace_name
        self.api_key = api_key
        self.api_secret = api_secret
        self._authenticated = False

    # ========================================================================
    # ABSTRACT METHODS (must be implemented by subclasses)
    # ========================================================================

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the marketplace.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def search(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search for jobs on the marketplace.

        Args:
            query: Search parameters

        Returns:
            List of search results

        Raises:
            MarketplaceError: If search fails
            RateLimitError: If rate limited
        """
        pass

    @abstractmethod
    async def get_job_details(self, job_id: str) -> SearchResult:
        """
        Get detailed information about a job.

        Args:
            job_id: ID of the job

        Returns:
            Detailed job information

        Raises:
            NotFoundError: If job not found
            MarketplaceError: If request fails
        """
        pass

    @abstractmethod
    async def place_bid(self, proposal: BidProposal) -> PlacedBid:
        """
        Place a bid/offer on a job.

        Args:
            proposal: Bid proposal

        Returns:
            Placed bid information

        Raises:
            MarketplaceError: If bid placement fails
            RateLimitError: If rate limited
        """
        pass

    @abstractmethod
    async def get_bid_status(self, bid_id: str) -> BidStatusUpdate:
        """
        Get status of a placed bid.

        Args:
            bid_id: ID of the bid

        Returns:
            Bid status update

        Raises:
            NotFoundError: If bid not found
            MarketplaceError: If request fails
        """
        pass

    @abstractmethod
    async def withdraw_bid(self, bid_id: str) -> BidStatusUpdate:
        """
        Withdraw a placed bid.

        Args:
            bid_id: ID of the bid

        Returns:
            Updated bid status

        Raises:
            NotFoundError: If bid not found
            MarketplaceError: If withdrawal fails
        """
        pass

    @abstractmethod
    async def check_inbox(self) -> List[InboxMessage]:
        """
        Check for new messages in marketplace inbox.

        Returns:
            List of unread messages

        Raises:
            MarketplaceError: If request fails
        """
        pass

    @abstractmethod
    async def mark_message_read(self, message_id: str) -> bool:
        """
        Mark a message as read.

        Args:
            message_id: ID of the message

        Returns:
            True if successful

        Raises:
            NotFoundError: If message not found
            MarketplaceError: If request fails
        """
        pass

    @abstractmethod
    async def sync_portfolio(self, portfolio_items: List[Dict[str, Any]]) -> bool:
        """
        Sync portfolio/profile with marketplace.

        Args:
            portfolio_items: List of portfolio items

        Returns:
            True if successful

        Raises:
            MarketplaceError: If sync fails
        """
        pass

    # ========================================================================
    # COMMON METHODS
    # ========================================================================

    async def is_authenticated(self) -> bool:
        """Check if adapter is authenticated."""
        return self._authenticated

    async def close(self) -> None:
        """Clean up resources."""
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        await self.authenticate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
