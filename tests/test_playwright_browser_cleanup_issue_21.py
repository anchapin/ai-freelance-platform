"""
Regression tests for Issue #21: Resource Leak - Playwright Browser Instances

Tests ensure proper cleanup of Playwright browser, page, and playwright instances
in all execution paths (normal, exception, timeout).

Note: BrowserPool.start() tests are omitted here because they require Playwright to be
installed or complex mocking. The cleanup functionality is tested through higher-level
abstractions in the companion test file.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from src.agent_execution.market_scanner import MarketScanner
from src.agent_execution.marketplace_discovery import MarketplaceDiscovery


class TestMarketScannerCleanup:
    """Test suite for MarketScanner resource cleanup."""

    @pytest.mark.asyncio
    async def test_market_scanner_context_manager_cleanup(self):
        """Test that MarketScanner cleanup is called on exit."""
        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            scanner = MarketScanner()

            with patch.object(scanner, "start", new_callable=AsyncMock):
                with patch.object(scanner, "stop", new_callable=AsyncMock) as mock_stop:
                    async with scanner:
                        pass

                    # Verify stop was called
                    mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scanner_cleanup_on_exception(self):
        """Test that MarketScanner stops even when exception occurs."""
        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            scanner = MarketScanner()

            with patch.object(scanner, "start", new_callable=AsyncMock):
                with patch.object(scanner, "stop", new_callable=AsyncMock) as mock_stop:
                    try:
                        async with scanner:
                            raise ValueError("Test exception")
                    except ValueError:
                        pass

                    # Verify stop was called despite exception
                    mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scanner_stop_cleanup_order(self):
        """Test that stop() cleans up resources in correct order: page -> pool release."""
        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            scanner = MarketScanner()
            scanner.page = AsyncMock()
            scanner.browser = AsyncMock()

            cleanup_order = []

            def track_close(name):
                cleanup_order.append(name)

            scanner.page.close = AsyncMock(side_effect=lambda: track_close("page"))

            # Mock the pool
            mock_pool = AsyncMock()
            mock_pool.release_browser = AsyncMock(
                side_effect=lambda b: track_close("pool_release")
            )

            with patch(
                "src.agent_execution.market_scanner.get_browser_pool",
                return_value=mock_pool,
            ):
                await scanner.stop()

            # Verify cleanup order: page first, then release to pool
            assert cleanup_order == ["page", "pool_release"]
            assert scanner.page is None
            assert scanner.browser is None
            assert scanner.playwright is None


class TestMarketplaceDiscoveryCleanup:
    """Test suite for MarketplaceDiscovery resource cleanup."""

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_success(self):
        """Test that resources are cleaned up after successful evaluation."""
        with patch(
            "src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE", True
        ):
            discovery = MarketplaceDiscovery()

            # Setup mock pool and browser
            mock_pool = AsyncMock()
            mock_browser = AsyncMock()
            mock_page = AsyncMock()

            mock_pool.acquire_browser = AsyncMock(return_value=mock_browser)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_page.goto = AsyncMock(return_value=AsyncMock(status=200))
            mock_page.query_selector_all = AsyncMock(return_value=[])

            with patch(
                "src.agent_execution.marketplace_discovery.get_browser_pool",
                return_value=mock_pool,
            ):
                # Call evaluation
                result = await discovery.evaluate_marketplace("https://example.com")

                # Verify result
                assert result["url"] == "https://example.com"
                assert result["accessible"] is True

                # Verify pool release was called
                mock_pool.release_browser.assert_called_once_with(mock_browser)
                mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_exception(self):
        """Test that resources are cleaned up when exception occurs during evaluation."""
        with patch(
            "src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE", True
        ):
            discovery = MarketplaceDiscovery()

            # Setup mock pool and browser
            mock_pool = AsyncMock()
            mock_browser = AsyncMock()
            mock_page = AsyncMock()

            mock_pool.acquire_browser = AsyncMock(return_value=mock_browser)
            mock_browser.new_page = AsyncMock(return_value=mock_page)

            # Simulate error during page navigation
            mock_page.goto = AsyncMock(side_effect=RuntimeError("Network error"))

            with patch(
                "src.agent_execution.marketplace_discovery.get_browser_pool",
                return_value=mock_pool,
            ):
                # Call evaluation
                result = await discovery.evaluate_marketplace(
                    "https://example.com", timeout=5
                )

                # Verify cleanup was called
                mock_page.close.assert_called_once()
                mock_pool.release_browser.assert_called_once_with(mock_browser)

                # Verify result indicates failure
                assert result["accessible"] is False

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_timeout(self):
        """Test that resources are cleaned up when timeout occurs."""
        with patch(
            "src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE", True
        ):
            discovery = MarketplaceDiscovery()

            # Setup mock pool and browser
            mock_pool = AsyncMock()
            mock_browser = AsyncMock()
            mock_page = AsyncMock()

            mock_pool.acquire_browser = AsyncMock(return_value=mock_browser)
            mock_browser.new_page = AsyncMock(return_value=mock_page)

            # Simulate timeout
            mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError())

            with patch(
                "src.agent_execution.marketplace_discovery.get_browser_pool",
                return_value=mock_pool,
            ):
                # Call evaluation
                result = await discovery.evaluate_marketplace(
                    "https://example.com", timeout=1
                )

                # Verify cleanup was called
                mock_page.close.assert_called_once()
                mock_pool.release_browser.assert_called_once_with(mock_browser)

                # Verify timeout error in result
                assert "timeout" in result.get("error", "").lower()
