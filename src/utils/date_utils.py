"""Datetime utilities with safe parsing."""
from datetime import datetime, timezone
from typing import Optional
from src.utils.logging import logger


def parse_iso_datetime(
    date_str: Optional[str],
    fallback: Optional[datetime] = None
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
        normalized = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(normalized)
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