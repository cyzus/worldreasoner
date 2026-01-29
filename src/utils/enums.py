"""Enum utility functions."""

from enum import Enum
from typing import List, Optional
from src.domain.models.event import Domain, EventType
from src.utils.logging import logger


def enum_to_list(enum_class: type[Enum]) -> List[str]:
    """Extract enum values as list for JSON schema.

    Args:
        enum_class: The Enum class to extract values from

    Returns:
        List of string values from the enum

    Example:
        >>> class Color(str, Enum):
        ...     RED = "red"
        ...     BLUE = "blue"
        >>> enum_to_list(Color)
        ['red', 'blue']
    """
    return [e.value for e in enum_class]


def parse_domain(
    domain_str: Optional[str], default: Optional[Domain] = None
) -> Optional[Domain]:
    """
    Parse domain string with fallback to default.

    Args:
        domain_str: Domain string to parse
        default: Default domain if parsing fails (None = no filter)

    Returns:
        Parsed Domain enum, default, or None (no filter)
    """
    if not domain_str:
        return default

    try:
        return Domain(domain_str.lower())
    except ValueError:
        logger.warning(f"Invalid domain '{domain_str}', ignoring domain filter")
        return default


def parse_event_type(
    event_type_str: Optional[str], default: EventType = EventType.INDICATOR
) -> EventType:
    """
    Parse event type string with fallback to default.

    Args:
        event_type_str: Event type string to parse
        default: Default event type if parsing fails

    Returns:
        Parsed EventType enum or default
    """
    if not event_type_str:
        return default

    try:
        return EventType(event_type_str.lower())
    except ValueError:
        logger.warning(
            f"Invalid event_type '{event_type_str}', using '{default.value}'"
        )
        return default
