"""
Marketplace Adapters Package

Provides extensible adapter pattern for multiple freelance marketplaces.
Implements unified interface for searching, bidding, and tracking across
different platforms (Fiverr, Upwork, PeoplePerHour, etc.).
"""

from .base import (
    MarketplaceAdapter,
    SearchQuery,
    SearchResult,
    BidProposal,
    BidStatus,
    PricingModel,
    MarketplaceError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
)
from .registry import MarketplaceRegistry
from .fiverr_adapter import FiverrAdapter
from .upwork_adapter import UpworkAdapter
from .peoplehour_adapter import PeoplePerHourAdapter

__all__ = [
    "MarketplaceAdapter",
    "SearchQuery",
    "SearchResult",
    "BidProposal",
    "BidStatus",
    "PricingModel",
    "MarketplaceError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    "MarketplaceRegistry",
    "FiverrAdapter",
    "UpworkAdapter",
    "PeoplePerHourAdapter",
]
