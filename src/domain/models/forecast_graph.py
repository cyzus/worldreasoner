"""Models for forecast-specific causal graphs.

These models track events and causal hypotheses identified during forecasting,
separate from the main event graph. They are linked to forecasts via session_id
during reasoning and forecast_id after submission.
"""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field
from src.core.database import register_model
from src.domain.models.event import EventType, EventStatus, CausalRelationType
from src.utils.enums import Domain


@register_model("forecast_events", indexes=["forecast_id", "session_id", "domain"])
class ForecastEvent(BaseModel):
    """Event identified during forecasting.

    Represents an event that the forecasting agent identified as relevant
    to the prediction. Can either be a new event or a reference to an
    existing event in the main event graph.
    """

    id: str = Field(..., description="Event ID (reused from main graph or new)")
    forecast_id: Optional[str] = Field(
        None, description="Forecast ID (set after submission)"
    )
    session_id: str = Field(
        ..., description="Session ID for tracking during forecasting"
    )

    title: str = Field(..., description="Event title")
    description: str = Field(..., description="Event description")
    domain: Domain = Field(..., description="Event domain")
    occurred_date: Optional[datetime] = Field(
        None, description="When the event occurred"
    )
    event_type: Optional[EventType] = Field(None, description="Type of event")
    status: EventStatus = Field(EventStatus.OCCURRED, description="Event status")

    source_article_ids: List[str] = Field(
        default_factory=list, description="Article IDs supporting this event"
    )
    identified_by: str = Field(
        "forecast_agent", description="Who identified this event"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


@register_model(
    "forecast_hypotheses",
    indexes=["forecast_id", "session_id", "source_event_id", "target_event_id"],
)
class ForecastHypothesis(BaseModel):
    """Causal hypothesis from forecasting.

    Represents a causal relationship between two events as hypothesized
    by the forecasting agent during its reasoning process.
    """

    id: str = Field(..., description="Hypothesis ID")
    forecast_id: Optional[str] = Field(
        None, description="Forecast ID (set after submission)"
    )
    session_id: str = Field(
        ..., description="Session ID for tracking during forecasting"
    )

    source_event_id: str = Field(..., description="Source event ID (cause)")
    target_event_id: str = Field(..., description="Target event ID (effect)")
    relation_type: CausalRelationType = Field(
        ..., description="Type of causal relationship"
    )

    strength: float = Field(
        ..., ge=0.0, le=1.0, description="Relationship strength (0-1)"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in hypothesis (0-1)"
    )

    reasoning: str = Field(..., description="Explanation of the causal relationship")
    evidence_article_ids: List[str] = Field(
        default_factory=list, description="Article IDs supporting this hypothesis"
    )

    identified_by: str = Field(
        "forecast_agent", description="Who identified this hypothesis"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
