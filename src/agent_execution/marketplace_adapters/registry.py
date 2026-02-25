"""
Marketplace Registry

Factory pattern for registering and creating marketplace adapters.
Provides a registry to manage different marketplace implementations.
"""

from typing import Dict, Type, Optional, Any
from .base import MarketplaceAdapter
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketplaceRegistry:
    """
    Registry for marketplace adapters.

    Implements factory pattern to register and instantiate marketplace adapters.
    Supports dynamic registration of new marketplace implementations.
    """

    _adapters: Dict[str, Type[MarketplaceAdapter]] = {}

    @classmethod
    def register(
        cls, name: str, adapter_class: Type[MarketplaceAdapter]
    ) -> None:
        """
        Register a new marketplace adapter.

        Args:
            name: Marketplace name (e.g., 'fiverr', 'upwork', 'peoplehour')
            adapter_class: Adapter class to register

        Raises:
            ValueError: If marketplace already registered
        """
        if name.lower() in cls._adapters:
            logger.warning(
                f"Marketplace '{name}' already registered, overwriting..."
            )
        cls._adapters[name.lower()] = adapter_class
        logger.info(f"Registered marketplace adapter: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[Type[MarketplaceAdapter]]:
        """
        Get adapter class by marketplace name.

        Args:
            name: Marketplace name

        Returns:
            Adapter class or None if not registered
        """
        return cls._adapters.get(name.lower())

    @classmethod
    def create(
        cls, name: str, **kwargs: Any
    ) -> MarketplaceAdapter:
        """
        Create an instance of a registered adapter.

        Args:
            name: Marketplace name
            **kwargs: Arguments to pass to adapter constructor

        Returns:
            Adapter instance

        Raises:
            ValueError: If marketplace not registered
        """
        adapter_class = cls.get(name)
        if not adapter_class:
            raise ValueError(
                f"Marketplace '{name}' not registered. "
                f"Available: {list(cls._adapters.keys())}"
            )
        return adapter_class(**kwargs)

    @classmethod
    def list_registered(cls) -> list:
        """
        Get list of registered marketplace names.

        Returns:
            List of marketplace names
        """
        return list(cls._adapters.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        Check if marketplace is registered.

        Args:
            name: Marketplace name

        Returns:
            True if registered
        """
        return name.lower() in cls._adapters

    @classmethod
    def clear(cls) -> None:
        """Clear all registered adapters (useful for testing)."""
        cls._adapters.clear()
        logger.info("Cleared all registered marketplace adapters")
