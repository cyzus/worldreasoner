"""Base classes for pipeline tools.

This module provides reusable base classes for tools:

1. **CollectorAwareTool** - For tools that collect/store results
   - Use when tool generates items that need to be collected (Events, Articles, etc.)
   - Provides unified store_result() interface
   - Example: EventIdentifierTool, CausalReasonerTool

2. **ToolResponseMixin** - For standardized JSON responses
   - Use json_response() instead of manual json.dumps()
   - Use error_response() for consistent error formatting
   - Use success_response() for success cases
   - Example: Any tool returning JSON to LLM

3. **DatabaseAwareTool** - For tools that need database access (in database_mixin.py)
   - Standardizes database initialization (db, db_path, default)
   - Provides not_found_response() helper
   - Use when tool reads/writes to database
   - Example: ArticleRetrievalTool, EventDetailsTool, GraphInspectorTool

Tools can inherit from multiple base classes as needed:
- CollectorAwareTool + manual DB init: EventIdentifierTool
- DatabaseAwareTool only: ArticleRetrievalTool
- ToolResponseMixin: Can be added to any tool
"""

import json
from typing import Any, Generic, TypeVar, Optional, List, Dict
from smolagents import Tool
from src.core.collectors import ResultCollector
from src.utils.logging import logger

T = TypeVar("T")


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


class ToolResponseMixin:
    """Mixin for standardized tool responses.

    Provides consistent JSON formatting across all tools.
    """

    @staticmethod
    def json_response(data: Any, pretty: bool = True) -> str:
        """Format data as JSON string for LLM consumption.

        Args:
            data: Data to serialize (dict, list, or serializable object)
            pretty: Whether to use indentation (default: True)

        Returns:
            JSON string with datetime/enum handling
        """
        if pretty:
            return json.dumps(data, indent=2, default=str)
        return json.dumps(data, default=str)

    @staticmethod
    def error_response(
        message: str, details: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        """Format error response for LLM.

        Args:
            message: Error message
            details: Optional additional error details
            **kwargs: Additional context fields (status, missing_ids, etc.)

        Returns:
            JSON error string

        Examples:
            >>> error_response("Article not found", details={"article_id": "a123"})
            >>> error_response("Validation failed", status="rejected", missing_ids=["a1", "a2"])
        """
        error_obj = {"error": message}

        if details:
            error_obj.update(details)

        if kwargs:
            error_obj.update(kwargs)

        return json.dumps(error_obj, indent=2, default=str)

    @staticmethod
    def success_response(data: Dict[str, Any], **kwargs) -> str:
        """Format success response for LLM.

        Args:
            data: Response data
            **kwargs: Additional fields to merge

        Returns:
            JSON success string
        """
        response = dict(data)
        if kwargs:
            response.update(kwargs)
        return json.dumps(response, indent=2, default=str)
