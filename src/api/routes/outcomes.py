"""Outcome Impact API endpoints.

Provides REST API for querying outcome events and their impacts.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.routes.database import get_current_db_path
from src.core.database import GenericDatabase
from src.domain.models.event import Event
from src.services.graph import GraphEdge, GraphNode, SQLiteGraphService
from src.services.outcome_event_service import OutcomeEventService
from src.utils.logging import logger


router = APIRouter()


# Dependency for getting graph service
def get_graph_service() -> SQLiteGraphService:
    """Dependency to get graph service instance."""
    return SQLiteGraphService(get_current_db_path())


# Dependency for getting outcome service
def get_outcome_service() -> OutcomeEventService:
    """Dependency to get outcome event service instance."""
    db = GenericDatabase(get_current_db_path())
    return OutcomeEventService(db)


@router.get("/questions/{question_id}/outcomes", response_model=List[GraphNode])
async def get_question_outcomes(
    question_id: str,
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get outcome events for a specific question.

    Args:
        question_id: Question ID

    Returns:
        List of outcome events as GraphNodes
    """
    try:
        outcomes = await graph_service.get_outcome_events(question_id)

        logger.info(
            f"Retrieved {len(outcomes)} outcome events for question {question_id}"
        )

        return outcomes

    except Exception as e:
        logger.error(f"Failed to get outcomes for question {question_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/outcomes/{outcome_id}")
async def get_outcome(
    outcome_id: str,
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get a single outcome event by ID.

    Args:
        outcome_id: Outcome event ID

    Returns:
        Outcome event details
    """
    try:
        node = await graph_service.get_node(outcome_id)

        if not node:
            raise HTTPException(
                status_code=404, detail=f"Outcome {outcome_id} not found"
            )

        # Verify it's actually an outcome
        if not node.properties.get("is_outcome"):
            raise HTTPException(
                status_code=400, detail=f"Event {outcome_id} is not an outcome event"
            )

        return node

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/outcomes/{outcome_id}/impacts", response_model=List[GraphEdge])
async def get_outcome_impacts(
    outcome_id: str,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    impact_direction: Optional[str] = Query(
        None, regex="^(positive|negative|neutral|mixed)$"
    ),
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get impact edges for a specific outcome event.

    Args:
        outcome_id: Outcome event ID
        min_confidence: Minimum confidence threshold
        impact_direction: Filter by direction (positive, negative, neutral, mixed)

    Returns:
        List of impact edges
    """
    try:
        # Verify outcome exists
        node = await graph_service.get_node(outcome_id)
        if not node:
            raise HTTPException(
                status_code=404, detail=f"Outcome {outcome_id} not found"
            )

        # Get impacts for this outcome
        impacts = await graph_service.get_impact_edges(
            outcome_event_id=outcome_id,
            min_confidence=min_confidence,
            impact_direction=impact_direction,
        )

        logger.info(
            f"Retrieved {len(impacts)} impacts for outcome {outcome_id} "
            f"(min_confidence={min_confidence}, direction={impact_direction})"
        )

        return impacts

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get impacts for outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/outcomes/{outcome_id}/mark-actual")
async def mark_actual_outcome(
    outcome_id: str,
    is_actual: bool = Query(..., description="Whether this is the actual outcome"),
    outcome_service: OutcomeEventService = Depends(get_outcome_service),
):
    """Mark an outcome event as the actual outcome.

    Args:
        outcome_id: Outcome event ID
        is_actual: Whether this is the actual outcome

    Returns:
        Success message
    """
    try:
        outcome_service.mark_actual_outcome(outcome_id, is_actual)

        logger.info(f"Marked outcome {outcome_id} as actual={is_actual}")

        return {
            "success": True,
            "outcome_id": outcome_id,
            "is_actual": is_actual,
            "message": f"Outcome marked as {'actual' if is_actual else 'not actual'}",
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to mark outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


_DIRECTION_SIGN: Dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
    "mixed": 0.0,
}


@router.get("/outcomes/{outcome_id}/trajectory")
async def get_outcome_trajectory(
    outcome_id: str,
    graph_service: SQLiteGraphService = Depends(get_graph_service),
) -> Dict[str, Any]:
    """Compute a chronological causal-pressure trajectory toward an outcome.

    For each event that has a recorded impact on this outcome, retrieves the
    event's occurred_date and computes a weighted contribution:

        contribution = sign(direction) × magnitude × confidence

    Returns points sorted by date with a running cumulative_pressure field,
    giving a time-series view of how evidence accumulated toward or against
    the outcome.

    Args:
        outcome_id: Outcome event ID

    Returns:
        trajectory: list of dated pressure points (sorted by date)
        summary: net_pressure, event_count, avg_confidence, dominant_direction
    """
    try:
        node = await graph_service.get_node(outcome_id)
        if not node:
            raise HTTPException(
                status_code=404, detail=f"Outcome {outcome_id} not found"
            )

        impacts = await graph_service.get_impact_edges(outcome_event_id=outcome_id)
        db = GenericDatabase(get_current_db_path())

        points: List[Dict[str, Any]] = []
        for impact in impacts:
            event = db.get(Event, impact.source_id)
            if not event:
                continue
            date = event.occurred_date or event.predicted_date
            if not date:
                continue

            direction = impact.properties.get("impact_direction", "neutral")
            magnitude = float(impact.properties.get("impact_magnitude", 0.0))
            confidence = float(impact.properties.get("confidence", 0.0))
            contribution = _DIRECTION_SIGN.get(direction, 0.0) * magnitude * confidence

            points.append(
                {
                    "date": date.isoformat(),
                    "event_id": event.id,
                    "event_title": event.title,
                    "direction": direction,
                    "magnitude": magnitude,
                    "confidence": confidence,
                    "weighted_contribution": round(contribution, 4),
                }
            )

        points.sort(key=lambda p: p["date"])
        cumulative = 0.0
        for point in points:
            cumulative += point["weighted_contribution"]
            point["cumulative_pressure"] = round(cumulative, 4)

        avg_confidence = (
            sum(p["confidence"] for p in points) / len(points) if points else 0.0
        )
        dominant = (
            "positive" if cumulative > 0 else "negative" if cumulative < 0 else "neutral"
        )

        logger.info(
            f"Computed trajectory for outcome {outcome_id}: "
            f"{len(points)} points, net_pressure={cumulative:.3f}"
        )

        return {
            "outcome_event_id": outcome_id,
            "trajectory": points,
            "summary": {
                "net_pressure": round(cumulative, 4),
                "event_count": len(points),
                "avg_confidence": round(avg_confidence, 4),
                "dominant_direction": dominant,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compute trajectory for outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{event_id}/impacts", response_model=List[GraphEdge])
async def get_event_impacts(
    event_id: str,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    impact_direction: Optional[str] = Query(
        None, regex="^(positive|negative|neutral|mixed)$"
    ),
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get impact edges from a specific event.

    Args:
        event_id: Source event ID
        min_confidence: Minimum confidence threshold
        impact_direction: Filter by direction (positive, negative, neutral, mixed)

    Returns:
        List of impact edges from this event
    """
    try:
        # Verify event exists
        node = await graph_service.get_node(event_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Get impacts from this event
        impacts = await graph_service.get_impact_edges(
            event_id=event_id,
            min_confidence=min_confidence,
            impact_direction=impact_direction,
        )

        logger.info(
            f"Retrieved {len(impacts)} impacts from event {event_id} "
            f"(min_confidence={min_confidence}, direction={impact_direction})"
        )

        return impacts

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get impacts from event {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
