"""Base classes for pipeline tools."""
from typing import Any, Generic, TypeVar, Optional, List
from smolagents import Tool
from src.pipelines.stages.collectors import ResultCollector
from src.utils.logging import logger

T = TypeVar('T')


class CollectorAwareTool(Tool, Generic[T]):
    """
    Base class for tools that collect results.

    Provides unified interface for storing results in either:
    - External ResultCollector (preferred for pipeline integration)
    - Internal fallback list (for standalone use)

    This eliminates duplicate collector logic across tool implementations.

    Usage:
        class MyTool(CollectorAwareTool[MyModel]):
            def __init__(self, collector: Optional[ResultCollector[MyModel]] = None):
                super().__init__(collector)
                # ... tool-specific initialization

            def forward(self, ...):
                # Process and create item
                item = MyModel(...)

                # Store using unified method
                self.store_result(item, context="MyModel")
                return item
    """

    def __init__(self, collector: Optional[ResultCollector[T]] = None):
        super().__init__()
        self.collector = collector
        self._fallback_items: List[T] = []

    def store_result(self, item: T, context: str = "") -> None:
        """
        Store result using collector or fallback list.

        Args:
            item: Item to store
            context: Optional context for logging (e.g., "Article", "Event")
        """
        if self.collector is not None:
            self.collector.add(item)
            count = self.collector.count()
            logger.debug(f"{context}: Added to collector (total: {count})")
        else:
            self._fallback_items.append(item)
            count = len(self._fallback_items)
            logger.debug(f"{context}: Added to fallback list (total: {count})")

    def get_stored_count(self) -> int:
        """Get count of stored items."""
        if self.collector is not None:
            return self.collector.count()
        return len(self._fallback_items)

    def get_stored_items(self) -> List[T]:
        """Get all stored items (mainly for testing)."""
        if self.collector is not None:
            return self.collector.get_all()
        return self._fallback_items.copy()
