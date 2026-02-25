"""Async utilities for safe event loop handling"""

import asyncio
from typing import Callable, TypeVar, Awaitable

T = TypeVar("T")


async def safe_sleep(seconds: float) -> None:
    """Sleep without blocking event loop - use instead of time.sleep()"""
    await asyncio.sleep(seconds)
