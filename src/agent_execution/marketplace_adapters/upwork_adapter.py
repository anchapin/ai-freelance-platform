"""
Upwork Marketplace Adapter

Implements marketplace adapter for Upwork platform.
Handles job searching, proposal placement, and contract management.
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


class UpworkAdapter(MarketplaceAdapter):
    """
    Upwork marketplace adapter.

    Handles integration with Upwork API for:
    - Searching jobs
    - Placing proposals
    - Managing contracts
    - Tracking proposal status
    """

    # Upwork API configuration
    API_BASE_URL = "https://www.upwork.com/api"
    API_VERSION = "v2"
    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
    ):
        """
        Initialize Upwork adapter.

        Args:
            api_key: Upwork client ID
            api_secret: Upwork client secret
            access_token: OAuth access token
            access_token_secret: OAuth access token secret
        """
        super().__init__("upwork", api_key, api_secret)
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.client: Optional[httpx.AsyncClient] = None
        self.user_id: Optional[str] = None

    async def authenticate(self) -> bool:
        """
        Authenticate with Upwork API.

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            if not self.access_token:
                raise AuthenticationError("Access token required for Upwork")

            self.client = httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT)

            # Verify authentication by getting user profile
            headers = self._get_auth_headers()
            response = await self.client.get(
                f"{self.API_BASE_URL}/{self.API_VERSION}/contractors/profile",
                headers=headers,
            )

            if response.status_code == 401:
                raise AuthenticationError("Invalid Upwork access token")

            response.raise_for_status()
            profile = response.json()
            self.user_id = profile.get("profile", {}).get("user_id")
            self._authenticated = True
            logger.info(f"Authenticated with Upwork as user {self.user_id}")
            return True

        except httpx.HTTPError as e:
            raise AuthenticationError(f"Upwork authentication failed: {str(e)}")

    async def search(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search for jobs on Upwork.

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
                "offset": (query.page - 1) * query.limit,
                "limit": min(query.limit, 50),
            }

            if query.min_budget:
                params["budget_from"] = int(query.min_budget)
            if query.max_budget:
                params["budget_to"] = int(query.max_budget)

            if query.job_type:
                params["job_type"] = query.job_type

            # Make search request
            response = await self._request(
                "GET",
                f"{self.API_BASE_URL}/{self.API_VERSION}/jobs/search",
                params=params,
            )

            results = []
            for job in response.get("jobs", []):
                # Determine pricing model
                pricing_model = PricingModel.FIXED
                if job.get("commitment", {}).get("interval") == "hourly":
                    pricing_model = PricingModel.HOURLY

                result = SearchResult(
                    marketplace_name="upwork",
                    job_id=str(job.get("id")),
                    title=job.get("title", ""),
                    description=job.get("description", ""),
                    budget=float(job.get("budget", {}).get("amount", 0)),
                    pricing_model=pricing_model,
                    client_name=job.get("client", {}).get("name", ""),
                    client_rating=float(job.get("client", {}).get("rating", 0)),
                    proposals_count=job.get("proposals_count", 0),
                    created_at=self._parse_datetime(job.get("posted_on")),
                    deadline=self._parse_datetime(job.get("deadline")),
                    skills_required=job.get("skills", []),
                    url=job.get("url"),
                    metadata=job,
                )
                results.append(result)

            logger.info(
                f"Upwork search returned {len(results)} results for '{query.keywords}'"
            )
            return results

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitError("Upwork rate limit exceeded")
            raise MarketplaceError(f"Upwork search failed: {str(e)}")

    async def get_job_details(self, job_id: str) -> SearchResult:
        """
        Get detailed information about an Upwork job.

        Args:
            job_id: Job ID

        Returns:
            Detailed job information

        Raises:
            NotFoundError: If job not found
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET", f"{self.API_BASE_URL}/{self.API_VERSION}/jobs/{job_id}"
            )

            job = response.get("job", {})

            # Determine pricing model
            pricing_model = PricingModel.FIXED
            if job.get("commitment", {}).get("interval") == "hourly":
                pricing_model = PricingModel.HOURLY

            return SearchResult(
                marketplace_name="upwork",
                job_id=str(job.get("id")),
                title=job.get("title", ""),
                description=job.get("description", ""),
                budget=float(job.get("budget", {}).get("amount", 0)),
                pricing_model=pricing_model,
                client_name=job.get("client", {}).get("name", ""),
                client_rating=float(job.get("client", {}).get("rating", 0)),
                proposals_count=job.get("proposals_count", 0),
                created_at=self._parse_datetime(job.get("posted_on")),
                deadline=self._parse_datetime(job.get("deadline")),
                skills_required=job.get("skills", []),
                url=job.get("url"),
                metadata=job,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Job {job_id} not found")
            raise MarketplaceError(f"Failed to get job details: {str(e)}")

    async def place_bid(self, proposal: BidProposal) -> PlacedBid:
        """
        Place a proposal on an Upwork job.

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
                "job_id": proposal.job_id,
                "proposal_text": proposal.proposal_text,
                "bidding_tier_id": self._get_bidding_tier_id(proposal.amount),
            }

            if proposal.cover_letter:
                payload["cover_letter"] = proposal.cover_letter

            if proposal.estimated_duration:
                payload["duration"] = proposal.estimated_duration

            response = await self._request(
                "POST",
                f"{self.API_BASE_URL}/{self.API_VERSION}/proposals",
                json=payload,
            )

            proposal_data = response.get("proposal", {})
            return PlacedBid(
                marketplace_name="upwork",
                bid_id=str(proposal_data.get("id")),
                job_id=proposal.job_id,
                status=BidStatus.SUBMITTED,
                amount=proposal.amount,
                pricing_model=proposal.pricing_model,
                submitted_at=datetime.utcnow(),
                url=proposal_data.get("url"),
                metadata=proposal_data,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitError("Upwork rate limit exceeded")
            raise MarketplaceError(f"Failed to place Upwork proposal: {str(e)}")

    async def get_bid_status(self, bid_id: str) -> BidStatusUpdate:
        """
        Get status of a placed proposal.

        Args:
            bid_id: Proposal ID

        Returns:
            Bid status update

        Raises:
            NotFoundError: If proposal not found
            MarketplaceError: If request fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "GET",
                f"{self.API_BASE_URL}/{self.API_VERSION}/proposals/{bid_id}",
            )

            proposal_data = response.get("proposal", {})
            status_map = {
                "pending": BidStatus.PENDING,
                "pending_review": BidStatus.PENDING,
                "accepted": BidStatus.ACCEPTED,
                "rejected": BidStatus.REJECTED,
                "withdrawn": BidStatus.WITHDRAWN,
                "expired": BidStatus.EXPIRED,
            }

            return BidStatusUpdate(
                marketplace_name="upwork",
                bid_id=bid_id,
                job_id=proposal_data.get("job_id", ""),
                status=status_map.get(
                    proposal_data.get("status", "").lower(), BidStatus.PENDING
                ),
                last_updated=self._parse_datetime(proposal_data.get("updated_at")),
                metadata=proposal_data,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Proposal {bid_id} not found")
            raise MarketplaceError(f"Failed to get proposal status: {str(e)}")

    async def withdraw_bid(self, bid_id: str) -> BidStatusUpdate:
        """
        Withdraw a placed proposal.

        Args:
            bid_id: Proposal ID

        Returns:
            Updated bid status

        Raises:
            NotFoundError: If proposal not found
            MarketplaceError: If withdrawal fails
        """
        if not self._authenticated:
            raise MarketplaceError("Not authenticated")

        try:
            response = await self._request(
                "POST",
                f"{self.API_BASE_URL}/{self.API_VERSION}/proposals/{bid_id}/withdraw",
            )

            proposal_data = response.get("proposal", {})
            return BidStatusUpdate(
                marketplace_name="upwork",
                bid_id=bid_id,
                job_id=proposal_data.get("job_id", ""),
                status=BidStatus.WITHDRAWN,
                last_updated=datetime.utcnow(),
                metadata=proposal_data,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Proposal {bid_id} not found")
            raise MarketplaceError(f"Failed to withdraw proposal: {str(e)}")

    async def check_inbox(self) -> List[InboxMessage]:
        """
        Check for new messages in Upwork inbox.

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
                f"{self.API_BASE_URL}/{self.API_VERSION}/messages",
                params={"filter": "unread"},
            )

            messages = []
            for msg in response.get("messages", []):
                message = InboxMessage(
                    message_id=str(msg.get("id")),
                    sender_name=msg.get("sender", {}).get("name", ""),
                    subject=msg.get("subject", ""),
                    body=msg.get("body", ""),
                    created_at=self._parse_datetime(msg.get("created_at")),
                    is_read=msg.get("is_read", False),
                    url=msg.get("url"),
                    metadata=msg,
                )
                messages.append(message)

            logger.info(f"Retrieved {len(messages)} unread Upwork messages")
            return messages

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(f"Failed to check Upwork inbox: {str(e)}")

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
        Sync portfolio with Upwork.

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
            for item in portfolio_items:
                payload = {
                    "title": item.get("title"),
                    "description": item.get("description"),
                    "url": item.get("url"),
                    "skills": item.get("skills", []),
                }

                await self._request(
                    "POST",
                    f"{self.API_BASE_URL}/{self.API_VERSION}/user/portfolio",
                    json=payload,
                )

            logger.info(f"Synced {len(portfolio_items)} portfolio items to Upwork")
            return True

        except httpx.HTTPStatusError as e:
            raise MarketplaceError(f"Failed to sync Upwork portfolio: {str(e)}")

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
        """Get OAuth headers for Upwork API."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _get_bidding_tier_id(amount: float) -> str:
        """
        Get bidding tier ID based on amount.
        Upwork has different tier IDs for different price ranges.
        """
        if amount < 500:
            return "0"  # Tier 1
        elif amount < 1000:
            return "1"  # Tier 2
        else:
            return "2"  # Tier 3+

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from Upwork API."""
        if not dt_str:
            return None
        try:
            # Handle various formats
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
