"""Datetime utilities with safe parsing."""

from datetime import datetime, timezone
from typing import Optional
from src.utils.logging import logger


def parse_iso_datetime(
    date_str: Optional[str], fallback: Optional[datetime] = None
) -> datetime:
    """
    Parse ISO datetime string with timezone handling.

    Args:
        date_str: ISO format datetime string (may include 'Z' suffix)
        fallback: Fallback datetime if parsing fails (default: current UTC time)

    Returns:
        Parsed datetime or fallback

    Examples:
        >>> parse_iso_datetime("2024-01-01T12:00:00Z")
        datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        >>> parse_iso_datetime(None)
        datetime.now(timezone.utc)
    """
    if not date_str:
        return fallback or datetime.now(timezone.utc)

    try:
        # Handle 'Z' suffix by replacing with +00:00
        normalized = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        # Ensure result is timezone-aware (treat naive as UTC)
        if dt.tzinfo is None:
            logger.debug(f"Datetime string '{date_str}' missing timezone, assuming UTC")
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError) as e:
        logger.warning(f"Failed to parse datetime '{date_str}': {e}")
        return fallback or datetime.now(timezone.utc)


def ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware (UTC if naive).

    Args:
        dt: Datetime to check

    Returns:
        Timezone-aware datetime (converted to UTC if naive)
    """
    if dt.tzinfo is None:
        logger.warning("Converting naive datetime to UTC")
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_flexible_datetime(
    date_str: Optional[str], fallback: Optional[datetime] = None
) -> datetime:
    """
    Parse datetime string that may be ISO datetime or date-only format.

    Handles both:
    - Full datetime: "2024-01-01T12:00:00Z" or "2024-01-01T12:00:00+00:00"
    - Date only: "2024-01-01" (assumes midnight UTC)

    Args:
        date_str: Datetime or date string to parse
        fallback: Fallback datetime if parsing fails (default: current UTC time)

    Returns:
        Parsed datetime or fallback

    Examples:
        >>> parse_flexible_datetime("2024-01-01T12:00:00Z")
        datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        >>> parse_flexible_datetime("2024-01-01")
        datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    """
    if not date_str:
        return fallback or datetime.now(timezone.utc)

    try:
        # Handle date-only format (no 'T' separator)
        if "T" not in date_str:
            # Add time component at midnight UTC
            date_str = f"{date_str}T00:00:00+00:00"

        # Handle 'Z' suffix by replacing with +00:00
        normalized = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Failed to parse datetime '{date_str}': {e}")
        return fallback or datetime.now(timezone.utc)


def validate_date_against_question_window(
    date: datetime,
    question_start_time: Optional[datetime],
    question_resolution_date: datetime,
    entity_type: str = "item",
) -> Optional[dict]:
    """
    Validate that a date falls within the question's valid time window.

    Returns None if valid, or a dict with error details if invalid.

    Args:
        date: The date to validate
        question_start_time: Optional question start time (estimated_start_time)
        question_resolution_date: Question resolution date
        entity_type: Type of entity being validated (e.g., "Article", "Event")

    Returns:
        None if valid, or dict with 'warnings' and 'recommendation' if invalid

    Examples:
        >>> from datetime import datetime, timezone
        >>> date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        >>> start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        >>> resolution = datetime(2024, 12, 1, tzinfo=timezone.utc)
        >>> validate_date_against_question_window(date, start, resolution, "Article")
        None  # Valid - within window

        >>> early_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
        >>> result = validate_date_against_question_window(early_date, start, resolution, "Article")
        >>> result is not None
        True
    """
    warning_messages = []

    # Ensure dates are timezone-aware for comparison
    date = ensure_timezone_aware(date)
    question_resolution_date = ensure_timezone_aware(question_resolution_date)
    if question_start_time:
        question_start_time = ensure_timezone_aware(question_start_time)

    # Check if date is before estimated_start_time
    if question_start_time and date < question_start_time:
        days_before = (question_start_time - date).days
        warning_messages.append(
            f"{entity_type} dated {days_before} days before question start time "
            f"({question_start_time.strftime('%Y-%m-%d')}). "
            f"This {entity_type.lower()} may not be relevant for forecasting this question."
        )

    # Check if date is after resolution_date
    if date >= question_resolution_date:
        days_after = (date - question_resolution_date).days
        warning_messages.append(
            f"{entity_type} dated {days_after} days after resolution date "
            f"({question_resolution_date.strftime('%Y-%m-%d')}). "
            f"This {entity_type.lower()} contains hindsight information and should not be used for evidence."
        )

    # If there are warnings, return error details
    if warning_messages:
        if question_start_time:
            recommended_window = (
                f"Recommended time window: "
                f"{question_start_time.strftime('%Y-%m-%d')} to "
                f"{question_resolution_date.strftime('%Y-%m-%d')}"
            )
        else:
            recommended_window = (
                f"Recommended: {entity_type.lower()}s dated before "
                f"{question_resolution_date.strftime('%Y-%m-%d')}"
            )

        return {
            "warnings": warning_messages,
            "recommendation": recommended_window,
            "date": date.isoformat(),
            "question_start": question_start_time.isoformat()
            if question_start_time
            else None,
            "question_resolution": question_resolution_date.isoformat(),
        }

    return None
