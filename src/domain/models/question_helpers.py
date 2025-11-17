"""Helper functions for Question model temporal analysis."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List
from .question import Question
from .event import Event
from .article import Article


def calculate_forecast_context_window(
    question: Question,
    events: Optional[List[Event]] = None,
    articles: Optional[List[Article]] = None,
    db=None,
    min_context_items: int = 3
) -> Tuple[datetime, datetime]:
    """Calculate the valid temporal window for making a forecast on this question.

    The forecast window is bounded by:
    - MIN: When sufficient context becomes available (Nth earliest context item)
    - MAX: When the answer becomes known (resolution_date)

    Instead of requiring ALL context (which could mean waiting until 1 day before resolution),
    this uses a threshold approach: the window opens when you have at least N context items
    (events/articles) available. This is more realistic for forecasting scenarios.

    Args:
        question: The forecast question
        events: Optional list of related events (if None, fetches from DB using related_event_ids)
        articles: Optional list of context articles (if None, fetches from DB)
        db: Database instance (required if events/articles not provided)
        min_context_items: Minimum number of context items needed to start forecasting (default: 3)
                          E.g., if 3, window opens when 3rd article/event is published

    Returns:
        (earliest_valid_date, latest_valid_date) tuple

    Raises:
        ValueError: If insufficient data to calculate window

    Example:
        >>> # Opens when 3rd context item available (default)
        >>> window_start, window_end = calculate_forecast_context_window(question, db=db)
        >>>
        >>> # Opens when 5th context item available (more conservative)
        >>> window_start, window_end = calculate_forecast_context_window(question, db=db, min_context_items=5)
        >>>
        >>> # Opens when 1st context item available (most aggressive)
        >>> window_start, window_end = calculate_forecast_context_window(question, db=db, min_context_items=1)
    """
    # The latest you can forecast is 1 second before resolution
    window_end = question.resolution_date - timedelta(seconds=1)

    # Find the earliest you can forecast based on context availability
    context_dates = []

    # Helper to ensure timezone-aware datetimes
    def ensure_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    # 1. Get related events (these must have occurred before forecasting)
    if events is None and db is not None and question.related_event_ids:
        from src.core.database import GenericDatabase
        if not isinstance(db, GenericDatabase):
            from src.core.database import GenericDatabase
            db = GenericDatabase(db) if isinstance(db, str) else db

        for event_id in question.related_event_ids:
            event = db.get(Event, event_id)
            if event and event.occurred_date:
                context_dates.append(ensure_aware(event.occurred_date))
    elif events:
        for event in events:
            if event.occurred_date:
                context_dates.append(ensure_aware(event.occurred_date))

    # 2. Get context articles (for evidence-based questions)
    # Articles tagged with this question ID provide necessary background
    if articles is None and db is not None:
        from src.core.database import GenericDatabase
        if not isinstance(db, GenericDatabase):
            from src.core.database import GenericDatabase
            db = GenericDatabase(db) if isinstance(db, str) else db

        # Find articles that reference this question
        all_articles = db.get_many(Article)
        question_articles = [
            a for a in all_articles
            if 'related_question_ids' in a.metadata
            and question.id in a.metadata['related_question_ids']
        ]

        for article in question_articles:
            if article.published_date:
                context_dates.append(ensure_aware(article.published_date))
    elif articles:
        for article in articles:
            if article.published_date:
                context_dates.append(ensure_aware(article.published_date))

    # The earliest you can forecast is after sufficient context becomes available
    if context_dates:
        # Sort dates chronologically
        sorted_dates = sorted(context_dates)

        # Use the Nth date (where N = min_context_items)
        # If we have fewer items than the threshold, use the latest one
        if len(sorted_dates) >= min_context_items:
            window_start = sorted_dates[min_context_items - 1]  # 0-indexed, so 3rd item is index 2
        else:
            # Fewer than minimum items - use latest available (fall back to conservative approach)
            window_start = sorted_dates[-1]
    else:
        # No explicit context - default to 30 days before resolution
        # (This is a heuristic for questions without identified context events)
        window_start = window_end - timedelta(days=30)

    # Sanity check: window must be valid
    if window_start >= window_end:
        raise ValueError(
            f"Invalid forecast window for question {question.id}: "
            f"context available at {window_start} but resolution at {window_end}"
        )

    return window_start, window_end


def validate_simulated_date(
    question: Question,
    simulated_date: datetime,
    db=None,
    min_context_items: int = 3
) -> Tuple[bool, Optional[str]]:
    """Validate if a simulated date is appropriate for forecasting this question.

    Args:
        question: The forecast question
        simulated_date: The proposed simulation date
        db: Database instance for fetching context

    Returns:
        (is_valid, error_message) tuple
        - is_valid: True if simulated_date is in valid forecast window
        - error_message: None if valid, otherwise explanation string

    Example:
        >>> valid, error = validate_simulated_date(question, datetime(2025, 11, 3), db)
        >>> if not valid:
        >>>     print(f"Invalid simulated date: {error}")
    """
    try:
        window_start, window_end = calculate_forecast_context_window(
            question, db=db, min_context_items=min_context_items
        )
    except ValueError as e:
        return False, str(e)

    # Check if simulated date is within window
    if simulated_date < window_start:
        return False, (
            f"Simulated date {simulated_date.date()} is too early. "
            f"Required context not available until {window_start.date()}. "
            f"Valid window: [{window_start.date()}, {window_end.date()})"
        )

    if simulated_date >= window_end:
        return False, (
            f"Simulated date {simulated_date.date()} is too late. "
            f"Question resolves at {window_end.date()}. "
            f"Valid window: [{window_start.date()}, {window_end.date()})"
        )

    return True, None


def suggest_simulated_date(
    question: Question,
    db=None,
    offset_days_before_resolution: int = 7,
    min_context_items: int = 3
) -> datetime:
    """Suggest an appropriate simulated date for forecasting this question.

    Picks a date that:
    - Is after all context is available
    - Is some days before resolution (configurable buffer)
    - Falls within the valid forecast window

    Args:
        question: The forecast question
        db: Database instance for fetching context
        offset_days_before_resolution: How many days before resolution to suggest (default: 7)

    Returns:
        Suggested simulated datetime

    Example:
        >>> simulated_date = suggest_simulated_date(question, db=db, offset_days_before_resolution=14)
    """
    window_start, window_end = calculate_forecast_context_window(
        question, db=db, min_context_items=min_context_items
    )

    # Try to suggest offset_days before resolution
    suggested = window_end - timedelta(days=offset_days_before_resolution)

    # But ensure it's after context is available
    if suggested < window_start:
        # Use 1 day after context becomes available
        suggested = window_start + timedelta(days=1)

    # Make sure we didn't overshoot
    if suggested >= window_end:
        # Use midpoint of window
        suggested = window_start + (window_end - window_start) / 2

    return suggested
