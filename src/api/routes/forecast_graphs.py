"""API routes for forecast causal graphs."""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel

from src.core.database import GenericDatabase
from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis
from src.api.routes.database import get_current_db_path

router = APIRouter()


class ForecastGraphResponse(BaseModel):
    """Response with forecast causal graph data."""

    forecast_id: str
    session_id: str
    events: List[Dict[str, Any]]
    hypotheses: List[Dict[str, Any]]


@router.get("/forecasts/{forecast_id}/graph", response_model=ForecastGraphResponse)
async def get_forecast_graph(forecast_id: str):
    """Get the causal graph for a forecast.

    Returns events and causal hypotheses identified during forecasting.
    """
    from src.domain.models.forecast import Forecast

    db = GenericDatabase(get_current_db_path())

    # Get forecast events by forecast_id
    events = db.get_many(ForecastEvent, filters={"forecast_id": forecast_id})
    hypotheses = db.get_many(ForecastHypothesis, filters={"forecast_id": forecast_id})

    # If no results by forecast_id, try session_id as fallback
    if not events and not hypotheses:
        # Get the forecast to find its session_id
        forecast = db.get(Forecast, forecast_id)
        if forecast and forecast.session_id:
            events = db.get_many(
                ForecastEvent, filters={"session_id": forecast.session_id}
            )
            hypotheses = db.get_many(
                ForecastHypothesis, filters={"session_id": forecast.session_id}
            )

    if not events and not hypotheses:
        raise HTTPException(
            status_code=404, detail=f"No graph data found for forecast {forecast_id}"
        )

    # Get session_id from first event or hypothesis
    session_id = None
    if events:
        session_id = events[0].session_id
    elif hypotheses:
        session_id = hypotheses[0].session_id

    # Also include the question's target event if it's referenced by hypotheses
    # This ensures all nodes that hypotheses reference are included
    from src.domain.models import Event

    referenced_event_ids = set()
    for hyp in hypotheses:
        referenced_event_ids.add(hyp.source_event_id)
        referenced_event_ids.add(hyp.target_event_id)

    existing_event_ids = {e.id for e in events}
    missing_event_ids = referenced_event_ids - existing_event_ids

    if missing_event_ids:
        # Fetch missing events from main events table
        for event_id in missing_event_ids:
            event = db.get(Event, event_id)
            if event:
                # Convert Event to ForecastEvent-like dict for consistency
                events.append(event)

    # Convert to dicts - handle both ForecastEvent and Event types
    events_data = []
    for e in events:
        event_dict = {
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "domain": e.domain.value if hasattr(e.domain, "value") else e.domain,
            "occurred_date": e.occurred_date.isoformat() if e.occurred_date else None,
            "event_type": e.event_type.value
            if e.event_type and hasattr(e.event_type, "value")
            else e.event_type
            if e.event_type
            else None,
            "status": e.status.value if hasattr(e.status, "value") else e.status,
            "source_article_ids": getattr(e, "source_article_ids", []),
            "identified_by": getattr(e, "identified_by", "unknown"),
            "created_at": e.created_at.isoformat(),
        }
        events_data.append(event_dict)

    hypotheses_data = [
        {
            "id": h.id,
            "source_event_id": h.source_event_id,
            "target_event_id": h.target_event_id,
            "relation_type": h.relation_type.value
            if hasattr(h.relation_type, "value")
            else h.relation_type,
            "strength": h.strength,
            "confidence": h.confidence,
            "reasoning": h.reasoning,
            "evidence_article_ids": h.evidence_article_ids,
            "identified_by": h.identified_by,
            "created_at": h.created_at.isoformat(),
        }
        for h in hypotheses
    ]

    return ForecastGraphResponse(
        forecast_id=forecast_id,
        session_id=session_id,
        events=events_data,
        hypotheses=hypotheses_data,
    )
