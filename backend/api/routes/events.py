"""Events API endpoints.

Provides REST API for querying event details.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from src.core.database import GenericDatabase
from src.domain.models import Event
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
