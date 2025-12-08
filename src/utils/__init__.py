"""Utilities for WorldReasoner."""

from .logging import logger, setup_logging
from .similarity import (
    calculate_text_similarity,
    calculate_combined_similarity,
    find_similar_item,
    find_similar_items,
    SimilarityMatcher,
)

# Note: question_filters not imported here to avoid circular import
# Import directly: from src.utils.question_filters import filter_questions

__all__ = [
    "logger",
    "setup_logging",
    "calculate_text_similarity",
    "calculate_combined_similarity",
    "find_similar_item",
    "find_similar_items",
    "SimilarityMatcher",
]
