"""
PeoplePerHour Marketplace Adapter

Implements marketplace adapter for PeoplePerHour platform.
Handles project searching, offer placement, and portfolio sync.
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


class PeoplePerHourAdapter(MarketplaceAdapter):
    """
    PeoplePerHour marketplace adapter.

    Handles integration with PeoplePerHour API for:
    - Searching projects
    - Placing offers
    - Portfolio management
    - Message tracking
    """

    # PeoplePerHour API configuration
    API_BASE_URL = "https://api.peoplehour.com/v1"
    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        """
        Initialize PeoplePerHour adapter.

        Args:
            api_key: PeoplePerHour API key
            api_secret: PeoplePerHour API secret
        """
        super().__init__("peoplehour", api_key, api_secret)
        self.client: Optional[httpx.AsyncClient] = None
        self.user_id: Optional[str] = None

    async def authenticate(self) -> bool:
        """
        Authenticate with PeoplePerHour API.

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            if not self.api_key:
                raise AuthenticationError("API key required for PeoplePerHour")

            self.client = httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT)

            # Verify authentication by getting user profile
            headers = self._get_auth_headers()
            response = await self.client.get(
                f"{self.API_BASE_URL}/user/profile", headers=headers
            )

            if response.status_code == 401:
                raise AuthenticationError("Invalid PeoplePerHour API key")

            response.raise_for_status()
            profile = response.json()
            self.user_id = profile.get("user_id")
            self._authenticated = True
            logger.info(f"Authenticated with PeoplePerHour as user {self.user_id}")
            return True

        except httpx.HTTPError as e:
            raise AuthenticationError(
                f"PeoplePerHour authentication failed: {str(e)}"
            )

    async def search(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search for projects on PeoplePerHour.

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
                "limit": min(query.limit, 50),
            }

            if query.min_budget:
                params["budget_from"] = int(query.min_budget)
            if query.max_budget:
                params["budget_to"] = int(query.max_budget)

            if query.skills:
                params["skills"] = ",".join(query.skills)

            if query.job_type:
                params["type"] = query.job_type

            # Make search request
            response = await self._request(
                "GET", f"{self.API_BASE_URL}/projects/search", params=params
            )

            results = []
            for project in response.get("projects", []):
                # Determine pricing model
                pricing_model = PricingModel.FIXED
                project_type = project.get("type", "").lower()
                if project_type in ["hourly", "time_material"]:
                    pricing_model = PricingModel.HOURLY

                result = SearchResult(
                    marketplace_name="peoplehour",
                    job_id=str(project.get("project_id")),
                    title=project.get("title", ""),
                    description=project.get("description", ""),
                    budget=float(project.get("budget", 0)),
                    pricing_model=pricing_model,
                    client_name=project.get("client_name", ""),
                    client_rating=float(project.get("client_rating", 0)),
                    proposals_count=project.get("offers_count", 0),
                    created_at=self._parse_datetime(project.get("posted_at")),
                    deadline=self._parse_datetime(project.get("deadline")),
                    skills_required=project.get("required_skills", []),
                    url=project.get("url"),
                    metadata=project,
                )
                results.append(result)

            logger.info(
                f"PeoplePerHour search returned {len(results)} results for '{query.keywords}'"
            )
            return results

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitError("PeoplePerHour rate limit exceeded")
            raise MarketplaceError(f"PeoplePerHour search failed: {str(e)}")

    async def get_job_details(self, job_id: str) -> SearchResult:
        """
        Get detailed information about a project.

        Args:
            job_id: Project ID

        Returns:
            Detailed project information

        Raises:
            NotFoundError: If project not found
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET", f"{self.API_BASE_URL}/projects/{job_id}"
            )

            project = response.get("project", {})

            # Determine pricing model
            pricing_model = PricingModel.FIXED
            project_type = project.get("type", "").lower()
            if project_type in ["hourly", "time_material"]:
                pricing_model = PricingModel.HOURLY

            return SearchResult(
                marketplace_name="peoplehour",
                job_id=str(project.get("project_id")),
                title=project.get("title", ""),
                description=project.get("description", ""),
                budget=float(project.get("budget", 0)),
                pricing_model=pricing_model,
                client_name=project.get("client_name", ""),
                client_rating=float(project.get("client_rating", 0)),
                proposals_count=project.get("offers_count", 0),
                created_at=self._parse_datetime(project.get("posted_at")),
                deadline=self._parse_datetime(project.get("deadline")),
                skills_required=project.get("required_skills", []),
                url=project.get("url"),
                metadata=project,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Project {job_id} not found")
            raise MarketplaceError(f"Failed to get project details: {str(e)}")

    async def place_bid(self, proposal: BidProposal) -> PlacedBid:
        """
        Place an offer on a project.

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
                "project_id": proposal.job_id,
                "amount": proposal.amount,
                "proposal": proposal.proposal_text,
            }

            if proposal.cover_letter:
                payload["message"] = proposal.cover_letter

            if proposal.estimated_duration:
                payload["duration_days"] = proposal.estimated_duration

            if proposal.availability:
                payload["availability"] = proposal.availability

            response = await self._request(
                "POST", f"{self.API_BASE_URL}/offers", json=payload
            )

            offer = response.get("offer", {})
            return PlacedBid(
                marketplace_name="peoplehour",
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
                raise RateLimitError("PeoplePerHour rate limit exceeded")
            raise MarketplaceError(f"Failed to place PeoplePerHour offer: {str(e)}")

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
                "GET", f"{self.API_BASE_URL}/offers/{bid_id}"
            )

            offer = response.get("offer", {})
            status_map = {
                "pending": BidStatus.PENDING,
                "accepted": BidStatus.ACCEPTED,
                "rejected": BidStatus.REJECTED,
                "withdrawn": BidStatus.WITHDRAWN,
                "expired": BidStatus.EXPIRED,
            }

            return BidStatusUpdate(
                marketplace_name="peoplehour",
                bid_id=bid_id,
                job_id=offer.get("project_id", ""),
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
                "POST", f"{self.API_BASE_URL}/offers/{bid_id}/withdraw"
            )

            offer = response.get("offer", {})
            return BidStatusUpdate(
                marketplace_name="peoplehour",
                bid_id=bid_id,
                job_id=offer.get("project_id", ""),
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
        Check for new messages in inbox.

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
                f"{self.API_BASE_URL}/inbox",
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

            logger.info(f"Retrieved {len(messages)} unread PeoplePerHour messages")
            return messages

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(f"Failed to check PeoplePerHour inbox: {str(e)}")

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
                "POST", f"{self.API_BASE_URL}/messages/{message_id}/read"
            )
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Message {message_id} not found")
            raise MarketplaceError(f"Failed to mark message as read: {str(e)}")

    async def sync_portfolio(self, portfolio_items: List[Dict[str, Any]]) -> bool:
        """
        Sync portfolio with PeoplePerHour.

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
                f"{self.API_BASE_URL}/user/portfolio",
                json=payload,
            )

            logger.info(
                f"Synced {len(portfolio_items)} portfolio items to PeoplePerHour"
            )
            return True

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(
                f"Failed to sync PeoplePerHour portfolio: {str(e)}"
            )

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

        # Add auth headers
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"].update(self._get_auth_headers())

        async def _do_request():
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()

        # Retry with exponential backoff
        backoff = ExponentialBackoff(base_delay=1.0)
        return await backoff.with_retry(_do_request, max_retries=3)

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for PeoplePerHour API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from PeoplePerHour API."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
