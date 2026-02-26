"""
Marketplace Discovery Module

This module handles autonomous discovery and evaluation of freelance marketplaces.
It searches for new marketplaces, tracks their performance, and maintains a curated
list of URLs to scan. The system learns which marketplaces yield the best opportunities
and automatically updates its scanning strategy to maximize profitability.

Features:
- Web search-based marketplace discovery
- Marketplace evaluation using Playwright and LLM
- Performance tracking and scoring
- Priority-based marketplace ranking
- Autonomous discovery loop with self-improvement
"""

import os
import json
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field
from datetime import datetime

from dotenv import load_dotenv

# Import logger
from src.utils.logger import get_logger

# Try to import web search capability
try:
    from src.llm_service import LLMService

    LLM_SERVICE_AVAILABLE = True
except ImportError:
    LLM_SERVICE_AVAILABLE = False

# Try to import Playwright
try:
    from playwright.async_api import async_playwright
    from .browser_pool import get_browser_pool
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Load environment variables
load_dotenv()

# Initialize logger after all imports
logger = get_logger(__name__)

if not LLM_SERVICE_AVAILABLE:
    logger.warning("LLMService not available for marketplace discovery")

if not PLAYWRIGHT_AVAILABLE:
    logger.warning("Playwright not available for marketplace evaluation")


# =============================================================================
# CONFIGURATION
# =============================================================================

MARKETPLACES_FILE = os.environ.get(
    "MARKETPLACES_FILE",
    os.path.join(os.path.dirname(__file__), "../../data/marketplaces.json"),
)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DiscoveredMarketplace:
    """A discovered freelance marketplace or job board."""

    name: str
    url: str
    category: str  # "freelance", "remote", "gig", "enterprise"
    discovered_at: datetime
    last_scanned: Optional[datetime] = None
    scan_count: int = 0
    jobs_found: int = 0
    bids_placed: int = 0
    bids_won: int = 0
    total_revenue: float = 0.0
    success_rate: float = 0.0  # wins / bids_placed
    is_active: bool = True
    priority_score: float = 0.0  # Computed: success_rate * total_revenue
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["discovered_at"] = (
            self.discovered_at.isoformat()
            if isinstance(self.discovered_at, datetime)
            else self.discovered_at
        )
        data["last_scanned"] = (
            self.last_scanned.isoformat()
            if isinstance(self.last_scanned, datetime)
            else self.last_scanned
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveredMarketplace":
        """Create instance from dictionary."""
        # Parse datetime fields
        if isinstance(data.get("discovered_at"), str):
            data["discovered_at"] = datetime.fromisoformat(data["discovered_at"])
        if isinstance(data.get("last_scanned"), str):
            data["last_scanned"] = datetime.fromisoformat(data["last_scanned"])

        return cls(**data)


@dataclass
class DiscoveryConfig:
    """Configuration for marketplace discovery."""

    search_keywords: List[str]
    min_success_rate: float
    max_marketplaces: int
    discovery_interval_hours: int
    rescore_interval_hours: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveryConfig":
        """Create instance from dictionary."""
        return cls(**data)


# =============================================================================
# MARKETPLACE DISCOVERY CLASS
# =============================================================================


class MarketplaceDiscovery:
    """
    Main orchestrator for marketplace discovery and evaluation.

    Responsibilities:
    - Search for new marketplaces using web search
    - Evaluate marketplace quality using Playwright
    - Track marketplace performance metrics
    - Calculate priority scores based on profitability
    - Maintain curated list of active marketplaces
    """

    def __init__(self, config_file: str = MARKETPLACES_FILE):
        """
        Initialize the marketplace discovery system.

        Args:
            config_file: Path to the marketplaces.json configuration file
        """
        self.config_file = config_file
        self.marketplaces: List[DiscoveredMarketplace] = []
        self.config: Optional[DiscoveryConfig] = None

        # Load existing configuration
        self._load_marketplaces()

    def _load_marketplaces(self) -> None:
        """Load marketplaces from JSON file."""
        if not os.path.exists(self.config_file):
            logger.warning(f"Marketplaces file not found: {self.config_file}")
            self.config = DiscoveryConfig(
                search_keywords=[],
                min_success_rate=0.1,
                max_marketplaces=20,
                discovery_interval_hours=168,
                rescore_interval_hours=24,
            )
            return

        try:
            with open(self.config_file, "r") as f:
                data = json.load(f)

            # Load config
            if "config" in data:
                self.config = DiscoveryConfig.from_dict(data["config"])

            # Load marketplaces
            if "marketplaces" in data:
                self.marketplaces = [
                    DiscoveredMarketplace.from_dict(m) for m in data["marketplaces"]
                ]

            logger.info(f"Loaded {len(self.marketplaces)} marketplaces from config")

        except Exception as e:
            logger.error(f"Failed to load marketplaces: {e}")
            self.config = DiscoveryConfig(
                search_keywords=[],
                min_success_rate=0.1,
                max_marketplaces=20,
                discovery_interval_hours=168,
                rescore_interval_hours=24,
            )

    def save_marketplaces(self) -> None:
        """Save marketplace list and configuration to JSON file."""
        if not self.config:
            logger.warning("No configuration available, cannot save marketplaces")
            return

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

        data = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "config": self.config.to_dict(),
            "marketplaces": [m.to_dict() for m in self.marketplaces],
        }

        try:
            with open(self.config_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.marketplaces)} marketplaces to config")
        except Exception as e:
            logger.error(f"Failed to save marketplaces: {e}")

    def get_active_marketplaces(self) -> List[DiscoveredMarketplace]:
        """
        Get active marketplaces sorted by priority score.

        Returns:
            List of active marketplaces sorted by priority (highest first)
        """
        active = [m for m in self.marketplaces if m.is_active]
        return sorted(active, key=lambda m: m.priority_score, reverse=True)

    def get_marketplace_by_url(self, url: str) -> Optional[DiscoveredMarketplace]:
        """Get a marketplace by its URL."""
        for m in self.marketplaces:
            if m.url == url:
                return m
        return None

    def add_marketplace(
        self,
        name: str,
        url: str,
        category: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DiscoveredMarketplace:
        """
        Add a new marketplace to the list.

        Args:
            name: Marketplace name
            url: Marketplace URL
            category: Category (freelance, remote, gig, enterprise)
            metadata: Additional metadata

        Returns:
            The added DiscoveredMarketplace
        """
        # Check if already exists
        if self.get_marketplace_by_url(url):
            logger.warning(f"Marketplace already exists: {url}")
            return self.get_marketplace_by_url(url)

        marketplace = DiscoveredMarketplace(
            name=name,
            url=url,
            category=category,
            discovered_at=datetime.now(),
            metadata=metadata or {},
        )

        self.marketplaces.append(marketplace)
        logger.info(f"Added new marketplace: {name} ({url})")

        return marketplace

    def update_marketplace_stats(
        self,
        url: str,
        jobs_found: int = 0,
        bid_placed: bool = False,
        bid_won: bool = False,
        revenue: float = 0.0,
    ) -> None:
        """
        Update statistics for a marketplace after scanning/bidding.

        Args:
            url: Marketplace URL
            jobs_found: Number of jobs found in this scan
            bid_placed: Whether a bid was placed
            bid_won: Whether a bid was won
            revenue: Revenue from a won bid
        """
        marketplace = self.get_marketplace_by_url(url)
        if not marketplace:
            logger.warning(f"Marketplace not found: {url}")
            return

        marketplace.last_scanned = datetime.now()
        marketplace.scan_count += 1
        marketplace.jobs_found += jobs_found

        if bid_placed:
            marketplace.bids_placed += 1

        if bid_won:
            marketplace.bids_won += 1
            marketplace.total_revenue += revenue

        # Recalculate success rate
        if marketplace.bids_placed > 0:
            marketplace.success_rate = marketplace.bids_won / marketplace.bids_placed

        # Recalculate priority score
        self._calculate_priority_score(marketplace)

    def _calculate_priority_score(self, marketplace: DiscoveredMarketplace) -> None:
        """
        Calculate the priority score for a marketplace.

        Priority = (success_rate * 0.5) + (revenue / max_revenue * 0.5)
        with activity factor (scan_count)

        Args:
            marketplace: The marketplace to score
        """
        if not self.marketplaces:
            marketplace.priority_score = 0.0
            return

        # Get max revenue for normalization
        max_revenue = max((m.total_revenue for m in self.marketplaces), default=1.0)
        if max_revenue == 0:
            max_revenue = 1.0

        # Base score: weighted combination of success rate and revenue
        success_component = marketplace.success_rate * 0.5
        revenue_component = (marketplace.total_revenue / max_revenue) * 0.5
        base_score = success_component + revenue_component

        # Activity factor: boost if recently scanned
        activity_factor = 1.0
        if marketplace.last_scanned:
            hours_since_scan = (
                datetime.now() - marketplace.last_scanned
            ).total_seconds() / 3600
            if hours_since_scan < 24:
                activity_factor = 1.5  # Boost recent scans
            elif hours_since_scan > 168:
                activity_factor = 0.7  # Penalize stale scans

        # Final score (normalized to 0-100)
        marketplace.priority_score = base_score * activity_factor * 100

    def rescore_all_marketplaces(self) -> None:
        """Recalculate priority scores for all marketplaces."""
        for marketplace in self.marketplaces:
            self._calculate_priority_score(marketplace)

        logger.info("Rescored all marketplaces")

    async def search_marketplaces(
        self, keywords: Optional[List[str]] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for new marketplaces using web search.

        Args:
            keywords: Search keywords (uses config if not provided)
            limit: Maximum number of marketplaces to discover per keyword

        Returns:
            List of discovered marketplace dictionaries
        """
        if not LLM_SERVICE_AVAILABLE:
            logger.warning("LLMService not available for marketplace search")
            return []

        if not keywords and self.config:
            keywords = self.config.search_keywords

        if not keywords:
            logger.warning("No keywords available for marketplace search")
            return []

        discovered = []

        try:
            llm = LLMService.with_local(model="llama3.2")

            for keyword in keywords:
                logger.info(f"Searching for marketplaces: {keyword}")

                # Create a search prompt
                prompt = f"""
                Find 3-5 popular freelance marketplaces and job boards related to: "{keyword}"
                
                For each marketplace, provide:
                1. Name
                2. URL
                3. Category (freelance/remote/gig/enterprise)
                4. Brief description
                
                Format as JSON list with keys: name, url, category, description
                """

                try:
                    # Use LLM to search (in practice, this would use actual web search)
                    # For now, return structured format based on LLM knowledge
                    response = llm.invoke([{"role": "user", "content": prompt}])

                    # Try to parse JSON response
                    # This is a simplified implementation
                    logger.debug(f"LLM response for '{keyword}': {response[:100]}")

                except Exception as e:
                    logger.warning(f"Failed to search with LLM: {e}")

        except Exception as e:
            logger.error(f"Marketplace search failed: {e}")

        return discovered

    async def evaluate_marketplace(self, url: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Evaluate a marketplace by visiting it with Playwright.

        Uses async context managers for proper resource cleanup.

        Args:
            url: Marketplace URL to evaluate
            timeout: Page load timeout in seconds

        Returns:
            Dictionary with evaluation metrics
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available for marketplace evaluation")
            return {
                "url": url,
                "accessible": False,
                "job_count": 0,
                "avg_budget": 0,
                "error": "Playwright not available",
            }

        playwright = None
        browser = None
        page = None

        try:
            # Use BrowserPool instead of launching new browser (Issue #4)
            pool = get_browser_pool()
            # Ensure pool is started
            try:
                await pool.start()
            except Exception:
                pass
                
            browser = await pool.acquire_browser()

            try:
                # Create page
                page = await browser.new_page()

                    try:
                        # Navigate to marketplace with timeout
                        response = await page.goto(
                            url, wait_until="domcontentloaded", timeout=timeout * 1000
                        )

                        if not response or response.status >= 400:
                            return {
                                "url": url,
                                "accessible": False,
                                "job_count": 0,
                                "avg_budget": 0,
                                "status_code": response.status if response else None,
                            }

                        # Try to count job listings
                        job_elements = await page.query_selector_all(
                            [
                                ".job-listing",
                                ".job-card",
                                ".project-card",
                                "[data-testid='job-post']",
                                ".listing-item",
                                "article.job",
                            ]
                        )

                        job_count = len(job_elements) if job_elements else 0

                        return {
                            "url": url,
                            "accessible": True,
                            "job_count": job_count,
                            "avg_budget": 0,  # Would be calculated from actual job data
                            "evaluated_at": datetime.now().isoformat(),
                        }

                    except asyncio.TimeoutError:
                        logger.warning(f"Marketplace evaluation timeout for {url}")
                        return {
                            "url": url,
                            "accessible": False,
                            "job_count": 0,
                            "avg_budget": 0,
                            "error": "Page load timeout",
                        }

                    except Exception as e:
                        logger.warning(f"Failed to evaluate marketplace {url}: {e}")
                        return {
                            "url": url,
                            "accessible": False,
                            "job_count": 0,
                            "avg_budget": 0,
                            "error": str(e),
                        }

                    finally:
                        # Explicitly close page
                        try:
                            await page.close()
                        except Exception as e:
                            logger.warning(f"Error closing page for {url}: {e}")

                finally:
                    # Release browser back to pool instead of closing (Issue #4)
                    if browser:
                        pool = get_browser_pool()
                        await pool.release_browser(browser)

        except Exception as e:
            logger.error(f"Marketplace evaluation error: {e}")
            return {
                "url": url,
                "accessible": False,
                "job_count": 0,
                "avg_budget": 0,
                "error": str(e),
            }

    async def discover_and_update(self) -> Dict[str, Any]:
        """
        Main orchestration: discovers new marketplaces and updates existing stats.

        Returns:
            Dictionary with discovery summary
        """
        summary = {
            "success": False,
            "discovered_new": 0,
            "total_active": 0,
            "rescored": 0,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # Search for new marketplaces
            if self.config:
                new_marketplaces = await self.search_marketplaces(
                    keywords=self.config.search_keywords, limit=3
                )

                for marketplace_data in new_marketplaces:
                    existing = self.get_marketplace_by_url(marketplace_data.get("url"))
                    if not existing:
                        self.add_marketplace(
                            name=marketplace_data.get("name", "Unknown"),
                            url=marketplace_data.get("url", ""),
                            category=marketplace_data.get("category", "freelance"),
                            metadata=marketplace_data,
                        )
                        summary["discovered_new"] += 1

            # Rescore all marketplaces
            self.rescore_all_marketplaces()
            summary["rescored"] = len(self.marketplaces)

            # Save updated configuration
            self.save_marketplaces()

            summary["total_active"] = len(self.get_active_marketplaces())
            summary["success"] = True

            logger.info(f"Discovery update complete: {summary}")

        except Exception as e:
            logger.error(f"Discovery and update failed: {e}")
            summary["error"] = str(e)

        return summary


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def load_marketplaces(
    config_file: str = MARKETPLACES_FILE,
) -> List[DiscoveredMarketplace]:
    """
    Load marketplace list from JSON file.

    Args:
        config_file: Path to the marketplaces.json configuration file

    Returns:
        List of discovered marketplaces
    """
    discovery = MarketplaceDiscovery(config_file=config_file)
    return discovery.get_active_marketplaces()


def save_marketplaces_config(
    marketplaces: List[DiscoveredMarketplace], config_file: str = MARKETPLACES_FILE
) -> None:
    """
    Save marketplace list to JSON file.

    Args:
        marketplaces: List of marketplaces to save
        config_file: Path to the marketplaces.json configuration file
    """
    discovery = MarketplaceDiscovery(config_file=config_file)
    discovery.marketplaces = marketplaces
    discovery.save_marketplaces()


async def discover_new_marketplaces(
    config_file: str = MARKETPLACES_FILE,
) -> Dict[str, Any]:
    """
    Discover new marketplaces and update the configuration.

    Args:
        config_file: Path to the marketplaces.json configuration file

    Returns:
        Dictionary with discovery summary
    """
    discovery = MarketplaceDiscovery(config_file=config_file)
    return await discovery.discover_and_update()


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":

    async def main():
        """Main entry point for testing."""
        print("=" * 60)
        print("Marketplace Discovery - Test Run")
        print("=" * 60)

        # Initialize discovery
        discovery = MarketplaceDiscovery()

        print("\nCurrent Configuration:")
        if discovery.config:
            print(f"  Keywords: {discovery.config.search_keywords}")
            print(f"  Min Success Rate: {discovery.config.min_success_rate}")
            print(f"  Max Marketplaces: {discovery.config.max_marketplaces}")

        print(f"\nLoaded Marketplaces: {len(discovery.marketplaces)}")

        # Show active marketplaces
        active = discovery.get_active_marketplaces()
        print(f"\nActive Marketplaces ({len(active)}):")
        for mp in active:
            print(f"  - {mp.name}: {mp.url}")
            print(f"    Priority: {mp.priority_score:.2f}")
            print(f"    Success Rate: {mp.success_rate:.2%}")
            print(f"    Total Revenue: ${mp.total_revenue:.2f}")

        # Try discovery (if configured)
        if discovery.config and discovery.config.search_keywords:
            print("\nAttempting marketplace discovery...")
            summary = await discovery.discover_and_update()
            print(f"Discovery Summary: {summary}")

    # Run the main function
    asyncio.run(main())
