"""Reusable question filtering utilities.

Provides filtering functions for questions based on type, category,
quality requirements, and temporal constraints. Extracted from
pipeline-specific code for reusability across the codebase.
"""

from typing import List, Optional, Dict, Union
from datetime import datetime, timezone

from src.domain.models import Question
from src.config.collection_goal import QualityRequirements
from src.utils.logging import logger


def filter_questions_by_type(
    questions: List[Question],
    allowed_types: List[str],
) -> List[Question]:
    """Filter questions by question type.

    Args:
        questions: Questions to filter
        allowed_types: List of allowed question types (e.g., ["boolean", "mcq"])

    Returns:
        Filtered list of questions
    """
    logger.debug(f"Filtering by types: {allowed_types}")
    logger.debug(f"Question types in input: {set(q.question_type for q in questions)}")
    return [q for q in questions if q.question_type in allowed_types]


def filter_questions_by_category(
    questions: List[Question],
    category_filter: Union[Dict[str, int], List[str]],
) -> List[Question]:
    """Filter questions by category.

    Args:
        questions: Questions to filter
        category_filter: Either:
            - Dict mapping categories to counts (e.g., {"finance": 1, "tech": 2})
            - List of allowed categories (e.g., ["finance", "tech"])
            - Can contain Domain enum objects (will be converted to strings)

    Returns:
        Filtered list of questions
    """
    from src.domain.models.domain import Domain

    if isinstance(category_filter, dict):
        allowed_categories = category_filter.keys()
    else:
        allowed_categories = category_filter
    logger.debug(f"Filtering by categories: {allowed_categories}")
    logger.debug(f"Question categories in input: {set(q.domain for q in questions)}")
    # Convert Domain enums to strings for comparison
    allowed_categories_strs = set()
    for cat in allowed_categories:
        if isinstance(cat, Domain):
            allowed_categories_strs.add(cat.value)
        else:
            allowed_categories_strs.add(str(cat))

    return [q for q in questions if q.domain in allowed_categories_strs]


def apply_quality_requirements(
    questions: List[Question],
    requirements: QualityRequirements,
) -> List[Question]:
    """Apply quality filters to questions.

    Filters based on:
    - Difficulty range
    - Resolution criteria presence
    - Resolution date range (for unresolved questions)

    Args:
        questions: Questions to filter
        requirements: Quality requirements to apply

    Returns:
        Questions meeting quality requirements
    """
    filtered = []
    now = datetime.now(timezone.utc)

    # Track skip reasons for logging
    skip_difficulty = 0
    skip_criteria = 0
    skip_date_too_old = 0
    skip_date_too_recent = 0

    for question in questions:
        # Check difficulty
        if question.difficulty:
            if not (
                requirements.min_difficulty
                <= question.difficulty
                <= requirements.max_difficulty
            ):
                skip_difficulty += 1
                continue

        # Check resolution criteria
        if requirements.require_resolution_criteria:
            if not question.resolution_criteria:
                skip_criteria += 1
                continue

        # Check resolution date range
        # Skip date filtering for questions with ground truth (already resolved)
        has_ground_truth = question.ground_truth is not None
        if question.resolution_date and not has_ground_truth:
            days_until_resolution = (question.resolution_date - now).days

            if days_until_resolution < requirements.min_resolution_days:
                skip_date_too_old += 1
                logger.debug(
                    f"Filtered {question.id}: too old "
                    f"({days_until_resolution} days < {requirements.min_resolution_days})"
                )
                continue

            if days_until_resolution > requirements.max_resolution_days:
                skip_date_too_recent += 1
                logger.debug(
                    f"Filtered {question.id}: too recent "
                    f"({days_until_resolution} days > {requirements.max_resolution_days})"
                )
                continue

        filtered.append(question)

    # Log summary if any questions were processed
    if questions:
        logger.info(
            f"Quality filter: {len(filtered)}/{len(questions)} kept, "
            f"skipped: {skip_difficulty} difficulty, {skip_criteria} criteria, "
            f"{skip_date_too_old} too old, {skip_date_too_recent} too recent"
        )

    return filtered


def filter_questions(
    questions: List[Question],
    type_filter: Optional[List[str]] = None,
    category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
    quality_requirements: Optional[QualityRequirements] = None,
) -> List[Question]:
    """Apply multiple filters to questions in sequence.

    Convenience function that applies type, category, and quality filters.

    Args:
        questions: Questions to filter
        type_filter: Allowed question types
        category_filter: Dict mapping categories to counts OR list of categories
        quality_requirements: Quality constraints

    Returns:
        Filtered list of questions
    """
    filtered = questions
    logger.info(
        f"category_filter: {category_filter}, type_filter: {type_filter}, quality_requirements: {quality_requirements}"
    )
    # Filter by type
    if type_filter:
        filtered = filter_questions_by_type(filtered, type_filter)

    # Filter by category
    if category_filter:
        filtered = filter_questions_by_category(filtered, category_filter)

    # Filter by quality requirements
    if quality_requirements:
        filtered = apply_quality_requirements(filtered, quality_requirements)

    return filtered


def filter_resolved_questions(
    questions: List[Question],
    resolved_only: bool = True,
) -> List[Question]:
    """Filter questions by resolution status.

    Args:
        questions: Questions to filter
        resolved_only: If True, only return resolved questions with ground_truth

    Returns:
        Filtered list of questions
    """
    if resolved_only:
        return [q for q in questions if q.ground_truth is not None]
    return [q for q in questions if q.ground_truth is None]


def filter_by_quality_score(
    questions: List[Question],
    min_score: float,
) -> List[Question]:
    """Filter questions by minimum quality score.

    Args:
        questions: Questions to filter
        min_score: Minimum quality score threshold

    Returns:
        Questions with quality_score >= min_score
    """
    return [q for q in questions if (q.quality_score or 0.0) >= min_score]


def tag_questions_with_source(
    questions: List[Question],
    source_name: str,
) -> None:
    """Tag questions with source metadata.

    Modifies questions in place by:
    1. Setting the question.source field
    2. Adding "source" to metadata dict
    3. Setting "category" from domain if not present

    Args:
        questions: Questions to tag (modified in place)
        source_name: Source identifier (e.g., "polymarket", "news")
    """
    for question in questions:
        # Set the source field on the question
        question.source = source_name

        # Initialize metadata if needed
        if not hasattr(question, "metadata") or question.metadata is None:
            question.metadata = {}

        # Add source to metadata
        if "source" not in question.metadata:
            question.metadata["source"] = source_name

        # Set category from domain for progress tracking
        if "category" not in question.metadata:
            question.metadata["category"] = question.domain.value
