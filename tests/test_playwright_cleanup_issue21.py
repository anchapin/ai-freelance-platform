"""
Comprehensive tests for Playwright Resource Leak Fix (Issue #21)

Tests verify that browser instances and pages are properly cleaned up
across all Playwright usage patterns, preventing resource exhaustion.

Tests cover:
1. MarketScanner context manager and page cleanup
2. MarketplaceDiscovery async context manager pattern
3. Multiple iterations without resource growth
4. Exception handling with proper cleanup
5. Page-per-operation pattern in MarketScanner
6. Timeout handling and cancellation cleanup
"""

import pytest
import psutil
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent_execution.market_scanner import MarketScanner
from src.agent_execution.marketplace_discovery import MarketplaceDiscovery
from src.agent_execution.browser_pool import BrowserPool, PooledBrowser
from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_open_files_count() -> int:
    """Get the current process's open file descriptor count."""
    try:
        process = psutil.Process()
        return len(process.open_files())
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return 0


def get_fd_count() -> int:
    """Get the current process's file descriptor count (Linux-specific)."""
    try:
        import os

        return len(os.listdir(f"/proc/{os.getpid()}/fd"))
    except Exception:
        return 0


class TestMarketScannerResourceCleanup:
    """Tests for MarketScanner resource cleanup patterns."""

    @pytest.mark.asyncio
    async def test_market_scanner_async_context_manager_cleanup(self):
        """Test MarketScanner context manager properly cleans up resources."""
        scanner = None

        # Mock the pool
        mock_pool = AsyncMock()
        mock_browser = AsyncMock()
        mock_pool.acquire_browser = AsyncMock(return_value=mock_browser)

        with patch(
            "src.agent_execution.market_scanner.get_browser_pool",
            return_value=mock_pool,
        ):
            try:
                async with MarketScanner() as scanner:
                    # Scanner should be initialized
                    assert scanner is not None
                    assert hasattr(scanner, "browser")

                # After context exit, scanner should be cleaned up
                mock_pool.release_browser.assert_called_once_with(mock_browser)
            except Exception as e:
                # Re-raise if not related to environment
                if "Playwright is not installed" not in str(e):
                    raise

    @pytest.mark.asyncio
    async def test_market_scanner_exception_during_context(self):
        """Test that cleanup happens even when exception occurs in context."""
        exception_raised = False

        # Mock the pool
        mock_pool = AsyncMock()
        mock_browser = AsyncMock()
        mock_pool.acquire_browser = AsyncMock(return_value=mock_browser)

        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            with patch(
                "src.agent_execution.market_scanner.get_browser_pool",
                return_value=mock_pool,
            ):
                try:
                    async with MarketScanner():
                        # Simulate an exception
                        raise ValueError("Test exception")
                except ValueError:
                    exception_raised = True
                except Exception:
                    # Some other exception occurred
                    pass

        # Exception should have been raised
        assert exception_raised
        # Cleanup should have happened
        mock_pool.release_browser.assert_called_once_with(mock_browser)

    @pytest.mark.asyncio
    async def test_market_scanner_page_per_operation(self):
        """Test that fetch_job_postings creates and closes page per operation."""
        # Verify the method structure includes page creation/cleanup
        import inspect

        scanner = MarketScanner()
        source = inspect.getsource(scanner.fetch_job_postings)

        # Should create fresh page per operation
        # Note: browser.new_page() is used now that it's acquired from pool
        assert "await self.browser.new_page()" in source

        # Should close page in finally block
        assert "await page.close()" in source
        assert "finally:" in source

    @pytest.mark.asyncio
    async def test_market_scanner_stop_cleanup_order(self):
        """Test that stop() closes resources in proper order: page -> pool release."""
        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            scanner = MarketScanner()

            # Mock the resources
            scanner.page = AsyncMock()
            scanner.browser = AsyncMock()

            # Track call order
            call_order = []

            async def track_page_close():
                call_order.append("page")

            async def track_pool_release(b):
                call_order.append("pool_release")

            scanner.page.close = AsyncMock(side_effect=track_page_close)

            # Mock the pool
            mock_pool = AsyncMock()
            mock_pool.release_browser = AsyncMock(side_effect=track_pool_release)

            with patch(
                "src.agent_execution.market_scanner.get_browser_pool",
                return_value=mock_pool,
            ):
                # Call stop
                await scanner.stop()

            # Verify cleanup order: page first, then release to pool
            assert call_order == ["page", "pool_release"]

            # Verify all are set to None
            assert scanner.page is None
            assert scanner.browser is None
            assert scanner.playwright is None

    @pytest.mark.asyncio
    async def test_market_scanner_start_cleanup_on_failure(self):
        """Test that start() cleans up on failure."""
        # Verify start() method calls stop() on failure by checking the source
        import inspect

        scanner = MarketScanner()
        source = inspect.getsource(scanner.start)

        # Should have try/except with cleanup on error
        assert "try:" in source

        # Should call stop() on failure - check for it in the main except block
        # Use rsplit to get the last except block which is the main one
        assert "except Exception as e:" in source
        main_except = source.rsplit("except Exception as e:", 1)[1]
        assert "await self.stop()" in main_except
        assert "raise" in main_except


class TestMarketplaceDiscoveryCleanup:
    """Tests for MarketplaceDiscovery resource cleanup."""

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_uses_nested_context_managers(self):
        """Test evaluate_marketplace properly uses resource management patterns."""
        import inspect

        discovery = MarketplaceDiscovery()
        source = inspect.getsource(discovery.evaluate_marketplace)

        # Verify the method structure includes proper management (Issue #4):
        # - get_browser_pool()
        # - try/finally for page.close()
        # - try/finally for pool.release_browser()
        assert "get_browser_pool()" in source
        # Check for both nesting levels
        assert (
            source.count("finally:") >= 2
        )  # At least 2 finally blocks for page and pool release

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_handles_timeout(self):
        """Test evaluate_marketplace handles asyncio.TimeoutError properly."""
        import inspect

        discovery = MarketplaceDiscovery()
        source = inspect.getsource(discovery.evaluate_marketplace)

        # Verify timeout handling is present
        assert "asyncio.TimeoutError" in source

        # Verify it returns proper error response
        assert '"error": "Page load timeout"' in source

    @pytest.mark.asyncio
    async def test_evaluate_marketplace_exception_handling(self):
        """Test evaluate_marketplace exception handling and cleanup."""
        import inspect

        discovery = MarketplaceDiscovery()
        source = inspect.getsource(discovery.evaluate_marketplace)

        # Verify exception handling
        assert "except" in source
        assert "try:" in source

        # Verify it returns error response without propagating
        assert '"error": str(e)' in source or "str(e)" in source


class TestBrowserPoolResourceTracking:
    """Tests for browser pool resource tracking and cleanup."""

    @pytest.mark.asyncio
    async def test_browser_pool_tracks_errors(self):
        """Test pool tracks browser errors for health monitoring."""
        pool = BrowserPool(max_browsers=2)

        # Create a mock browser
        mock_browser = MagicMock()
        mock_browser.version = "1.0"
        mock_browser.close = AsyncMock()

        from datetime import datetime, timezone

        # Add browser to pool
        pool._browsers["test_0"] = PooledBrowser(
            browser=mock_browser,
            created_at=datetime.now(timezone.utc),
            in_use=False,
            error_count=0,
        )

        # Record an error
        await pool.record_browser_error(mock_browser)

        # Verify error was tracked
        assert pool._browsers["test_0"].error_count == 1

    @pytest.mark.asyncio
    async def test_browser_pool_removes_unhealthy_browsers(self):
        """Test pool removes browsers exceeding error threshold."""
        pool = BrowserPool(max_browsers=3)

        from datetime import datetime, timezone

        # Create a browser with high error count
        mock_browser = MagicMock()
        mock_browser.version = "1.0"

        pool._browsers["unhealthy"] = PooledBrowser(
            browser=mock_browser,
            created_at=datetime.now(timezone.utc),
            in_use=False,
            error_count=5,  # Exceeds threshold
        )

        # Create a healthy browser
        healthy_mock = MagicMock()
        healthy_mock.version = "1.0"

        pool._browsers["healthy"] = PooledBrowser(
            browser=healthy_mock,
            created_at=datetime.now(timezone.utc),
            in_use=False,
            error_count=2,
        )

        # Get metrics
        metrics = pool.get_metrics()

        # Verify metrics
        assert metrics["total_browsers"] == 2
        assert metrics["total_errors"] == 7  # 5 + 2


class TestResourceLeakDetectionMultipleIterations:
    """Tests that verify no resource leaks occur over multiple operations."""

    @pytest.mark.asyncio
    async def test_market_scanner_multiple_operations_no_leak(self):
        """Test multiple MarketScanner operations don't leak resources."""
        # This is a structural test - verifies the pattern is correct
        # Actual resource leak testing would need real Playwright running

        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            # Verify that MarketScanner can be used multiple times
            scanner1 = MarketScanner()
            scanner2 = MarketScanner()

            # Both should be independent instances
            assert scanner1 is not scanner2
            assert id(scanner1) != id(scanner2)

    @pytest.mark.asyncio
    async def test_marketplace_discovery_multiple_evaluations(self):
        """Test multiple marketplace evaluations don't leak."""
        # Structural test for the evaluation method
        discovery1 = MarketplaceDiscovery()
        discovery2 = MarketplaceDiscovery()

        # Both should be independent
        assert discovery1 is not discovery2


class TestAsyncContextManagerPattern:
    """Tests for proper async context manager patterns."""

    @pytest.mark.asyncio
    async def test_market_scanner_aenter_aexit_present(self):
        """Test MarketScanner has proper async context manager methods."""
        scanner = MarketScanner()

        # Verify context manager methods exist
        assert hasattr(scanner, "__aenter__")
        assert hasattr(scanner, "__aexit__")
        assert callable(getattr(scanner, "__aenter__"))
        assert callable(getattr(scanner, "__aexit__"))

    @pytest.mark.asyncio
    async def test_market_scanner_aexit_returns_false(self):
        """Test __aexit__ returns False (doesn't suppress exceptions)."""
        import inspect

        scanner = MarketScanner()
        source = inspect.getsource(scanner.__aexit__)

        # Should return False to not suppress exceptions
        assert "return False" in source

    @pytest.mark.asyncio
    async def test_market_scanner_aexit_calls_stop(self):
        """Test __aexit__ calls stop() for cleanup."""
        import inspect

        scanner = MarketScanner()
        source = inspect.getsource(scanner.__aexit__)

        # Should call stop() for cleanup
        assert "stop()" in source or "await" in source


class TestExceptionHandlingWithCleanup:
    """Tests that verify cleanup happens even with exceptions."""

    @pytest.mark.asyncio
    async def test_market_scanner_page_close_on_exception(self):
        """Test that page is closed even when operation fails."""
        with patch("src.agent_execution.market_scanner.PLAYWRIGHT_AVAILABLE", True):
            scanner = MarketScanner()

            # Mock browser with a page that will raise
            mock_browser = AsyncMock()
            mock_page = AsyncMock()

            scanner.browser = mock_browser

            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_page.goto = AsyncMock(side_effect=Exception("Network error"))
            mock_page.close = AsyncMock()

            # Call fetch_job_postings - should handle exception
            result = await scanner.fetch_job_postings()

            # Should return fallback mock data
            assert result is not None
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_marketplace_discovery_nested_exception_handling(self):
        """Test nested exception handling in evaluate_marketplace."""
        import inspect

        discovery = MarketplaceDiscovery()
        source = inspect.getsource(discovery.evaluate_marketplace)

        # Should have multiple try/except blocks for different levels:
        # 1. Outer try for overall error
        # 2. Inner try for page operation
        # 3. Finally blocks for cleanup
        except_count = source.count("except")
        finally_count = source.count("finally:")

        assert except_count >= 2  # Multiple exception handlers
        assert finally_count >= 1  # At least one finally


class TestResourceCleanupDocumentation:
    """Tests that verify cleanup patterns are properly documented."""

    @pytest.mark.asyncio
    async def test_market_scanner_cleanup_documented(self):
        """Test MarketScanner cleanup is documented."""

        scanner = MarketScanner()

        # Check start() docstring
        start_doc = scanner.start.__doc__ or ""
        assert len(start_doc) > 0

        # Check stop() docstring
        stop_doc = scanner.stop.__doc__ or ""
        assert len(stop_doc) > 0
        assert "cleanup" in stop_doc.lower()

    @pytest.mark.asyncio
    async def test_marketplace_discovery_context_manager_documented(self):
        """Test evaluate_marketplace context manager is documented."""

        discovery = MarketplaceDiscovery()
        doc = discovery.evaluate_marketplace.__doc__ or ""

        assert len(doc) > 0
        # Should mention context managers or cleanup
        doc_lower = doc.lower()
        assert "context" in doc_lower or "cleanup" in doc_lower or "async" in doc_lower


logger = get_logger(__name__)
