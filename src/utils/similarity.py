"""Generic similarity matching utilities for deduplication across models."""

import re
from typing import List, Optional, TypeVar, Callable, Any
from pydantic import BaseModel

from src.utils.logging import logger


T = TypeVar("T", bound=BaseModel)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts.

    Uses word overlap (Jaccard index) for simple, fast similarity calculation.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score 0.0-1.0
    """
    if not text1 or not text2:
        return 0.0

    # Normalize: lowercase, remove punctuation, split into words
    def normalize(text: str) -> set:
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        return set(word for word in text.split() if len(word) > 2)

    words1 = normalize(text1)
    words2 = normalize(text2)

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0


def calculate_combined_similarity(
    item1: Any,
    item2: Any,
    fields: List[tuple[str, float]],
) -> float:
    """Calculate weighted similarity across multiple fields.

    Args:
        item1: First item (dict or object with attributes)
        item2: Second item (dict or object with attributes)
        fields: List of (field_name, weight) tuples

    Returns:
        Weighted similarity score 0.0-1.0
    """
    total_weight = sum(weight for _, weight in fields)
    if total_weight == 0:
        return 0.0

    weighted_score = 0.0

    for field_name, weight in fields:
        # Get values from dict or object
        if isinstance(item1, dict):
            val1 = item1.get(field_name, "")
        else:
            val1 = getattr(item1, field_name, "")

        if isinstance(item2, dict):
            val2 = item2.get(field_name, "")
        else:
            val2 = getattr(item2, field_name, "")

        # Convert to string for comparison
        val1 = str(val1) if val1 else ""
        val2 = str(val2) if val2 else ""

        score = calculate_text_similarity(val1, val2)
        weighted_score += score * weight

    return weighted_score / total_weight


def find_similar_item(
    candidates: List[T],
    target_text: str,
    text_field: str = "title",
    similarity_threshold: float = 0.6,
    additional_filter: Optional[Callable[[T], bool]] = None,
) -> Optional[T]:
    """Find the most similar item from candidates based on text similarity.

    Args:
        candidates: List of candidate items to search
        target_text: Text to match against
        text_field: Field name to compare (default: "title")
        similarity_threshold: Minimum similarity to consider a match (0.0-1.0)
        additional_filter: Optional filter function to pre-filter candidates

    Returns:
        Best matching item or None if no match above threshold
    """
    if not candidates or not target_text:
        return None

    best_match = None
    best_score = 0.0

    for item in candidates:
        # Apply additional filter if provided
        if additional_filter and not additional_filter(item):
            continue

        # Get the text field value
        if isinstance(item, dict):
            item_text = item.get(text_field, "")
        else:
            item_text = getattr(item, text_field, "")

        if not item_text:
            continue

        score = calculate_text_similarity(target_text, str(item_text))

        if score > best_score and score >= similarity_threshold:
            best_score = score
            best_match = item

    if best_match:
        logger.debug(f"Found similar item with score {best_score:.2f}")

    return best_match


def find_similar_items(
    candidates: List[T],
    target_text: str,
    text_field: str = "title",
    similarity_threshold: float = 0.6,
    max_results: int = 5,
    additional_filter: Optional[Callable[[T], bool]] = None,
) -> List[tuple[T, float]]:
    """Find all similar items above threshold, sorted by similarity.

    Args:
        candidates: List of candidate items to search
        target_text: Text to match against
        text_field: Field name to compare (default: "title")
        similarity_threshold: Minimum similarity to consider a match (0.0-1.0)
        max_results: Maximum number of results to return
        additional_filter: Optional filter function to pre-filter candidates

    Returns:
        List of (item, score) tuples sorted by score descending
    """
    if not candidates or not target_text:
        return []

    matches = []

    for item in candidates:
        # Apply additional filter if provided
        if additional_filter and not additional_filter(item):
            continue

        # Get the text field value
        if isinstance(item, dict):
            item_text = item.get(text_field, "")
        else:
            item_text = getattr(item, text_field, "")

        if not item_text:
            continue

        score = calculate_text_similarity(target_text, str(item_text))

        if score >= similarity_threshold:
            matches.append((item, score))

    # Sort by score descending and limit results
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:max_results]


class SimilarityMatcher:
    """Generic similarity matcher for deduplicating model instances.

    Example usage:
        matcher = SimilarityMatcher(
            db=database,
            model_class=Event,
            text_fields=[("title", 0.7), ("description", 0.3)],
            similarity_threshold=0.7,
        )

        existing = matcher.find_match(
            title="Fed raises rates",
            description="Federal Reserve increases interest rates",
            filters={"domain": "finance"}
        )
    """

    def __init__(
        self,
        db,
        model_class: type,
        text_fields: List[tuple[str, float]],
        similarity_threshold: float = 0.7,
    ):
        """Initialize the similarity matcher.

        Args:
            db: Database instance (GenericDatabase)
            model_class: The model class to search (e.g., Event)
            text_fields: List of (field_name, weight) for similarity calculation
            similarity_threshold: Minimum combined similarity score (0.0-1.0)
        """
        self.db = db
        self.model_class = model_class
        self.text_fields = text_fields
        self.similarity_threshold = similarity_threshold

    def find_match(
        self,
        filters: Optional[dict] = None,
        additional_filter: Optional[Callable[[T], bool]] = None,
        **target_values,
    ) -> Optional[T]:
        """Find matching item in database.

        Args:
            filters: Database query filters (e.g., {"domain": "tech"})
            additional_filter: Python filter function for complex conditions
            **target_values: Field values to match (e.g., title="...", description="...")

        Returns:
            Best matching item or None
        """
        # Get candidates from database
        candidates = self.db.get_many(self.model_class, filters=filters or {})

        if not candidates:
            return None

        best_match = None
        best_score = 0.0

        for item in candidates:
            # Apply additional filter
            if additional_filter and not additional_filter(item):
                continue

            # Calculate combined similarity
            score = calculate_combined_similarity(target_values, item, self.text_fields)

            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = item

        if best_match:
            logger.debug(
                f"Found matching {self.model_class.__name__} with score {best_score:.2f}: "
                f"{getattr(best_match, 'id', 'unknown')}"
            )

        return best_match

    def find_matches(
        self,
        max_results: int = 5,
        filters: Optional[dict] = None,
        additional_filter: Optional[Callable[[T], bool]] = None,
        **target_values,
    ) -> List[tuple[T, float]]:
        """Find all matching items above threshold.

        Args:
            max_results: Maximum results to return
            filters: Database query filters
            additional_filter: Python filter function
            **target_values: Field values to match

        Returns:
            List of (item, score) tuples sorted by score descending
        """
        candidates = self.db.get_many(self.model_class, filters=filters or {})

        if not candidates:
            return []

        matches = []

        for item in candidates:
            if additional_filter and not additional_filter(item):
                continue

            score = calculate_combined_similarity(target_values, item, self.text_fields)

            if score >= self.similarity_threshold:
                matches.append((item, score))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:max_results]
