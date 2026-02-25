# Subagent Task: Issue #4

## Issue: Fix async Playwright resource leaks in market scanner

**Repository**: /home/alexc/Projects/ArbitrageAI  
**Worktree**: main-issue-4  
**Branch**: feature/playwright-resource-leak  
**Priority**: P1

## Problem Statement
The market scanner uses Playwright for web scraping without proper resource cleanup. Missing try/finally blocks, no async context managers, and concurrent browser spawning cause file descriptor exhaustion after 1000+ tasks, leading to system instability.

## Objective
Properly manage Playwright resources using async context managers and implement connection pooling to prevent resource exhaustion.

## Implementation Tasks

### 1. Refactor Playwright Resource Management (market_scanner.py)

**Current Pattern (WRONG)**:
```python
browser = await async_playwright().start()
page = await browser.new_page()
await page.goto(url, timeout=PAGE_LOAD_TIMEOUT)
# No cleanup if exception occurs
```

**Correct Pattern (REQUIRED)**:
```python
async with async_playwright() as p:
    async with p.chromium.launch(headless=True) as browser:
        async with browser.new_page() as page:
            # All code here
            pass
        # Page closed automatically
    # Browser closed automatically
# Playwright closed automatically
```

**Tasks**:
- Update lines 200-500 in market_scanner.py
- Wrap all browser/page operations with async context managers
- Replace all `.start()` calls with context managers
- Ensure all `.close()` calls are in finally blocks or use context managers
- Add timeout handling within context manager scope

### 2. Implement Browser Connection Pooling

Create `BrowserPool` class:
```python
class BrowserPool:
    def __init__(self, max_browsers: int = 3):
        self.max_browsers = max_browsers
        self.available: asyncio.Queue = asyncio.Queue(maxsize=max_browsers)
        self.in_use = set()
        
    async def acquire_browser(self) -> Browser:
        # Get from pool or launch new
        if self.available.empty() and len(self.in_use) < self.max_browsers:
            browser = await self._launch_browser()
        else:
            browser = await self.available.get()
        self.in_use.add(browser)
        return browser
        
    async def release_browser(self, browser: Browser):
        self.in_use.discard(browser)
        await self.available.put(browser)
        
    async def health_check(self, browser: Browser) -> bool:
        # Check if browser still responsive
        try:
            page = await browser.new_page()
            await page.close()
            return True
        except:
            return False
            
    async def _launch_browser(self) -> Browser:
        async with async_playwright() as p:
            return await p.chromium.launch(headless=True)
```

**Usage**:
```python
browser = await browser_pool.acquire_browser()
try:
    # Use browser
    pass
finally:
    await browser_pool.release_browser(browser)
```

### 3. Update marketplace_discovery.py (lines 419-505)

**Tasks**:
- Apply same async context manager pattern
- Ensure all Playwright resources properly scoped
- Add error handling with resource cleanup
- Remove any manual browser/page closing (rely on context managers)

### 4. Implement Circuit Breaker for Failing URLs

Create `URLCircuitBreaker` class:
```python
class URLCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown: int = 300):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown  # seconds
        self.failures: Dict[str, List[float]] = {}  # url -> [timestamp, ...]
        self.broken_urls: Dict[str, float] = {}  # url -> unbreak_time
        
    async def should_request(self, url: str) -> bool:
        # Check if URL is in cooldown
        if url in self.broken_urls:
            if time.time() < self.broken_urls[url]:
                return False  # Still in cooldown
            else:
                del self.broken_urls[url]  # Reset
                
        return True
        
    def record_failure(self, url: str):
        now = time.time()
        self.failures[url] = [t for t in self.failures.get(url, []) if now - t < 300]
        self.failures[url].append(now)
        
        if len(self.failures[url]) >= self.failure_threshold:
            self.broken_urls[url] = now + self.cooldown
            
    def record_success(self, url: str):
        self.failures[url] = []
```

**Integration**:
```python
async def scrape_url(url: str):
    if not await circuit_breaker.should_request(url):
        logger.warning(f"Circuit open for {url}")
        return None
        
    try:
        result = await fetch_page(url)
        circuit_breaker.record_success(url)
        return result
    except Exception as e:
        circuit_breaker.record_failure(url)
        raise
```

### 5. Implement Exponential Backoff for Retries

Create `ExponentialBackoff` class:
```python
class ExponentialBackoff:
    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0):
        self.base_delay = base_delay
        self.max_delay = max_delay
        
    async def wait(self, retry_count: int):
        delay = min(self.base_delay * (2 ** retry_count), self.max_delay)
        await asyncio.sleep(delay)
        
    async def with_retry(self, func, max_retries: int = 3):
        backoff = ExponentialBackoff()
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await backoff.wait(attempt)
```

**Integration**:
```python
async def scrape_with_retry(url: str, max_retries: int = 3):
    async def _scrape():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=PAGE_LOAD_TIMEOUT)
                return await page.content()
            finally:
                await page.close()
                await browser.close()
                
    backoff = ExponentialBackoff()
    return await backoff.with_retry(_scrape, max_retries)
```

### 6. Add Resource Cleanup Tests

Create `test_resource_leaks.py`:
```python
import subprocess
import os

def get_file_descriptor_count(pid: int) -> int:
    """Count open file descriptors for process"""
    proc_fd_dir = f"/proc/{pid}/fd"
    return len(os.listdir(proc_fd_dir))

async def test_no_resource_leak_on_1000_tasks():
    """Verify 1000+ sequential tasks don't exhaust resources"""
    
    initial_fds = get_file_descriptor_count(os.getpid())
    
    for i in range(1000):
        await execute_marketplace_scan_task()
        
        if (i + 1) % 100 == 0:
            current_fds = get_file_descriptor_count(os.getpid())
            increase = current_fds - initial_fds
            assert increase < 50, f"Too many FDs open: {increase}"
    
    final_fds = get_file_descriptor_count(os.getpid())
    assert final_fds <= initial_fds + 10, "FDs not cleaned up"
```

### 7. Integration Testing

Add tests for:
- Async context manager cleanup
- Browser pool limits enforced
- Circuit breaker activation and reset
- Exponential backoff timing
- Exception handling preserves resources
- Stress test with limited file descriptors

```bash
# Test with reduced file descriptor limit
ulimit -n 100
pytest tests/test_resource_leaks.py -v
```

## Files to Modify
- `src/agent_execution/market_scanner.py` (lines 200-500)
- `src/agent_execution/marketplace_discovery.py` (lines 419-505)
- `src/agent_execution/browser_pool.py` (new file)
- `src/agent_execution/circuit_breaker.py` (new file)
- `src/agent_execution/backoff.py` (new file)
- `tests/test_resource_leaks.py` (new test file)
- `tests/test_circuit_breaker.py` (new test file)

## Testing Requirements
- ✓ All Playwright resources use async context managers
- ✓ Browser connection pooling working correctly
- ✓ Circuit breaker prevents dead URLs from blocking
- ✓ Exponential backoff timing correct
- ✓ Resource leak detection: 1000 tasks → no FD exhaustion
- ✓ Exception handling: all resources cleaned up on error
- ✓ Stress test with limited file descriptors (<200)
- ✓ All tests passing with 100% coverage

## Acceptance Criteria
- [ ] All Playwright resources use async context managers
- [ ] Browser connection pooling implemented and tested
- [ ] Circuit breaker prevents dead URLs (configurable threshold)
- [ ] Exponential backoff for retries (configurable)
- [ ] Resource leak detection tests added
- [ ] 1000+ sequential tasks don't exhaust resources
- [ ] System stability verified with stress testing
- [ ] All tests passing

## Timeline
Estimated: 5-6 hours

## Notes
- Test on low-memory system (may trigger different failures)
- Monitor resource usage in CI/CD pipeline
- Consider using `resource.setrlimit()` in tests for stricter validation
- Coordinate with Issue #8 (distributed lock) - shared code paths in market_scanner
