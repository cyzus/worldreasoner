"""Events API endpoints.

Provides REST API for querying event details.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from src.core.database import GenericDatabase
from src.domain.models import Event, Article, Question
from src.api.routes.database import get_current_db_path
from src.utils.logging import logger


router = APIRouter()


def get_db() -> GenericDatabase:
    """Get database instance with current database path."""
    return GenericDatabase(get_current_db_path())


@router.get("/{event_id}")
async def get_event(event_id: str):
    """Get detailed event information.

    Args:
        event_id: Event identifier

    Returns:
        Full event data including causal links
    """
    try:
        db = get_db()
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_events(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List events with pagination.

    Args:
        domain: Optional domain filter
        limit: Maximum number of events to return
        offset: Pagination offset

    Returns:
        List of events
    """
    try:
        db = get_db()

        filters = {}
        if domain:
            filters["domain"] = domain

        events = db.get_many(Event, filters=filters)

        # Manual pagination
        total = len(events)
        events = events[offset : offset + limit]

        return {
            "events": events,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(f"List events failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/articles")
async def get_event_articles(event_id: str):
    """Get all articles related to an event.

    Args:
        event_id: Event identifier

    Returns:
        List of articles that document or discuss this event
    """
    try:
        db = get_db()
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Do a reverse lookup: find all articles that reference this event in their event_ids
        all_articles = db.get_many(Article)
        related_articles = [
            article for article in all_articles if event_id in article.event_ids
        ]

        # Also check event.article_ids for backward compatibility
        for article_id in event.article_ids:
            article = db.get(Article, article_id)
            if article and article not in related_articles:
                related_articles.append(article)

        logger.info(f"Found {len(related_articles)} articles for event {event_id}")
        return {"articles": related_articles, "total": len(related_articles)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event articles failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/questions")
async def get_event_questions(event_id: str):
    """Get all questions related to an event.

    Args:
        event_id: Event identifier

    Returns:
        List of questions that reference this event (as target or related event)
        or were linked via evidence pipeline/causal hypotheses
    """
    try:
        from src.domain.models import CausalHypothesis

        db = get_db()
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Fetch all questions
        all_questions = db.get_many(Question)

        # 1. Direct references: questions with this event as target or related
        directly_related = [
            q
            for q in all_questions
            if event_id in (q.outcome_event_ids or [])
            or q.target_event_id == event_id
            or event_id in q.related_event_ids
        ]

        # 2. Reverse lookup: questions that discovered this event via evidence pipeline
        # Use explicit provenance field with fallback to metadata
        evidence_related = []
        for q in all_questions:
            # Skip if already found
            if q in directly_related:
                continue
            # Check if this event was extracted for this question
            if event.extracted_for_question_id == q.id:
                evidence_related.append(q)
            # Fallback to metadata for pre-migration data
            elif (
                event.metadata.get("related_question_ids")
                and q.id in event.metadata["related_question_ids"]
            ):
                evidence_related.append(q)

        # 3. Causal hypothesis links: find questions linked via hypotheses
        all_hypotheses = db.get_many(CausalHypothesis)
        hypothesis_question_ids = set()
        for h in all_hypotheses:
            # Check if event is source or target of causal relationship
            if event_id == h.source_event_id or event_id == h.target_event_id:
                # Add all questions that discovered this hypothesis
                hypothesis_question_ids.update(h.discovered_by_question_ids)

        hypothesis_related = [
            q for q in all_questions if q.id in hypothesis_question_ids
        ]

        # Combine and deduplicate
        seen_ids = set()
        related_questions = []
        for q in directly_related + evidence_related + hypothesis_related:
            if q.id not in seen_ids:
                related_questions.append(q)
                seen_ids.add(q.id)

        logger.info(
            f"Found {len(related_questions)} questions for event {event_id} "
            f"(direct={len(directly_related)}, evidence={len(evidence_related)}, "
            f"hypothesis={len(hypothesis_related)})"
        )
        return {"questions": related_questions, "total": len(related_questions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event questions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/review")
async def review_event(event_id: str):
    """Review a single event using the EventReviewService."""
    try:
        from src.services.event_review_service import EventReviewService
        from src.domain.models import ReviewStatus
        import datetime

        db = get_db()
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        service = EventReviewService(db)
        
        # Build question context if possible
        question_context = "No question context available"
        if event.extracted_for_question_id:
            question = db.get(Question, event.extracted_for_question_id)
            if question:
                question_context = service._build_question_context(question)

        # Run review
        review = await service._review_single_event(event, question_context)

        # Update event status
        if review.approved:
            event.review_status = ReviewStatus.APPROVED
        else:
            event.review_status = ReviewStatus.REJECTED

        event.review_note = f"LLM Review: {review.reasoning[:200]}"
        event.updated_at = datetime.datetime.now(datetime.timezone.utc)
        
        db.save(Event, event)

        return {
            "status": "success",
            "review_status": event.review_status,
            "approved": review.approved,
            "reasoning": review.reasoning
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Review event failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
