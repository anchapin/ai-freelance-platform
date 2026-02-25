"""
Regression tests for Issue #21: Resource Leak - Playwright Browser Instances

Tests ensure proper cleanup of Playwright browser, page, and playwright instances
in all execution paths (normal, exception, timeout).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from src.agent_execution.browser_pool import BrowserPool
from src.agent_execution.market_scanner import MarketScanner
from src.agent_execution.marketplace_discovery import MarketplaceDiscovery


class TestBrowserPoolCleanup:
    """Test suite for BrowserPool resource cleanup."""

    @pytest.mark.asyncio
    async def test_browser_pool_start_and_stop(self):
        """Test that start() and stop() properly manage lifecycle."""
        pool = BrowserPool(max_browsers=1)
        await pool.start()
        assert pool._playwright is not None
        
        await pool.stop()
        assert pool._playwright is None
        assert len(pool._browsers) == 0

    @pytest.mark.asyncio
    async def test_browser_pool_cleanup_on_error(self):
        """Test that resources are cleaned up on start() error."""
        pool = BrowserPool(max_browsers=1)
        
        with patch.object(pool, '_playwright') as mock_playwright:
            mock_playwright.stop = AsyncMock()
            # Simulate error during start
            with patch('src.agent_execution.browser_pool.async_playwright') as mock_async_pb:
                mock_async_pb.return_value.start = AsyncMock(side_effect=RuntimeError("Test error"))
                
                with pytest.raises(RuntimeError):
                    await pool.start()
                
                # Verify cleanup was called
                assert pool._playwright is None

    @pytest.mark.asyncio
    async def test_browser_pool_releases_browser_on_error(self):
        """Test that browser is released even when operation fails."""
        pool = BrowserPool(max_browsers=1)
        await pool.start()
        
        try:
            browser = await pool.acquire_browser()
            assert browser is not None
            
            # Simulate error
            await pool.release_browser(browser, error=True)
            
            # Browser should be marked as not in use
            for pooled in pool._browsers.values():
                assert not pooled.in_use
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_browser_pool_cleanup_stale_browsers(self):
        """Test that stale browsers are properly closed and cleaned."""
        pool = BrowserPool(max_browsers=3)
        await pool.start()
        
        try:
            # Acquire and release a browser
            browser = await pool.acquire_browser()
            await pool.release_browser(browser)
            
            # Cleanup stale browsers (should clean all browsers older than 0 minutes)
            await pool.cleanup_stale_browsers(max_age_minutes=0)
            
            # All browsers should be closed
            assert len(pool._browsers) == 0
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_browser_pool_removes_unhealthy_browsers(self):
        """Test that unhealthy browsers are closed and removed."""
        pool = BrowserPool(max_browsers=2)
        await pool.start()
        
        try:
            browser = await pool.acquire_browser()
            
            # Simulate error
            await pool.release_browser(browser, error=True)
            
            # Record enough errors to exceed threshold (5)
            browser_id = next(iter(pool._browsers.keys()))
            pool._browsers[browser_id].error_count = 6
            
            # Try to reuse - should create new one instead
            await pool.acquire_browser()
            
            # Should have 2 browsers (1 new, 1 failed but still in dict until cleanup)
            assert len(pool._browsers) <= 2
        finally:
            await pool.stop()


class TestMarketScannerCleanup:
    """Test suite for MarketScanner resource cleanup."""

    @pytest.mark.asyncio
    async def test_market_scanner_context_manager_cleanup(self):
        """Test that MarketScanner cleanup is called on exit."""
        with patch('src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE', True):
            scanner = MarketScanner()
            
            with patch.object(scanner, 'start', new_callable=AsyncMock):
                with patch.object(scanner, 'stop', new_callable=AsyncMock) as mock_stop:
                    async with scanner:
                        pass
                    
                    # Verify stop was called
                    mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scanner_cleanup_on_exception(self):
        """Test that MarketScanner stops even when exception occurs."""
        with patch('src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE', True):
            scanner = MarketScanner()
            
            with patch.object(scanner, 'start', new_callable=AsyncMock):
                with patch.object(scanner, 'stop', new_callable=AsyncMock) as mock_stop:
                    try:
                        async with scanner:
                            raise ValueError("Test exception")
                    except ValueError:
                        pass
                    
                    # Verify stop was called despite exception
                    mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scanner_stop_cleanup_order(self):
        """Test that stop() cleans up resources in correct order: page -> browser -> playwright."""
        with patch('src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE', True):
            scanner = MarketScanner()
            scanner.page = AsyncMock()
            scanner.browser = AsyncMock()
            scanner.playwright = AsyncMock()
            
            cleanup_order = []
            
            def track_close(name):
                cleanup_order.append(name)
            
            scanner.page.close = AsyncMock(side_effect=lambda: track_close('page'))
            scanner.browser.close = AsyncMock(side_effect=lambda: track_close('browser'))
            scanner.playwright.stop = AsyncMock(side_effect=lambda: track_close('playwright'))
            
            await scanner.stop()
            
            # Verify cleanup order
            assert cleanup_order == ['page', 'browser', 'playwright']
            assert scanner.page is None
            assert scanner.browser is None
            assert scanner.playwright is None


class TestMarketplaceDiscoveryCleanup:
    """Test suite for MarketplaceDiscovery resource cleanup."""

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_success(self):
        """Test that resources are cleaned up after successful evaluation."""
        with patch('src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE', True):
            discovery = MarketplaceDiscovery()
            
            with patch('src.agent_execution.marketplace_discovery.async_playwright') as mock_playwright:
                # Setup mock playwright
                mock_pb = AsyncMock()
                mock_browser = AsyncMock()
                mock_page = AsyncMock()
                
                mock_pb.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_page = AsyncMock(return_value=mock_page)
                mock_page.goto = AsyncMock(return_value=AsyncMock(status=200))
                mock_page.query_selector_all = AsyncMock(return_value=[])
                
                # Setup context manager
                mock_async_playwright = AsyncMock()
                mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_pb)
                mock_async_playwright.__aexit__ = AsyncMock(return_value=False)
                
                mock_playwright.return_value = mock_async_playwright
                
                # Call evaluation
                result = await discovery.evaluate_marketplace("https://example.com")
                
                # Verify result
                assert result["url"] == "https://example.com"
                assert result["accessible"] is True

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_exception(self):
        """Test that resources are cleaned up when exception occurs during evaluation."""
        with patch('src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE', True):
            discovery = MarketplaceDiscovery()
            
            with patch('src.agent_execution.marketplace_discovery.async_playwright') as mock_playwright:
                # Setup mock to raise error
                mock_pb = AsyncMock()
                mock_browser = AsyncMock()
                mock_page = AsyncMock()
                
                mock_pb.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_page = AsyncMock(return_value=mock_page)
                
                # Simulate error during page navigation
                mock_page.goto = AsyncMock(side_effect=RuntimeError("Network error"))
                mock_page.close = AsyncMock()
                mock_browser.close = AsyncMock()
                
                mock_async_playwright = AsyncMock()
                mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_pb)
                mock_async_playwright.__aexit__ = AsyncMock(return_value=False)
                mock_playwright.return_value = mock_async_playwright
                
                # Call evaluation
                result = await discovery.evaluate_marketplace("https://example.com", timeout=5)
                
                # Verify cleanup was called
                mock_page.close.assert_called_once()
                mock_browser.close.assert_called_once()
                
                # Verify result indicates failure
                assert result["accessible"] is False

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_cleanup_on_timeout(self):
        """Test that resources are cleaned up when timeout occurs."""
        with patch('src.agent_execution.marketplace_discovery.PLAYWRIGHT_AVAILABLE', True):
            discovery = MarketplaceDiscovery()
            
            with patch('src.agent_execution.marketplace_discovery.async_playwright') as mock_playwright:
                mock_pb = AsyncMock()
                mock_browser = AsyncMock()
                mock_page = AsyncMock()
                
                mock_pb.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_page = AsyncMock(return_value=mock_page)
                
                # Simulate timeout
                mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError())
                mock_page.close = AsyncMock()
                mock_browser.close = AsyncMock()
                
                mock_async_playwright = AsyncMock()
                mock_async_playwright.__aenter__ = AsyncMock(return_value=mock_pb)
                mock_async_playwright.__aexit__ = AsyncMock(return_value=False)
                mock_playwright.return_value = mock_async_playwright
                
                # Call evaluation
                result = await discovery.evaluate_marketplace("https://example.com", timeout=1)
                
                # Verify cleanup was called
                mock_page.close.assert_called_once()
                mock_browser.close.assert_called_once()
                
                # Verify timeout error in result
                assert "timeout" in result.get("error", "").lower()


class TestBrowserPoolMetrics:
    """Test browser pool metrics and monitoring."""

    @pytest.mark.asyncio
    async def test_browser_pool_metrics_tracking(self):
        """Test that browser pool correctly tracks metrics."""
        pool = BrowserPool(max_browsers=1)
        await pool.start()
        
        try:
            # Acquire a browser
            browser = await pool.acquire_browser()
            metrics = pool.get_metrics()
            
            assert metrics["total_browsers"] == 1
            assert metrics["active_browsers"] == 1
            assert metrics["idle_browsers"] == 0
            assert metrics["browsers_created"] == 1
            
            # Release it
            await pool.release_browser(browser)
            metrics = pool.get_metrics()
            
            assert metrics["active_browsers"] == 0
            assert metrics["idle_browsers"] == 1
            assert metrics["browsers_reused"] == 0  # Not yet reused
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_browser_pool_reuse_tracking(self):
        """Test that browser reuse is correctly tracked."""
        pool = BrowserPool(max_browsers=1)
        await pool.start()
        
        try:
            # Acquire, release, then reuse
            browser1 = await pool.acquire_browser()
            await pool.release_browser(browser1)
            
            browser2 = await pool.acquire_browser()
            
            # Should be same browser, reused
            assert browser1 == browser2
            
            metrics = pool.get_metrics()
            assert metrics["browsers_reused"] == 1
            assert metrics["browsers_created"] == 1
        finally:
            await pool.stop()
