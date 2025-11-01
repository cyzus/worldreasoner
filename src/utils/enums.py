"""Enum utility functions."""

from enum import Enum
from typing import List


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
