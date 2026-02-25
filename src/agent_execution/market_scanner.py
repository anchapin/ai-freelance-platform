"""
Market Scanner Module

This module provides functionality to scan freelance marketplaces for potential tasks.
It uses Playwright to navigate to marketplace URLs and evaluates job postings
using a local LLM (Ollama) to determine suitability and optimal bid amounts.

Features:
- Playwright-based web scraping of freelance marketplace pages
- LLM-powered evaluation of job postings (suitability, bid amount, reasoning)
- Graceful error handling for 24/7 operation
- Configurable marketplace URL from environment variables
"""

import os
import json
import asyncio
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv

# Import logger
from src.utils.logger import get_logger

# Import ConfigManager for centralized configuration
from src.config import get_config

# Import LLM service for local inference
try:
    from src.llm_service import LLMService

    LLM_SERVICE_AVAILABLE = True
except ImportError:
    LLM_SERVICE_AVAILABLE = False

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Load environment variables after imports
load_dotenv()

# Initialize logger after all imports
logger = get_logger(__name__)

if not LLM_SERVICE_AVAILABLE:
    logger.warning(
        "LLMService not available, market scanner will use fallback evaluation"
    )

if not PLAYWRIGHT_AVAILABLE:
    logger.warning("Playwright not available, market scanner will use HTTP-only mode")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Load configuration from ConfigManager (centralized)
def _get_config():
    """Lazy load configuration to avoid circular imports."""
    try:
        return get_config()
    except Exception:
        # Fallback to environment variables if ConfigManager fails
        return None

# Marketplace URLs configuration
MARKETPLACES_FILE = os.environ.get(
    "MARKETPLACES_FILE",
    os.path.join(os.path.dirname(__file__), "../../data/marketplaces.json"),
)
DEFAULT_MARKETPLACE_URL = "https://example.com/freelance-jobs"

# Evaluation settings
EVALUATION_MODEL = os.environ.get("MARKET_SCAN_MODEL", "llama3.2")

# Load bid amounts from ConfigManager or use defaults
def get_max_bid_amount() -> int:
    """Get MAX_BID_AMOUNT from ConfigManager."""
    config = _get_config()
    if config:
        return config.MAX_BID_AMOUNT
    return int(os.environ.get("MAX_BID_AMOUNT", "500"))

def get_min_bid_amount() -> int:
    """Get MIN_BID_AMOUNT from ConfigManager."""
    config = _get_config()
    if config:
        return config.MIN_BID_AMOUNT
    return int(os.environ.get("MIN_BID_AMOUNT", "10"))

def get_page_load_timeout() -> int:
    """Get PAGE_LOAD_TIMEOUT from ConfigManager."""
    config = _get_config()
    if config:
        return config.PAGE_LOAD_TIMEOUT
    return int(os.environ.get("MARKET_SCAN_PAGE_TIMEOUT", "30"))

def get_scan_interval() -> int:
    """Get SCAN_INTERVAL from ConfigManager."""
    config = _get_config()
    if config:
        return config.SCAN_INTERVAL
    return int(os.environ.get("MARKET_SCAN_INTERVAL", "300"))

# Legacy module-level constants for backward compatibility
MAX_BID_AMOUNT = get_max_bid_amount()
MIN_BID_AMOUNT = get_min_bid_amount()
PAGE_LOAD_TIMEOUT = get_page_load_timeout()
SCAN_INTERVAL = get_scan_interval()


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class JobPosting:
    """Represents a job posting from the marketplace."""

    title: str
    description: str
    budget: Optional[str] = None
    skills: List[str] = None
    url: Optional[str] = None
    posted_date: Optional[str] = None
    client_rating: Optional[float] = None
    client_spend: Optional[str] = None

    def __post_init__(self):
        if self.skills is None:
            self.skills = []


@dataclass
class EvaluationResult:
    """Result of evaluating a job posting."""

    is_suitable: bool
    bid_amount: int
    reasoning: str
    task_id: Optional[str] = None
    confidence: Optional[float] = None
    evaluated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.evaluated_at is None:
            self.evaluated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_suitable": self.is_suitable,
            "bid_amount": self.bid_amount,
            "reasoning": self.reasoning,
            "task_id": self.task_id,
            "confidence": self.confidence,
            "evaluated_at": self.evaluated_at.isoformat()
            if self.evaluated_at
            else None,
        }


# =============================================================================
# MARKET SCANNER CLASS
# =============================================================================


class MarketScanner:
    """
    Scans freelance marketplaces for potential tasks using Playwright.

    This scanner:
    1. Loads marketplace URLs from configuration (data/marketplaces.json)
    2. Extracts job postings from the page
    3. Evaluates each posting using local LLM (Ollama)
    4. Returns evaluation results with suitability, bid amount, and reasoning

    Supports scanning multiple marketplaces with deduplication of jobs.
    """

    def __init__(
        self,
        marketplace_url: Optional[str] = None,
        headless: bool = True,
        timeout: int = PAGE_LOAD_TIMEOUT,
    ):
        """
        Initialize the MarketScanner.

        Args:
            marketplace_url: URL of the freelance marketplace to scan (overrides config)
            headless: Whether to run Playwright in headless mode
            timeout: Page load timeout in seconds
        """
        self.marketplace_urls: List[str] = []
        self.marketplace_url = marketplace_url  # Single URL override

        # Load marketplace URLs from config if no override provided
        if not marketplace_url:
            self._load_marketplaces_from_config()

        self.headless = headless
        self.timeout = timeout * 1000  # Convert to milliseconds for Playwright

        self.playwright = None
        self.browser = None
        self.page = None

        # Initialize LLM service for evaluation
        self.llm = None
        if LLM_SERVICE_AVAILABLE:
            try:
                self.llm = LLMService.with_local(model=EVALUATION_MODEL)
                logger.info(
                    f"MarketScanner initialized with LLM model: {EVALUATION_MODEL}"
                )
            except Exception as e:
                logger.warning(f"Failed to initialize LLM service: {e}")

    def _load_marketplaces_from_config(self) -> None:
        """Load active marketplace URLs from the marketplaces.json config file."""
        try:
            if not os.path.exists(MARKETPLACES_FILE):
                logger.warning(
                    f"Marketplaces config file not found: {MARKETPLACES_FILE}"
                )
                self.marketplace_urls = [DEFAULT_MARKETPLACE_URL]
                return

            with open(MARKETPLACES_FILE, "r") as f:
                data = json.load(f)

            # Extract active marketplace URLs
            marketplaces = data.get("marketplaces", [])
            self.marketplace_urls = [
                m["url"]
                for m in marketplaces
                if m.get("is_active", True) and m.get("url")
            ]

            if not self.marketplace_urls:
                logger.warning("No active marketplaces found in config, using default")
                self.marketplace_urls = [DEFAULT_MARKETPLACE_URL]

            logger.info(
                f"Loaded {len(self.marketplace_urls)} marketplace URLs from config"
            )

        except Exception as e:
            logger.error(f"Failed to load marketplaces from config: {e}")
            self.marketplace_urls = [DEFAULT_MARKETPLACE_URL]

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - always cleanup even on exception."""
        await self.stop()
        return False  # Don't suppress exceptions

    async def start(self):
        """
        Start the Playwright browser.

        Must be called before scanning if not using context manager.
        Creates a persistent browser instance for the scanner session.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error(
                "Playwright is not available. Install with: pip install playwright && playwright install chromium"
            )
            raise RuntimeError("Playwright is not installed")

        try:
            # Clean up any existing resources first
            await self.stop()

            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=self.headless)

            # Note: page will be created per operation in fetch_job_postings
            # to ensure proper resource cleanup after each operation

            logger.info("MarketScanner browser started successfully")
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            await self.stop()  # Cleanup on failure
            raise

    async def stop(self):
        """
        Stop the Playwright browser and cleanup all resources.

        Ensures proper cleanup order:
        1. Close any open pages
        2. Close browser
        3. Stop playwright
        """
        try:
            if self.page:
                try:
                    await self.page.close()
                except Exception as e:
                    logger.warning(f"Error closing page: {e}")

            if self.browser:
                try:
                    await self.browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")

            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping playwright: {e}")

            logger.info("MarketScanner browser stopped and resources cleaned up")
        except Exception as e:
            logger.warning(f"Error stopping browser: {e}")
        finally:
            self.page = None
            self.browser = None
            self.playwright = None

    async def fetch_job_postings(
        self, max_posts: int = 10, marketplace_url: Optional[str] = None
    ) -> List[JobPosting]:
        """
        Fetch job postings from the marketplace.

        Creates and properly closes a page for each fetch operation to prevent leaks.

        Args:
            max_posts: Maximum number of postings to fetch
            marketplace_url: Optional marketplace URL (uses default if not provided)

        Returns:
            List of JobPosting objects
        """
        if not self.browser:
            await self.start()

        # Use provided URL or fall back to single URL override or first configured URL
        url = (
            marketplace_url
            or self.marketplace_url
            or (
                self.marketplace_urls[0]
                if self.marketplace_urls
                else DEFAULT_MARKETPLACE_URL
            )
        )

        job_postings = []
        page = None

        try:
            # Create a fresh page for this operation
            page = await self.browser.new_page()
            await page.set_default_timeout(self.timeout)

            logger.info(f"Navigating to marketplace: {url}")

            # Navigate to the marketplace
            response = await page.goto(url, wait_until="domcontentloaded")

            if response and response.status >= 400:
                logger.warning(f"Marketplace returned status {response.status}")
                # Return mock data for testing when marketplace is unavailable
                return self._get_mock_job_postings(max_posts)

            # Wait for job listings to load
            await page.wait_for_load_state("networkidle", timeout=self.timeout)

            # Try to extract job postings (common selectors)
            # This is a generic approach - may need adjustment for specific marketplaces
            job_elements = await page.query_selector_all(
                [
                    ".job-listing",
                    ".job-card",
                    ".freelancer-project",
                    ".project-card",
                    "[data-testid='job-post']",
                    ".listing-item",
                    "article.job",
                    ".job-post",
                ]
            )

            if not job_elements:
                logger.warning(
                    "No job postings found with common selectors, using fallback extraction"
                )
                return self._get_mock_job_postings(max_posts)

            # Extract data from each job element
            for i, element in enumerate(job_elements[:max_posts]):
                try:
                    posting = await self._extract_job_posting(element, i)
                    if posting:
                        job_postings.append(posting)
                except Exception as e:
                    logger.warning(f"Failed to extract job posting {i}: {e}")
                    continue

            logger.info(f"Extracted {len(job_postings)} job postings")

        except Exception as e:
            logger.error(f"Error fetching job postings: {e}")
            # Return mock data for graceful degradation
            return self._get_mock_job_postings(max_posts)

        finally:
            # Always close the page to prevent resource leaks
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.warning(f"Error closing page during cleanup: {e}")

        return job_postings

    async def _extract_job_posting(self, element, index: int) -> Optional[JobPosting]:
        """
        Extract job posting data from a page element.

        Args:
            element: Playwright element handle
            index: Index of the element

        Returns:
            JobPosting object or None if extraction fails
        """
        try:
            # Try common selectors for job data
            title_elem = await element.query_selector(
                ["h2", "h3", ".title", ".job-title", "[data-testid='title']"]
            )
            title = await title_elem.inner_text() if title_elem else f"Job {index + 1}"

            desc_elem = await element.query_selector(
                [".description", ".job-description", ".snippet", "p"]
            )
            description = await desc_elem.inner_text() if desc_elem else ""

            # Try to get budget
            budget_elem = await element.query_selector(
                [".budget", ".price", ".amount", ".job-price", "[data-testid='budget']"]
            )
            budget = await budget_elem.inner_text() if budget_elem else None

            # Try to get skills
            skill_elems = await element.query_selector_all(
                [".skills span", ".skill-tag", ".tag", "span[data-testid='skill']"]
            )
            skills = []
            for skill in skill_elems:
                skill_text = await skill.inner_text()
                if skill_text:
                    skills.append(skill_text.strip())

            # Try to get URL
            link_elem = await element.query_selector("a")
            url = None
            if link_elem:
                url = await link_elem.get_attribute("href")

            return JobPosting(
                title=title.strip(),
                description=description.strip()[:500],  # Limit description length
                budget=budget,
                skills=skills,
                url=url,
            )

        except Exception as e:
            logger.warning(f"Failed to extract job posting: {e}")
            return None

    def _get_mock_job_postings(self, max_posts: int) -> List[JobPosting]:
        """
        Get mock job postings for testing or when marketplace is unavailable.

        Args:
            max_posts: Maximum number of mock postings

        Returns:
            List of mock JobPosting objects
        """
        mock_postings = [
            JobPosting(
                title="Python Data Analysis Script",
                description="Need a Python developer to create a data analysis script that processes CSV files and generates visualizations. Must include pandas and matplotlib.",
                budget="$100-200",
                skills=["Python", "pandas", "matplotlib", "data analysis"],
            ),
            JobPosting(
                title="React Dashboard Development",
                description="Looking for an experienced React developer to build a dashboard with charts, tables, and real-time data updates. Experience with D3.js preferred.",
                budget="$500-1000",
                skills=["React", "JavaScript", "D3.js", "CSS"],
            ),
            JobPosting(
                title="Excel Spreadsheet Automation",
                description="Need VBA macros created to automate repetitive spreadsheet tasks. Should include data validation and automated report generation.",
                budget="$50-150",
                skills=["Excel", "VBA", "Microsoft Office"],
            ),
            JobPosting(
                title="Legal Document Template",
                description="Create a professional legal contract template for NDA agreements. Must comply with US law standards.",
                budget="$200-300",
                skills=["Legal", "Document Creation", "Contract Law"],
            ),
            JobPosting(
                title="Web Scraping Bot",
                description="Build a web scraping bot to collect product prices from e-commerce sites. Must handle anti-scraping measures.",
                budget="$150-400",
                skills=["Python", "BeautifulSoup", "Selenium", "Web Scraping"],
            ),
        ]

        return mock_postings[:max_posts]

    async def evaluate_post(self, title: str, description: str) -> EvaluationResult:
        """
        Evaluate a job posting for suitability using LLM.

        Args:
            title: Job title
            description: Job description

        Returns:
            EvaluationResult with is_suitable, bid_amount, and reasoning
        """
        # Generate a unique task ID
        task_id = (
            f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(title) % 10000}"
        )

        # If LLM is available, use it for evaluation
        if self.llm and LLM_SERVICE_AVAILABLE:
            return await self._evaluate_with_llm(title, description, task_id)

        # Fallback to rule-based evaluation
        return self._evaluate_fallback(title, description, task_id)

    async def _evaluate_with_llm(
        self, title: str, description: str, task_id: str
    ) -> EvaluationResult:
        """
        Evaluate job posting using local LLM (Ollama).

        Args:
            title: Job title
            description: Job description
            task_id: Unique task identifier

        Returns:
            EvaluationResult
        """
        system_prompt = """You are an expert freelance job evaluator. Your task is to evaluate job postings
for suitability and determine an optimal bid amount.

Evaluate the job based on:
1. Whether it matches typical ArbitrageAI capabilities
2. Complexity and scope of work
3. Budget appropriateness
4. Required skills alignment

Return ONLY valid JSON with these exact keys:
{
    "is_suitable": true or false,
    "bid_amount": integer (your recommended bid in dollars),
    "reasoning": "Brief explanation of your evaluation (2-3 sentences)",
    "confidence": float between 0 and 1
}

Guidelines for bid amount:
- Low complexity tasks (simple data entry, basic formatting): $10-50
- Medium complexity (standard coding tasks, document creation): $50-150
- High complexity (complex development, specialized work): $150-400
- Very high complexity (full applications, complex systems): $400+

Only mark as suitable if the job is something an AI can reasonably handle."""

        prompt = f"""Job Title: {title}
Job Description: {description}

Evaluate this job posting and return JSON."""

        try:
            # Use the LLM service
            result = self.llm.complete(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=500,
            )

            # Parse the response
            response_content = result.get("content", "{}")

            # Extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", response_content)
            if json_match:
                eval_data = eval(json_match.group(0))

                # Validate and clamp bid amount
                bid_amount = eval_data.get("bid_amount", 50)
                bid_amount = max(MIN_BID_AMOUNT, min(MAX_BID_AMOUNT, bid_amount))

                return EvaluationResult(
                    is_suitable=eval_data.get("is_suitable", False),
                    bid_amount=bid_amount,
                    reasoning=eval_data.get("reasoning", "Evaluation completed"),
                    task_id=task_id,
                    confidence=eval_data.get("confidence", 0.5),
                )

            # If JSON parsing fails, use fallback
            logger.warning("Failed to parse LLM response, using fallback evaluation")
            return self._evaluate_fallback(title, description, task_id)

        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return self._evaluate_fallback(title, description, task_id)

    def _evaluate_fallback(
        self, title: str, description: str, task_id: str
    ) -> EvaluationResult:
        """
        Fallback rule-based evaluation when LLM is unavailable.

        Args:
            title: Job title
            description: Job description
            task_id: Unique task identifier

        Returns:
            EvaluationResult
        """
        title_lower = title.lower()
        desc_lower = description.lower()

        # Keywords that indicate suitable tasks
        suitable_keywords = [
            "python",
            "data",
            "analysis",
            "excel",
            "spreadsheet",
            "chart",
            "visualization",
            "report",
            "document",
            "script",
            "automation",
            "dashboard",
            "table",
            "csv",
            "parsing",
            "template",
            "format",
        ]

        # Keywords that indicate unsuitable tasks
        unsuitable_keywords = [
            "physical",
            "in-person",
            "on-site",
            "video",
            "call",
            "meeting",
            "voice",
            "audio",
            "real-time",
            "live",
            "3d modeling",
            "mobile app",
        ]

        # Check for unsuitable keywords first
        for keyword in unsuitable_keywords:
            if keyword in title_lower or keyword in desc_lower:
                return EvaluationResult(
                    is_suitable=False,
                    bid_amount=50,
                    reasoning=f"Job contains '{keyword}' which requires human involvement.",
                    task_id=task_id,
                    confidence=0.9,
                )

        # Check for suitable keywords
        suitable_count = sum(
            1 for kw in suitable_keywords if kw in title_lower or kw in desc_lower
        )

        if suitable_count >= 1:
            # Estimate bid amount based on description length and complexity
            base_bid = 50
            if len(description) > 300:
                base_bid += 25
            if any(
                kw in desc_lower
                for kw in ["complex", "advanced", "professional", "expert"]
            ):
                base_bid += 50

            return EvaluationResult(
                is_suitable=True,
                bid_amount=base_bid,
                reasoning=f"Job appears suitable based on keyword matching ({suitable_count} matching keywords).",
                task_id=task_id,
                confidence=0.6,
            )

        # Default: mark as not suitable with moderate confidence
        return EvaluationResult(
            is_suitable=False,
            bid_amount=50,
            reasoning="Job does not match typical AI-capable tasks based on keyword analysis.",
            task_id=task_id,
            confidence=0.5,
        )

    async def scan_and_evaluate(
        self,
        max_posts: int = 10,
        min_bid_threshold: int = 30,
        marketplace_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Scan marketplace and evaluate all job postings.

        Args:
            max_posts: Maximum number of postings to fetch
            min_bid_threshold: Minimum bid amount to consider
            marketplace_url: Optional marketplace URL override

        Returns:
            Dictionary with scan results
        """
        start_time = datetime.now()

        try:
            # Fetch job postings
            postings = await self.fetch_job_postings(
                max_posts, marketplace_url=marketplace_url
            )

            if not postings:
                return {
                    "success": False,
                    "message": "No job postings found",
                    "postings": [],
                    "evaluations": [],
                    "scan_time": 0,
                }

            # Evaluate each posting
            evaluations = []
            suitable_jobs = []

            for posting in postings:
                evaluation = await self.evaluate_post(
                    posting.title, posting.description
                )
                evaluation.task_id = (
                    f"{evaluation.task_id}_{hash(posting.title) % 1000}"
                )
                evaluations.append(evaluation.to_dict())

                if (
                    evaluation.is_suitable
                    and evaluation.bid_amount >= min_bid_threshold
                ):
                    suitable_jobs.append(
                        {
                            "posting": {
                                "title": posting.title,
                                "description": posting.description[:200] + "...",
                                "budget": posting.budget,
                                "skills": posting.skills,
                            },
                            "evaluation": evaluation.to_dict(),
                        }
                    )

            scan_duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "message": f"Scanned {len(postings)} postings, found {len(suitable_jobs)} suitable",
                "postings_count": len(postings),
                "suitable_count": len(suitable_jobs),
                "suitable_jobs": suitable_jobs,
                "all_evaluations": evaluations,
                "scan_duration_seconds": scan_duration,
                "scanned_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Scan and evaluation failed: {e}")
            return {
                "success": False,
                "message": f"Scan failed: {str(e)}",
                "postings": [],
                "evaluations": [],
                "scan_time": 0,
                "error": str(e),
            }

    async def scan_all_marketplaces(
        self, max_posts: int = 10, min_bid_threshold: int = 30
    ) -> Dict[str, Any]:
        """
        Scan all configured marketplaces and evaluate all job postings.

        Deduplicates jobs across marketplaces based on title and description.

        Args:
            max_posts: Maximum number of postings to fetch per marketplace
            min_bid_threshold: Minimum bid amount to consider

        Returns:
            Dictionary with aggregated scan results from all marketplaces
        """
        start_time = datetime.now()

        try:
            # Determine which URLs to scan
            urls_to_scan = (
                self.marketplace_urls
                if not self.marketplace_url
                else [self.marketplace_url]
            )

            if not urls_to_scan:
                return {
                    "success": False,
                    "message": "No marketplace URLs configured",
                    "marketplaces_scanned": 0,
                    "total_postings": 0,
                    "suitable_jobs": [],
                    "scan_duration_seconds": 0,
                }

            all_suitable_jobs = []
            seen_job_hashes = set()  # For deduplication
            marketplace_results = {}

            # Scan each marketplace
            for url in urls_to_scan:
                logger.info(f"Scanning marketplace: {url}")

                try:
                    result = await self.scan_and_evaluate(
                        max_posts=max_posts,
                        min_bid_threshold=min_bid_threshold,
                        marketplace_url=url,
                    )

                    marketplace_results[url] = result

                    # Add suitable jobs, avoiding duplicates
                    for job in result.get("suitable_jobs", []):
                        job_hash = hash(
                            job["posting"]["title"] + job["posting"]["description"]
                        )
                        if job_hash not in seen_job_hashes:
                            seen_job_hashes.add(job_hash)
                            job["marketplace_url"] = url
                            all_suitable_jobs.append(job)

                except Exception as e:
                    logger.error(f"Failed to scan {url}: {e}")
                    marketplace_results[url] = {"success": False, "error": str(e)}

            scan_duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "message": f"Scanned {len(urls_to_scan)} marketplace(s), found {len(all_suitable_jobs)} suitable unique jobs",
                "marketplaces_scanned": len(urls_to_scan),
                "marketplace_results": marketplace_results,
                "total_postings": sum(
                    r.get("postings_count", 0) for r in marketplace_results.values()
                ),
                "suitable_jobs": all_suitable_jobs,
                "scan_duration_seconds": scan_duration,
                "scanned_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Multi-marketplace scan failed: {e}")
            return {
                "success": False,
                "message": f"Multi-marketplace scan failed: {str(e)}",
                "marketplaces_scanned": 0,
                "total_postings": 0,
                "suitable_jobs": [],
                "error": str(e),
            }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


async def run_single_scan(
    marketplace_url: Optional[str] = None, max_posts: int = 10
) -> Dict[str, Any]:
    """
    Run a single market scan.

    Args:
        marketplace_url: Optional override for marketplace URL
        max_posts: Maximum postings to scan

    Returns:
        Dictionary with scan results
    """
    async with MarketScanner(marketplace_url=marketplace_url) as scanner:
        return await scanner.scan_and_evaluate(max_posts=max_posts)


async def run_continuous_scan(
    interval: int = SCAN_INTERVAL,
    marketplace_url: Optional[str] = None,
    max_posts: int = 10,
    max_iterations: Optional[int] = None,
):
    """
    Run continuous market scanning at regular intervals.

    Args:
        interval: Seconds between scans
        marketplace_url: Optional override for marketplace URL
        max_posts: Maximum postings to scan per iteration
        max_iterations: Maximum number of scans (None for infinite)

    Yields:
        Scan results dictionary for each iteration
    """
    iteration = 0

    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        logger.info(f"Starting scan iteration {iteration}")

        try:
            async with MarketScanner(marketplace_url=marketplace_url) as scanner:
                result = await scanner.scan_and_evaluate(max_posts=max_posts)
                result["iteration"] = iteration
                yield result

        except Exception as e:
            logger.error(f"Scan iteration {iteration} failed: {e}")
            yield {"success": False, "error": str(e), "iteration": iteration}

        # Wait before next scan
        if max_iterations is None or iteration < max_iterations:
            logger.info(f"Waiting {interval} seconds before next scan")
            await asyncio.sleep(interval)


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":

    async def main():
        """Main entry point for testing."""
        print("=" * 60)
        print("Market Scanner - Test Run")
        print("=" * 60)

        # Run a single scan
        print("\nRunning market scan...")
        result = await run_single_scan(max_posts=5)

        print("\nScan Result:")
        print(f"  Success: {result.get('success')}")
        print(f"  Message: {result.get('message')}")
        print(f"  Postings Found: {result.get('postings_count', 0)}")
        print(f"  Suitable Jobs: {result.get('suitable_count', 0)}")

        if result.get("suitable_jobs"):
            print("\nSuitable Jobs:")
            for i, job in enumerate(result["suitable_jobs"], 1):
                print(f"\n  {i}. {job['posting']['title']}")
                print(f"     Bid: ${job['evaluation']['bid_amount']}")
                print(f"     Reasoning: {job['evaluation']['reasoning']}")

        print(f"\nScan Duration: {result.get('scan_duration_seconds', 0):.2f}s")

    # Run the main function
    asyncio.run(main())
