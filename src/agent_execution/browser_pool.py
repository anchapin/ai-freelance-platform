"""
Browser Connection Pool for Playwright

Manages browser instances and page allocation with proper resource cleanup.

Issue #4: Fix async Playwright resource leaks in market scanner
"""

import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PooledBrowser:
    """Represents a pooled browser instance."""

    browser: Any  # Browser type
    created_at: datetime
    in_use: bool = False
    page_count: int = 0
    last_used: Optional[datetime] = None
    error_count: int = 0


class BrowserPool:
    """
    Connection pool for Playwright browsers.

    Features:
    - Limits concurrent browser instances
    - Reuses browsers across multiple pages
    - Health checks for stale browsers
    - Automatic cleanup on shutdown
    """

    def __init__(self, max_browsers: int = 3, headless: bool = True):
        """
        Initialize browser pool.

        Args:
            max_browsers: Maximum concurrent browsers
            headless: Whether to run browsers in headless mode
        """
        self.max_browsers = max_browsers
        self.headless = headless

        # Pool storage
        self._browsers: Dict[str, PooledBrowser] = {}
        self._browser_queue: asyncio.Queue = asyncio.Queue()
        self._lock = asyncio.Lock()

        # Playwright instance
        self._playwright = None

        # Metrics
        self.browsers_created = 0
        self.browsers_reused = 0
        self.pages_created = 0

    async def start(self):
        """Initialize the browser pool."""
        try:
            self._playwright = await async_playwright().start()
            logger.info(f"Browser pool started (max: {self.max_browsers})")
        except Exception as e:
            logger.error(f"Failed to start browser pool: {e}")
            self._playwright = None
            raise

    async def stop(self):
        """Shutdown the browser pool and cleanup resources."""
        async with self._lock:
            for browser_id, pooled in list(self._browsers.items()):
                try:
                    await pooled.browser.close()
                    logger.debug(f"Browser {browser_id} closed")
                except Exception as e:
                    logger.warning(f"Error closing browser {browser_id}: {e}")

            self._browsers.clear()

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            logger.info("Browser pool stopped")

    async def acquire_browser(self) -> Any:
        """
        Acquire a browser instance from the pool.

        Reuses healthy browsers, creates new ones if needed.

        Returns:
            Browser instance

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._playwright:
            raise RuntimeError("Browser pool not initialized. Call start() first.")

        async with self._lock:
            # Try to reuse existing healthy browser
            for browser_id, pooled in list(self._browsers.items()):
                if not pooled.in_use:
                    # Check health and error count
                    if await self._is_browser_healthy(pooled.browser):
                        # Skip browsers with too many errors
                        if pooled.error_count < 5:
                            pooled.in_use = True
                            pooled.last_used = datetime.now(timezone.utc)
                            self.browsers_reused += 1
                            logger.debug(f"Reusing browser {browser_id}")
                            return pooled.browser
                        else:
                            logger.debug(
                                f"Browser {browser_id} exceeded error threshold, removing"
                            )
                            try:
                                await pooled.browser.close()
                            except Exception as e:
                                logger.warning(f"Error closing failed browser: {e}")
                            del self._browsers[browser_id]

            # Create new browser if under limit
            if len(self._browsers) < self.max_browsers:
                try:
                    browser = await self._playwright.chromium.launch(
                        headless=self.headless
                    )
                    browser_id = f"browser_{len(self._browsers)}"
                    self._browsers[browser_id] = PooledBrowser(
                        browser=browser,
                        created_at=datetime.now(timezone.utc),
                        in_use=True,
                        last_used=datetime.now(timezone.utc),
                    )
                    self.browsers_created += 1
                    logger.debug(f"Created new browser {browser_id}")
                    return browser
                except Exception as e:
                    logger.error(f"Failed to create browser: {e}")
                    raise

        # All browsers in use, wait for one to be released
        logger.warning("All browsers in use, waiting for availability")
        await asyncio.sleep(0.1)
        return await self.acquire_browser()

    async def release_browser(self, browser: Any, error: bool = False):
        """
        Release a browser back to the pool.

        Args:
            browser: Browser instance to release
            error: If True, marks that an error occurred on this browser
        """
        async with self._lock:
            for browser_id, pooled in self._browsers.items():
                if pooled.browser == browser:
                    pooled.in_use = False
                    pooled.last_used = datetime.now(timezone.utc)
                    if error:
                        pooled.error_count += 1
                        logger.debug(
                            f"Released browser {browser_id} with error "
                            f"(error_count={pooled.error_count})"
                        )
                    else:
                        logger.debug(f"Released browser {browser_id}")
                    return

    async def record_browser_error(self, browser: Any):
        """Record an error on a browser instance."""
        await self.release_browser(browser, error=True)

    async def cleanup_stale_browsers(self, max_age_minutes: int = 60):
        """
        Remove browsers that haven't been used in a while.

        Args:
            max_age_minutes: Maximum age for a browser (in minutes)
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(minutes=max_age_minutes)

            stale_ids = []
            for browser_id, pooled in self._browsers.items():
                if pooled.last_used and pooled.last_used < cutoff and not pooled.in_use:
                    stale_ids.append(browser_id)

            for browser_id in stale_ids:
                pooled = self._browsers[browser_id]
                try:
                    await pooled.browser.close()
                    del self._browsers[browser_id]
                    logger.info(f"Cleaned up stale browser {browser_id}")
                except Exception as e:
                    logger.warning(f"Error cleaning up stale browser {browser_id}: {e}")

    async def _is_browser_healthy(self, browser: Any) -> bool:
        """
        Check if a browser is still responsive.

        Args:
            browser: Browser to check

        Returns:
            True if browser is healthy
        """
        try:
            # Try to get version - quick health check
            _ = browser.version
            return True
        except Exception:
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Get pool metrics."""
        active_count = sum(1 for p in self._browsers.values() if p.in_use)
        total_errors = sum(p.error_count for p in self._browsers.values())

        return {
            "max_browsers": self.max_browsers,
            "total_browsers": len(self._browsers),
            "active_browsers": active_count,
            "idle_browsers": len(self._browsers) - active_count,
            "browsers_created": self.browsers_created,
            "browsers_reused": self.browsers_reused,
            "total_errors": total_errors,
            "pages_created": self.pages_created,
            "reuse_ratio": (
                self.browsers_reused / (self.browsers_created + 1)
                if self.browsers_created > 0
                else 0
            ),
        }


# Global pool instance
_browser_pool: Optional[BrowserPool] = None


def get_browser_pool(max_browsers: int = 3) -> BrowserPool:
    """Get or create the global BrowserPool instance."""
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = BrowserPool(max_browsers=max_browsers)
    return _browser_pool


async def init_browser_pool(max_browsers: int = 3) -> BrowserPool:
    """Initialize the global BrowserPool."""
    global _browser_pool
    _browser_pool = BrowserPool(max_browsers=max_browsers)
    await _browser_pool.start()
    return _browser_pool
