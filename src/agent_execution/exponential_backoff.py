"""
Exponential Backoff Retry Strategy

Implements exponential backoff for retrying failed operations.

Issue #4: Fix async Playwright resource leaks in market scanner
"""

import asyncio
import random
from typing import Optional, TypeVar, Callable, Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class ExponentialBackoff:
    """
    Exponential backoff strategy with jitter.
    
    Features:
    - Configurable base delay and max delay
    - Exponential growth: delay = base * (2 ** retry_count)
    - Jitter to prevent thundering herd
    - Customizable max retries
    """
    
    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True
    ):
        """
        Initialize backoff strategy.
        
        Args:
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            jitter: Whether to add random jitter
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
    
    async def wait(self, retry_count: int) -> float:
        """
        Wait for exponentially increasing delay.
        
        Args:
            retry_count: Current retry attempt (0-based)
            
        Returns:
            Actual delay waited (in seconds)
        """
        # Calculate delay: base * 2^retry_count
        delay = self.base_delay * (2 ** retry_count)
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter (±25%)
        if self.jitter:
            jitter_factor = 0.75 + random.random() * 0.5  # 0.75 to 1.25
            delay = delay * jitter_factor
        
        logger.debug(f"Exponential backoff: waiting {delay:.2f}s (retry {retry_count})")
        await asyncio.sleep(delay)
        
        return delay
    
    async def with_retry(
        self,
        func: Callable[..., Any],
        *args,
        max_retries: int = 3,
        **kwargs
    ) -> Any:
        """
        Execute function with exponential backoff retry.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            max_retries: Maximum retry attempts
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
            
        Raises:
            Exception: If all retries fail
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = await func(*args, **kwargs)
                
                if attempt > 0:
                    logger.debug(f"Operation succeeded on retry {attempt + 1}")
                
                return result
                
            except Exception as e:
                last_error = e
                
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Operation failed (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    await self.wait(attempt)
                else:
                    logger.error(
                        f"Operation failed after {max_retries} attempts: {e}"
                    )
        
        if last_error:
            raise last_error
        
        raise RuntimeError("Operation failed: no error recorded")


# Common backoff strategies
DEFAULT_BACKOFF = ExponentialBackoff(base_delay=1.0, max_delay=60.0)
QUICK_BACKOFF = ExponentialBackoff(base_delay=0.1, max_delay=10.0)
SLOW_BACKOFF = ExponentialBackoff(base_delay=5.0, max_delay=300.0)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs
) -> Any:
    """
    Execute function with exponential backoff retry (convenience function).
    
    Args:
        func: Async function to execute
        *args: Positional arguments
        max_retries: Maximum attempts
        base_delay: Initial delay in seconds
        **kwargs: Keyword arguments
        
    Returns:
        Result from func
    """
    backoff = ExponentialBackoff(base_delay=base_delay)
    return await backoff.with_retry(func, *args, max_retries=max_retries, **kwargs)
