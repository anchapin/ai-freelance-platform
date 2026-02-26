"""
Fiverr Marketplace Adapter

Implements marketplace adapter for Fiverr platform.
Handles gig searching, offer placement, and inbox management.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx

from .base import (
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
from src.utils.logger import get_logger
from src.agent_execution.exponential_backoff import ExponentialBackoff

logger = get_logger(__name__)


class FiverrAdapter(MarketplaceAdapter):
    """
    Fiverr marketplace adapter.

    Handles integration with Fiverr API for:
    - Searching gigs/projects
    - Placing offers on gigs
    - Managing inbox/messages
    - Tracking offer status
    """

    # Fiverr API configuration
    API_BASE_URL = "https://www.fiverr.com/api"
    API_VERSION = "v2"
    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        user_token: Optional[str] = None,
    ):
        """
        Initialize Fiverr adapter.

        Args:
            api_key: Fiverr API key
            api_secret: Fiverr API secret
            user_token: User authentication token
        """
        super().__init__("fiverr", api_key, api_secret)
        self.user_token = user_token
        self.client: Optional[httpx.AsyncClient] = None
        self.user_id: Optional[str] = None

    async def authenticate(self) -> bool:
        """
        Authenticate with Fiverr API.

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            if not self.api_key:
                raise AuthenticationError("API key required for Fiverr authentication")

            self.client = httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )

            # Verify authentication by getting user profile
            response = await self.client.get(
                f"{self.API_BASE_URL}/{self.API_VERSION}/user/profile"
            )

            if response.status_code == 401:
                raise AuthenticationError("Invalid Fiverr API key")

            response.raise_for_status()
            profile = response.json()
            self.user_id = profile.get("user_id")
            self._authenticated = True
            logger.info(f"Authenticated with Fiverr as user {self.user_id}")
            return True

        except httpx.HTTPError as e:
            raise AuthenticationError(f"Fiverr authentication failed: {str(e)}")

    async def search(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search for gigs on Fiverr.

        Args:
            query: Search parameters

        Returns:
            List of search results

        Raises:
            MarketplaceError: If search fails
            RateLimitError: If rate limited
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            # Build search parameters
            params = {
                "q": query.keywords,
                "page": query.page,
                "limit": min(query.limit, 50),  # Fiverr max per page
            }

            if query.min_budget:
                params["min_price"] = int(query.min_budget)
            if query.max_budget:
                params["max_price"] = int(query.max_budget)

            if query.skills:
                params["skills"] = ",".join(query.skills)

            # Make search request with retry
            response = await self._request(
                "GET",
                f"{self.API_BASE_URL}/{self.API_VERSION}/gigs/search",
                params=params,
            )

            results = []
            for gig in response.get("gigs", []):
                result = SearchResult(
                    marketplace_name="fiverr",
                    job_id=str(gig.get("gig_id")),
                    title=gig.get("title", ""),
                    description=gig.get("description", ""),
                    budget=float(gig.get("price", 0)),
                    pricing_model=PricingModel.FIXED,
                    client_name=gig.get("seller_name", ""),
                    client_rating=float(gig.get("seller_rating", 0)),
                    created_at=self._parse_datetime(gig.get("created_at")),
                    url=gig.get("url"),
                    metadata=gig,
                )
                results.append(result)

            logger.info(
                f"Fiverr search returned {len(results)} results for '{query.keywords}'"
            )
            return results

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitError("Fiverr rate limit exceeded")
            raise MarketplaceError(f"Fiverr search failed: {str(e)}")

    async def get_job_details(self, job_id: str) -> SearchResult:
        """
        Get detailed information about a Fiverr gig.

        Args:
            job_id: Gig ID

        Returns:
            Detailed gig information

        Raises:
            NotFoundError: If gig not found
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET", f"{self.API_BASE_URL}/{self.API_VERSION}/gigs/{job_id}"
            )

            gig = response.get("gig", {})
            return SearchResult(
                marketplace_name="fiverr",
                job_id=str(gig.get("gig_id")),
                title=gig.get("title", ""),
                description=gig.get("description", ""),
                budget=float(gig.get("price", 0)),
                pricing_model=PricingModel.FIXED,
                client_name=gig.get("seller_name", ""),
                client_rating=float(gig.get("seller_rating", 0)),
                skills_required=gig.get("tags", []),
                created_at=self._parse_datetime(gig.get("created_at")),
                url=gig.get("url"),
                metadata=gig,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Gig {job_id} not found")
            raise MarketplaceError(f"Failed to get gig details: {str(e)}")

    async def place_bid(self, proposal: BidProposal) -> PlacedBid:
        """
        Place an offer on a Fiverr gig.

        Args:
            proposal: Bid proposal

        Returns:
            Placed bid information

        Raises:
            MarketplaceError: If bid placement fails
            RateLimitError: If rate limited
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            payload = {
                "gig_id": proposal.job_id,
                "message": proposal.proposal_text,
                "price": proposal.amount,
            }

            if proposal.cover_letter:
                payload["cover_letter"] = proposal.cover_letter

            response = await self._request(
                "POST",
                f"{self.API_BASE_URL}/{self.API_VERSION}/offers",
                json=payload,
            )

            offer = response.get("offer", {})
            return PlacedBid(
                marketplace_name="fiverr",
                bid_id=str(offer.get("offer_id")),
                job_id=proposal.job_id,
                status=BidStatus.SUBMITTED,
                amount=proposal.amount,
                pricing_model=proposal.pricing_model,
                submitted_at=datetime.utcnow(),
                url=offer.get("url"),
                metadata=offer,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitError("Fiverr rate limit exceeded")
            raise MarketplaceError(f"Failed to place Fiverr offer: {str(e)}")

    async def get_bid_status(self, bid_id: str) -> BidStatusUpdate:
        """
        Get status of a placed offer.

        Args:
            bid_id: Offer ID

        Returns:
            Bid status update

        Raises:
            NotFoundError: If offer not found
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET", f"{self.API_BASE_URL}/{self.API_VERSION}/offers/{bid_id}"
            )

            offer = response.get("offer", {})
            status_map = {
                "pending": BidStatus.PENDING,
                "accepted": BidStatus.ACCEPTED,
                "rejected": BidStatus.REJECTED,
                "withdrawn": BidStatus.WITHDRAWN,
            }

            return BidStatusUpdate(
                marketplace_name="fiverr",
                bid_id=bid_id,
                job_id=offer.get("gig_id", ""),
                status=status_map.get(
                    offer.get("status", "").lower(), BidStatus.PENDING
                ),
                last_updated=self._parse_datetime(offer.get("updated_at")),
                metadata=offer,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Offer {bid_id} not found")
            raise MarketplaceError(f"Failed to get offer status: {str(e)}")

    async def withdraw_bid(self, bid_id: str) -> BidStatusUpdate:
        """
        Withdraw a placed offer.

        Args:
            bid_id: Offer ID

        Returns:
            Updated bid status

        Raises:
            NotFoundError: If offer not found
            MarketplaceError: If withdrawal fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "POST",
                f"{self.API_BASE_URL}/{self.API_VERSION}/offers/{bid_id}/withdraw",
            )

            offer = response.get("offer", {})
            return BidStatusUpdate(
                marketplace_name="fiverr",
                bid_id=bid_id,
                job_id=offer.get("gig_id", ""),
                status=BidStatus.WITHDRAWN,
                last_updated=datetime.utcnow(),
                metadata=offer,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Offer {bid_id} not found")
            raise MarketplaceError(f"Failed to withdraw offer: {str(e)}")

    async def check_inbox(self) -> List[InboxMessage]:
        """
        Check for new messages in Fiverr inbox.

        Returns:
            List of unread messages

        Raises:
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET",
                f"{self.API_BASE_URL}/{self.API_VERSION}/inbox",
                params={"unread_only": True},
            )

            messages = []
            for msg in response.get("messages", []):
                message = InboxMessage(
                    message_id=str(msg.get("message_id")),
                    sender_name=msg.get("sender_name", ""),
                    subject=msg.get("subject", ""),
                    body=msg.get("body", ""),
                    created_at=self._parse_datetime(msg.get("created_at")),
                    is_read=msg.get("is_read", False),
                    url=msg.get("url"),
                    metadata=msg,
                )
                messages.append(message)

            logger.info(f"Retrieved {len(messages)} unread Fiverr messages")
            return messages

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(f"Failed to check Fiverr inbox: {str(e)}")

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
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            await self._request(
                "POST",
                f"{self.API_BASE_URL}/{self.API_VERSION}/messages/{message_id}/read",
            )
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Message {message_id} not found")
            raise MarketplaceError(f"Failed to mark message as read: {str(e)}")

    async def sync_portfolio(self, portfolio_items: List[Dict[str, Any]]) -> bool:
        """
        Sync portfolio with Fiverr.

        Args:
            portfolio_items: List of portfolio items

        Returns:
            True if successful

        Raises:
            MarketplaceError: If sync fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            payload = {"portfolio_items": portfolio_items}
            await self._request(
                "PUT",
                f"{self.API_BASE_URL}/{self.API_VERSION}/user/portfolio",
                json=payload,
            )
            logger.info(f"Synced {len(portfolio_items)} portfolio items to Fiverr")
            return True

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(f"Failed to sync Fiverr portfolio: {str(e)}")

    async def close(self) -> None:
        """Clean up resources."""
        if self.client:
            await self.client.aclose()
            self.client = None

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make HTTP request with automatic retry and error handling.

        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional arguments for httpx

        Returns:
            Response JSON

        Raises:
            MarketplaceError: If request fails
            RateLimitError: If rate limited
        """
        if not self.client:
            raise MarketplaceError("Not authenticated")

        async def _do_request():
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()

        # Retry with exponential backoff
        backoff = ExponentialBackoff(base_delay=1.0)
        return await backoff.with_retry(_do_request, max_retries=3)

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from Fiverr API."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
