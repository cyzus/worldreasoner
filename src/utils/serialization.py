"""Serialization utilities for common patterns."""

from typing import Any, Optional


def serialize_enum(enum_value: Any) -> str:
    """Serialize an enum value to string.

    Handles both Enum instances and plain strings/values.
    This eliminates the repeated pattern of:
    `value.value if hasattr(value, 'value') else value`

    Args:
        enum_value: Enum instance or plain value

    Returns:
        String representation of the value

    Examples:
        >>> from src.utils.enums import Domain
        >>> serialize_enum(Domain.POLITICS)
        'politics'
        >>> serialize_enum('politics')
        'politics'
    """
    if hasattr(enum_value, "value"):
        return enum_value.value
    return str(enum_value) if enum_value is not None else None


def serialize_domain(domain: Any) -> Optional[str]:
    """Serialize a domain value to string.

    Convenience wrapper for serialize_enum specifically for Domain fields.

    Args:
        domain: Domain enum or string value

    Returns:
        String representation of the domain
    """
    return serialize_enum(domain)
