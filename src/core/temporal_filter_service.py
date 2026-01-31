"""Unified temporal filtering service for articles, events, and other entities.

This service provides consistent temporal filtering logic across the codebase,
eliminating duplication between article_analysis.py and event_analysis.py.
"""

from typing import List, Optional, Tuple, Union, TYPE_CHECKING
from datetime import datetime, timedelta

from src.utils.date_utils import ensure_timezone_aware

if TYPE_CHECKING:
    from src.domain.models import Article, Event


class TemporalFilterService:
    """Service for temporal filtering of entities with timestamps.

    Provides unified logic for:
    - Calculating evidence collection windows
    - Filtering entities by time windows
    - Filtering entities by cutoff dates
    """

    @staticmethod
    def get_evidence_window(
        resolution_date: datetime,
        estimated_start_time: Optional[datetime] = None,
        fallback_window_days: int = 365,
    ) -> Tuple[Optional[datetime], datetime]:
        """Calculate the evidence collection time window for a question.

        Uses a two-tier approach:
        1. If question has estimated_start_time: use [estimated_start_time, resolution_date]
        2. Fallback: use [resolution_date - fallback_window_days, resolution_date]

        Args:
            resolution_date: Question resolution date (end of window)
            estimated_start_time: Optional question/market start time (preferred start)
            fallback_window_days: Days to look back if no estimated_start_time (default: 365)

        Returns:
            Tuple of (window_start, window_end) where:
            - window_start: Start of evidence window (None means no start limit)
            - window_end: End of evidence window (always resolution_date)
        """
        window_end = ensure_timezone_aware(resolution_date)

        if estimated_start_time:
            # Use question's explicit time window
            window_start = ensure_timezone_aware(estimated_start_time)
        else:
            # Fallback to configured lookback window
            window_start = window_end - timedelta(days=fallback_window_days)

        return window_start, window_end

    @staticmethod
    def filter_by_window(
        items: List[Union["Article", "Event"]],
        window_start: Optional[datetime],
        window_end: datetime,
        date_field: str = "published_date",
    ) -> List[Union["Article", "Event"]]:
        """Filter items to those within a time window.

        Items are considered valid if:
        - Date is after window_start (if provided)
        - Date is before window_end (strictly before) - excludes items at/after window_end

        Args:
            items: List of items to filter (Articles or Events)
            window_start: Start of window (None means no start limit)
            window_end: End of window (items must be strictly before this)
            date_field: Name of the date field to filter by (default: "published_date")

        Returns:
            List of items within the time window
        """
        window_end = ensure_timezone_aware(window_end)
        window_start = ensure_timezone_aware(window_start) if window_start else None

        filtered_items = []
        for item in items:
            # Get the date field from the item
            item_date = getattr(item, date_field, None)
            if not item_date:
                continue

            # Normalize item date for comparison
            item_date = ensure_timezone_aware(item_date)

            # Must be before window_end (strictly before)
            if item_date >= window_end:
                continue

            # Must be after window_start (if defined)
            if window_start and item_date < window_start:
                continue

            filtered_items.append(item)

        return filtered_items

    @staticmethod
    def filter_by_cutoff(
        items: List[Union["Article", "Event"]],
        cutoff_date: datetime,
        date_field: str = "published_date",
    ) -> List[Union["Article", "Event"]]:
        """Filter items to those before a cutoff date.

        This is a simplified version of filter_by_window that only applies
        an upper bound (no lower bound).

        Args:
            items: List of items to filter (Articles or Events)
            cutoff_date: Cutoff date (items must be strictly before this)
            date_field: Name of the date field to filter by (default: "published_date")

        Returns:
            List of items before the cutoff date
        """
        cutoff_date = ensure_timezone_aware(cutoff_date)

        filtered_items = []
        for item in items:
            # Get the date field from the item
            item_date = getattr(item, date_field, None)
            if not item_date:
                continue

            # Normalize item date for comparison
            item_date = ensure_timezone_aware(item_date)

            # Must be before cutoff (strictly before)
            if item_date < cutoff_date:
                filtered_items.append(item)

        return filtered_items
