"""Utility functions for loading and validating questions."""

from typing import List, Optional
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.utils.logging import logger


def load_specific_question(db_path: str, question_id: str) -> Optional[List[Question]]:
    """Load a specific question by ID and validate it's ready for processing.

    Args:
        db_path: Path to database
        question_id: Question ID to load

    Returns:
        List containing the question if found and valid, None otherwise
    """
    db = GenericDatabase(db_path)
    question = db.get(Question, question_id)

    if not question:
        logger.error(f"Question {question_id} not found in database")
        return None

    if not question.resolution_date or question.ground_truth is None:
        logger.error(
            f"Question {question_id} is not resolved (missing resolution_date or ground_truth)"
        )
        return None

    logger.info(f"Found question {question_id}: {question.title[:80]}...")
    return [question]
