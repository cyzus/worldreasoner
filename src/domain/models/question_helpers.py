"""Helper functions for Question model temporal analysis."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple, List
from .question import Question
from .event import Event
from .article import Article
from src.utils.logging import logger
from src.core.database import ensure_database



class ForecastSlot(str, Enum):
    """Named positions within a question's forecast window.

    Each slot maps to a fraction of the window span measured from window_start:

        window_start ──── early ──── mid ──── late ──── window_end
                      20%         50%        80%

    Using fractional positions (rather than fixed day-offsets) ensures
    consistent relative difficulty across short-, medium-, and long-range
    questions.
    """

    EARLY = "early"  # 20% into window — plenty of context missing
    MID = "mid"  # 50% into window — balanced (default)
    LATE = "late"  # 80% into window — most context available


#: Mapping from ForecastSlot to fraction of window elapsed from window_start.
SLOT_FRACTIONS: dict = {
    ForecastSlot.EARLY: 0.20,
    ForecastSlot.MID: 0.50,
    ForecastSlot.LATE: 0.80,
}


# Minimum effective forecast window used for slot placement.
# If context-derived windows are too narrow (e.g., all context appears just before
# resolution), we backfill window_start so early/mid/late remain meaningful.
MIN_EFFECTIVE_SLOT_WINDOW_DAYS = 7


def get_forecast_date_for_slot(
    question: Question,
    slot: ForecastSlot = ForecastSlot.MID,
) -> dict:
    """Return a simulated date at a fractional position within the forecast window.

    The window is defined by ``question.estimated_start_time`` (open) and
    ``question.resolution_date`` (close), so slot positions are independent of
    when supporting articles or events happen to exist in the database.

    Args:
        question: The forecast question.
        slot: Named position within the window (EARLY / MID / LATE).

    Returns:
        dict with keys:
            - ``simulated_date``: The chosen datetime.
            - ``window_start``: When the forecast window opens.
            - ``window_end``: When the forecast window closes (just before resolution).
            - ``slot``: The slot name used (string).
            - ``horizon_days``: Total number of days in the forecast window.

    Raises:
        ValueError: If the window cannot be computed.

    Example:
        >>> setup = get_forecast_date_for_slot(question, ForecastSlot.MID)
        >>> agent = ForecastAgent(question, simulated_date=setup['simulated_date'])
    """
    window_start, window_end = calculate_forecast_context_window(question)

    # Ensure slots remain meaningful even when context arrives very late.
    # Without this guard, a ~1 day window makes early/mid/late nearly identical.
    min_window_start = window_end - timedelta(days=MIN_EFFECTIVE_SLOT_WINDOW_DAYS)
    effective_window_start = window_start
    if window_start > min_window_start:
        effective_window_start = min_window_start
        logger.warning(
            f"Question {question.id} has narrow context window "
            f"({window_start.date()} -> {window_end.date()}); "
            f"expanding slot window start to {effective_window_start.date()} "
            f"for stable slot behavior"
        )

    span = window_end - effective_window_start
    fraction = SLOT_FRACTIONS[slot]
    simulated_date = effective_window_start + span * fraction

    logger.info(
        f"Forecast slot '{slot.value}' for question {question.id}: "
        f"simulated_date={simulated_date.date()} "
        f"(window {effective_window_start.date()} → {window_end.date()}, "
        f"{span.days}d span, {fraction * 100:.0f}% elapsed)"
    )

    return {
        "simulated_date": simulated_date,
        "window_start": effective_window_start,
        "window_end": window_end,
        "slot": slot.value,
        "horizon_days": span.days,
    }


def calculate_forecast_context_window(
    question: Question,
) -> Tuple[datetime, datetime]:
    """Return the forecast window for a question.

    The window is simply ``[estimated_start_time, resolution_date)``.
    Using the question's own temporal fields (rather than the dates of supporting
    articles or events) prevents the window from being pushed into the distant past
    by articles that predate the question.

    Falls back to ``created_at`` when ``estimated_start_time`` is not set, or to
    30 days before resolution when ``created_at`` is after the resolution date
    (e.g. questions imported retroactively).

    Args:
        question: The forecast question.

    Returns:
        ``(window_start, window_end)`` tuple (both timezone-aware UTC).

    Raises:
        ValueError: If the resulting window is invalid (start >= end).
    """

    def _ensure_aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    window_end = _ensure_aware(question.resolution_date) - timedelta(seconds=1)

    if question.estimated_start_time is not None:
        window_start = _ensure_aware(question.estimated_start_time)
    else:
        # Prefer created_at — the earliest a user of this system could have
        # forecast — but only when it precedes resolution (historical/imported
        # questions can have created_at > resolution_date).
        candidate = _ensure_aware(question.created_at)
        if candidate < window_end:
            window_start = candidate
            logger.warning(
                f"Question {question.id} has no estimated_start_time; "
                f"falling back to created_at ({window_start.date()}) as window_start"
            )
        else:
            # created_at is after resolution — question was imported retroactively.
            # Use 30 days before resolution as a last-resort heuristic.
            window_start = window_end - timedelta(days=30)
            logger.warning(
                f"Question {question.id} has no estimated_start_time and "
                f"created_at ({candidate.date()}) >= window_end ({window_end.date()}); "
                f"defaulting window_start to 30 days before resolution ({window_start.date()})"
            )

    if window_start >= window_end:
        raise ValueError(
            f"Invalid forecast window for question {question.id}: "
            f"window_start={window_start} >= window_end={window_end}"
        )

    return window_start, window_end


def validate_simulated_date(
    question: Question,
    simulated_date: datetime,
    window_start: datetime,
    window_end: datetime,
) -> Tuple[bool, Optional[str]]:
    """Validate if a simulated date is within a forecast window.

    This is a lightweight validation helper that just checks bounds.
    Use prepare_forecast_context() for the full setup workflow.

    Args:
        question: The forecast question
        simulated_date: The proposed simulation date
        window_start: Start of valid forecast window
        window_end: End of valid forecast window

    Returns:
        (is_valid, error_message) tuple
        - is_valid: True if simulated_date is in valid forecast window
        - error_message: None if valid, otherwise explanation string

    Example:
        >>> window_start, window_end = calculate_forecast_context_window(question, db)
        >>> valid, error = validate_simulated_date(question, datetime(2025, 11, 3), window_start, window_end)
        >>> if not valid:
        >>>     print(f"Invalid simulated date: {error}")
    """
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
    window_start: datetime,
    window_end: datetime,
    offset_days_before_resolution: int = 7,
) -> datetime:
    """Suggest an appropriate simulated date within a forecast window.

    This is a lightweight helper that picks a good date within bounds.
    Use prepare_forecast_context() for the full setup workflow.

    The offset_days_before_resolution is a HARD REQUIREMENT - the simulated date
    will always be at least that many days before resolution, regardless of context
    availability. This ensures proper temporal separation for forecasting.

    Args:
        question: The forecast question
        window_start: Start of valid forecast window
        window_end: End of valid forecast window
        offset_days_before_resolution: How many days before resolution to use (default: 7)
                                       This is enforced as a minimum requirement.

    Returns:
        Suggested simulated datetime (guaranteed to be offset_days before resolution)

    Raises:
        ValueError: If offset_days would place simulated date before window_start
                   and the gap is significant (>7 days)

    Example:
        >>> window_start, window_end = calculate_forecast_context_window(question, db)
        >>> simulated_date = suggest_simulated_date(question, window_start, window_end, offset_days_before_resolution=14)
    """
    # HARD REQUIREMENT: simulated date must be AT LEAST offset_days before resolution
    # This means we can forecast further out if needed (for data availability), but never closer
    max_date = question.resolution_date - timedelta(days=offset_days_before_resolution)

    if window_start <= max_date:
        suggested = max_date
    else:
        actual_offset_days = (question.resolution_date - window_start).days
        raise ValueError(
            f"Cannot satisfy minimum offset_days={offset_days_before_resolution} requirement. "
            f"Context not available until {window_start}, which is only {actual_offset_days} days "
            f"before resolution at {question.resolution_date}. Question needs earlier context items."
        )

    return suggested


def prepare_forecast_context(
    question: Question,
    db=None,
    offset_days_before_resolution: int = 0,
    min_context_items: int = 3,
) -> dict:
    """Get all information needed to forecast a question (hides complexity).

    This single function handles all the setup with a single pass:
    - Calculates valid forecast window
    - Suggests appropriate simulated date
    - Validates the setup
    - Returns everything needed

    This eliminates redundant calls to calculate_forecast_context_window.

    Args:
        question: The forecast question
        db: Database instance for fetching context
        offset_days_before_resolution: How many days before resolution to simulate (default: 0)
        min_context_items: Minimum number of context items needed (default: 3)

    Returns:
        dict with keys:
            - window_start: When forecasting window opens
            - window_end: When forecasting window closes
            - simulated_date: Suggested date to use for forecast
            - days_available: Number of days in forecast window

    Raises:
        ValueError: If insufficient context or invalid configuration

    Example:
        >>> setup = prepare_forecast_context(question, db, offset_days_before_resolution=7)
        >>> agent = ForecastAgent(question, simulated_date=setup['simulated_date'])
    """
    # Calculate forecast window (single pass)
    window_start, window_end = calculate_forecast_context_window(question)

    # Suggest simulated date based on window
    simulated_date = suggest_simulated_date(
        question, window_start, window_end, offset_days_before_resolution
    )

    # Validate the setup
    valid, error = validate_simulated_date(
        question, simulated_date, window_start, window_end
    )
    if not valid:
        raise ValueError(f"Invalid forecast setup: {error}")

    # Count how many context items are available at the suggested date
    context_count = 0
    event_count = 0
    article_count = 0

    if db is not None:
        db = ensure_database(db)

        # Count events available at simulated_date
        if question.related_event_ids:
            for event_id in question.related_event_ids:
                event = db.get(Event, event_id)
                if event and event.occurred_date:
                    occurred = event.occurred_date
                    if occurred.tzinfo is None:
                        occurred = occurred.replace(tzinfo=timezone.utc)
                    if occurred <= simulated_date:
                        event_count += 1

        # Count articles available at simulated_date
        all_articles = db.get_many(Article)
        question_articles = [
            a
            for a in all_articles
            if "related_question_ids" in a.metadata
            and question.id in a.metadata["related_question_ids"]
        ]
        for article in question_articles:
            if article.published_date:
                published = article.published_date
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published <= simulated_date:
                    article_count += 1

        context_count = event_count + article_count

    logger.info(
        f"Forecast context for question {question.id}: "
        f"{context_count} items available at suggested date {simulated_date.date()} "
        f"({event_count} events, {article_count} articles)"
    )

    return {
        "window_start": window_start,
        "window_end": window_end,
        "simulated_date": simulated_date,
        "days_available": (window_end - window_start).days,
        "context_count": context_count,
        "event_count": event_count,
        "article_count": article_count,
    }
