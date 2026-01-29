"""Result collection utilities for pipeline stages.

Provides a clean separation between tool processing logic and result storage,
making tools stateless and reusable across different pipeline runs.
"""

from typing import Generic, List, TypeVar, Optional


T = TypeVar("T")


class ResultCollector(Generic[T]):
    """Generic collector for accumulating results from tool executions.

    This class provides a clean separation of concerns:
    - Tools focus on processing (fetching, parsing, analyzing)
    - Collectors handle storage and aggregation
    - Stages orchestrate the flow

    Benefits:
    - Tools become stateless and reusable
    - Easier testing (can mock collector)
    - Thread-safe result accumulation
    - Clear data flow in pipelines

    Usage:
        >>> from src.domain.models import Article
        >>> collector = ResultCollector[Article]()
        >>> tool = ArticleCollectorTool(collector=collector)
        >>> agent.run("Collect articles...")
        >>> articles = collector.get_all()

    Type Safety:
        The generic type parameter ensures type safety:
        >>> collector = ResultCollector[Article]()
        >>> collector.add(article)  # ✓ Type-safe
        >>> collector.add(event)    # ✗ Type error
    """

    def __init__(self):
        """Initialize an empty result collector."""
        self._items: List[T] = []

    def add(self, item: T) -> None:
        """Add a single item to the collection.

        Args:
            item: Item to add to the collection

        Example:
            >>> collector.add(article)
            >>> collector.add(event)
        """
        self._items.append(item)

    def add_many(self, items: List[T]) -> None:
        """Add multiple items to the collection.

        Args:
            items: List of items to add

        Example:
            >>> collector.add_many([article1, article2, article3])
        """
        self._items.extend(items)

    def get_all(self) -> List[T]:
        """Get all collected items.

        Returns a copy of the internal list to prevent external modification.

        Returns:
            List of all collected items

        Example:
            >>> articles = collector.get_all()
            >>> print(f"Collected {len(articles)} articles")
        """
        return self._items.copy()

    def clear(self) -> None:
        """Clear all collected items.

        Use this to reset the collector for a new pipeline run while
        reusing the same collector instance.

        Example:
            >>> collector.clear()  # Reset before new run
            >>> agent.run("Collect more articles...")
            >>> new_articles = collector.get_all()
        """
        self._items.clear()

    def count(self) -> int:
        """Get the number of collected items.

        Returns:
            Number of items in the collection

        Example:
            >>> print(f"Collected {collector.count()} items so far")
        """
        return len(self._items)

    def is_empty(self) -> bool:
        """Check if the collector is empty.

        Returns:
            True if no items have been collected, False otherwise

        Example:
            >>> if collector.is_empty():
            ...     print("No items collected yet")
        """
        return len(self._items) == 0

    def get_last(self) -> Optional[T]:
        """Get the most recently added item.

        Returns:
            The last item added, or None if collector is empty

        Example:
            >>> last_article = collector.get_last()
            >>> if last_article:
            ...     print(f"Latest: {last_article.title}")
        """
        return self._items[-1] if self._items else None

    def __len__(self) -> int:
        """Support len() builtin.

        Returns:
            Number of collected items

        Example:
            >>> print(len(collector))
        """
        return len(self._items)

    def __bool__(self) -> bool:
        """Support bool() builtin.

        Returns:
            True if collector has items, False if empty

        Example:
            >>> if collector:
            ...     print("Has items!")
        """
        return bool(self._items)

    def __iter__(self):
        """Support iteration over collected items.

        Yields:
            Items in the collection

        Example:
            >>> for article in collector:
            ...     print(article.title)
        """
        return iter(self._items)

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            Debug string showing type and count

        Example:
            >>> print(collector)
            ResultCollector[Article](count=5)
        """
        type_name = getattr(T, "__name__", "T")
        return f"ResultCollector[{type_name}](count={len(self._items)})"
