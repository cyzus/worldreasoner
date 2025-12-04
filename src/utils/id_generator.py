"""Unified ID generation utilities."""
import uuid
from datetime import datetime
from src.domain.models.event import Domain


def generate_entity_id(
    entity_type: str,
    domain: Domain,
    date: datetime,
    counter: int
) -> str:
    """
    Generate unique entity ID with consistent format.

    Args:
        entity_type: Entity prefix (e.g., "art", "evt", "qst")
        domain: Domain enum value
        date: Date to include in ID
        counter: Sequential counter (0-based, will be formatted as 1-based)

    Returns:
        Formatted ID: {entity_type}_{domain}_{YYYYMMDD}_{counter:03d}_{random}

    Example:
        >>> generate_entity_id("art", Domain.TECH, datetime(2024,1,1), 0)
        "art_tech_20240101_001_a1b2c3d4"
    """
    date_str = date.strftime('%Y%m%d')
    suffix = uuid.uuid4().hex[:8]
    return f"{entity_type}_{domain.value}_{date_str}_{counter+1:03d}_{suffix}"


def generate_article_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate article ID."""
    return generate_entity_id("art", domain, date, counter)


def generate_event_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate event ID."""
    return generate_entity_id("evt", domain, date, counter)


def generate_question_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate question ID."""
    return generate_entity_id("qst", domain, date, counter)