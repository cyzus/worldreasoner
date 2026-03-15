"""Event-to-Outcome Impact data model - tracks how events affect outcome likelihoods."""

from enum import Enum
from typing import List
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, ConfigDict
from ...core.database import register_model


class ImpactDirection(str, Enum):
    """Direction of event's impact on outcome likelihood."""

    POSITIVE = "positive"  # Makes outcome MORE likely
    NEGATIVE = "negative"  # Makes outcome LESS likely
    NEUTRAL = "neutral"  # No clear directional impact
    MIXED = "mixed"  # Complex/contradictory effects


@register_model(
    "event_outcome_impacts",
    indexes=[
        "event_id",
        "outcome_event_id",
        "question_id",
        "impact_direction",
        "confidence",
    ],
)
class EventOutcomeImpact(BaseModel):
    """Tracks how an event directly impacts an outcome event's likelihood.

    This complements event→event causal chains by directly assessing
    whether an event makes a specific outcome more or less likely.

    Example: "Fed rate hike" (event) → "Recession occurs" (outcome event)
                Impact: POSITIVE, magnitude: 0.7

    Note: Both event_id and outcome_event_id reference the events table.
    Outcome events have is_outcome=True.
    """

    id: str = Field(..., description="Unique impact identifier (uuid)")

    # Core relationship (both are Events)
    event_id: str = Field(..., description="Event that has the impact")
    outcome_event_id: str = Field(
        ..., description="Outcome event being impacted (is_outcome=True)"
    )
    question_id: str = Field(..., description="Question for context/filtering")

    # Impact characteristics
    impact_direction: ImpactDirection = Field(
        ...,
        description="Direction: POSITIVE (increases likelihood), NEGATIVE (decreases), NEUTRAL, MIXED",
    )
    impact_magnitude: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strength of impact (0.0 to 1.0). Direction/sign is stored separately in impact_direction.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in this assessment (0.0=uncertain to 1.0=certain)",
    )

    # Explanation and evidence
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Detailed explanation of WHY and HOW this event impacts the outcome",
    )
    evidence_article_ids: List[str] = Field(
        default_factory=list,
        description="Article IDs supporting this impact assessment",
    )

    # Optional link to causal chain
    causal_chain_hypothesis_ids: List[str] = Field(
        default_factory=list,
        description="Optional: CausalHypothesis IDs showing event→outcome causal path",
    )

    # Discovery tracking (can be discovered multiple times)
    discovered_by_question_ids: List[str] = Field(
        default_factory=list,
        description="Question analyses that discovered/confirmed this impact",
    )
    identified_by: str = Field(
        default="evidence_pipeline",
        description="Source: evidence_pipeline, forecast_session, manual, etc.",
    )
    first_identified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_confirmed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("impact_magnitude")
    @classmethod
    def validate_magnitude(cls, v: float, info) -> float:
        """Ensure neutral impacts have low magnitude."""
        impact_direction = info.data.get("impact_direction")
        if impact_direction == ImpactDirection.NEUTRAL and v > 0.3:
            raise ValueError("Neutral impacts should have magnitude ≤ 0.3")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "impact_abc123",
                "event_id": "evt_pol_20240315_001",
                "outcome_event_id": "evt_outcome_yes_q123",
                "question_id": "q123",
                "impact_direction": "positive",
                "impact_magnitude": 0.7,
                "confidence": 0.8,
                "reasoning": "Higher inflation rates increase pressure on the Fed to raise interest rates to combat rising prices",
                "evidence_article_ids": ["art_fin_20240315_042"],
                "causal_chain_hypothesis_ids": ["hyp_abc", "hyp_def"],
                "discovered_by_question_ids": ["q123"],
                "identified_by": "hindsight_agent",
                "first_identified_at": "2024-03-15T10:30:00Z",
                "last_confirmed_at": "2024-03-15T10:30:00Z",
            }
        }
    )
