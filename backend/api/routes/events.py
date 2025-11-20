"""Events API endpoints.

Provides REST API for querying event details.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from src.core.database import GenericDatabase
from src.domain.models import Event, Article, Question
from src.utils.logging import logger


router = APIRouter()


@router.get("/{event_id}")
async def get_event(event_id: str):
    """Get detailed event information.

    Args:
        event_id: Event identifier

    Returns:
        Full event data including causal links
    """
    try:
        db = GenericDatabase("worldreasoner.db")
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
        db = GenericDatabase("worldreasoner.db")

        filters = {}
        if domain:
            filters["domain"] = domain

        events = db.get_many(Event, filters=filters)

        # Manual pagination
        total = len(events)
        events = events[offset:offset + limit]

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
        db = GenericDatabase("worldreasoner.db")
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Do a reverse lookup: find all articles that reference this event in their event_ids
        all_articles = db.get_many(Article)
        related_articles = [
            article for article in all_articles
            if event_id in article.event_ids
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
    """
    try:
        db = GenericDatabase("worldreasoner.db")
        event = db.get(Event, event_id)

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Fetch all questions
        all_questions = db.get_many(Question)

        # Filter questions that reference this event
        related_questions = [
            q for q in all_questions
            if q.target_event_id == event_id or event_id in q.related_event_ids
        ]

        logger.info(f"Found {len(related_questions)} questions for event {event_id}")
        return {"questions": related_questions, "total": len(related_questions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event questions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
