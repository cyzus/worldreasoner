"""Questions API endpoints.

Provides REST API for querying forecast questions.
"""

from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

from src.core.database import GenericDatabase
from src.domain.models import Question, CausalHypothesis
from src.utils.logging import logger


router = APIRouter()


# Dependency for getting database
def get_database() -> GenericDatabase:
    """Dependency to get database instance."""
    return GenericDatabase("worldreasoner.db")


class QuestionListItem(BaseModel):
    """Simplified question model for list views."""
    id: str
    question_text: str
    question_type: str
    domain: str
    difficulty: int
    source: str
    target_event_id: Optional[str]
    related_event_ids: List[str]


@router.get("/", response_model=List[QuestionListItem])
async def get_questions(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    db: GenericDatabase = Depends(get_database),
):
    """Get all questions with optional filtering.

    Args:
        domain: Optional domain filter

    Returns:
        List of questions
    """
    try:
        # Get all questions
        filters = {}
        if domain:
            filters['domain'] = domain

        questions = db.get_many(Question, filters=filters if filters else None)

        # Convert to simplified response model
        result = [
            QuestionListItem(
                id=q.id,
                question_text=q.question_text,
                question_type=q.question_type.value,
                domain=q.domain.value,
                difficulty=q.difficulty,
                source=q.source,
                target_event_id=q.target_event_id,
                related_event_ids=q.related_event_ids,
            )
            for q in questions
        ]

        logger.info(f"Returning {len(result)} questions")
        return result

    except Exception as e:
        logger.error(f"Failed to fetch questions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}", response_model=QuestionListItem)
async def get_question(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get a single question by ID.

    Args:
        question_id: Question identifier

    Returns:
        Question data
    """
    try:
        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")
        return QuestionListItem(
            id=question.id,
            question_text=question.question_text,
            question_type=question.question_type.value,
            domain=question.domain.value,
            difficulty=question.difficulty,
            source=question.source,
            target_event_id=question.target_event_id,
            related_event_ids=question.related_event_ids,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch question: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/events")
async def get_question_events(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get all events related to a question.

    This includes:
    - target_event_id from the question
    - related_event_ids from the question
    - All events extracted during evidence collection (via metadata)
    - All events from causal hypotheses discovered by this question

    Args:
        question_id: Question identifier

    Returns:
        Event IDs and statistics
    """
    try:
        from src.domain.models import Event

        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

        # Start with events directly referenced by question
        event_ids = set()
        if question.target_event_id:
            event_ids.add(question.target_event_id)
        event_ids.update(question.related_event_ids)

        direct_event_count = len(event_ids)

        # Find all events extracted during evidence collection (via metadata)
        all_events = db.get_many(Event)
        extracted_events = set()
        for event in all_events:
            related_q_ids = event.metadata.get('related_question_ids', [])
            if question_id in related_q_ids:
                extracted_events.add(event.id)
                event_ids.add(event.id)

        # Find all causal hypotheses discovered by this question
        all_hypotheses = db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses
            if question_id in h.discovered_by_question_ids
        ]

        # Extract all source and target events from these hypotheses
        hypothesis_events = set()
        for hypothesis in question_hypotheses:
            hypothesis_events.add(hypothesis.source_event_id)
            hypothesis_events.add(hypothesis.target_event_id)
            event_ids.add(hypothesis.source_event_id)
            event_ids.add(hypothesis.target_event_id)

        # Calculate orphaned events (extracted but not in hypotheses)
        orphaned_events = extracted_events - hypothesis_events

        logger.info(
            f"Question {question_id}: "
            f"{direct_event_count} direct events, "
            f"{len(extracted_events)} extracted during evidence, "
            f"{len(hypothesis_events)} in hypotheses, "
            f"{len(orphaned_events)} orphaned, "
            f"{len(event_ids)} total events"
        )

        return {
            "question_id": question_id,
            "event_ids": list(event_ids),
            "total_events": len(event_ids),
            "direct_events": direct_event_count,
            "extracted_events": len(extracted_events),
            "hypothesis_events": len(hypothesis_events),
            "orphaned_events": len(orphaned_events),
            "hypotheses_count": len(question_hypotheses),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch question events: {e}")
        raise HTTPException(status_code=500, detail=str(e))
