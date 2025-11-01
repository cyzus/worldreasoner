"""Domain classification for articles, events, and questions."""

from enum import Enum


class Domain(str, Enum):
    """Classification of content domains."""

    FINANCE = "finance"
    POLITICS = "politics"
    TECH = "tech"
    HEALTH = "health"
    CLIMATE = "climate"
    GENERAL = "general"
