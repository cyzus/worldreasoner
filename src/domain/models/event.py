"""Event data model - represents discrete occurrences in causal graphs."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict
from ...core.database import register_model
from .domain import Domain


class EventType(str, Enum):
    """Classification of event types."""

    DECISION = "decision"  # Policy decision, corporate action, etc.
    OUTCOME = "outcome"  # Election result, product launch, etc.
    INDICATOR = "indicator"  # Economic indicator, poll result, etc.
    MILESTONE = "milestone"  # Deadline, scheduled event, etc.
    EXTERNAL_SHOCK = "external_shock"  # Natural disaster, crisis, etc.


class EventStatus(str, Enum):
    """Current status of the event."""

    PREDICTED = "predicted"  # Forecast target (hasn't occurred yet)
    OCCURRED = "occurred"  # Confirmed occurrence
    CANCELLED = "cancelled"  # Event cancelled/didn't happen
    UNCERTAIN = "uncertain"  # Unclear if occurred


class CausalRelationType(str, Enum):
    """Type of causal relationship between events."""

    CAUSES = "causes"  # Direct causation
    ENABLES = "enables"  # Makes possible (binary prerequisite)
    PREVENTS = "prevents"  # Completely blocks or stops
    INHIBITS = "inhibits"  # Reduces likelihood or intensity
    AMPLIFIES = "amplifies"  # Increases intensity or severity
    TRIGGERS = "triggers"  # Causes immediate or sudden onset
    CORRELATES = "correlates"  # Associated but not causal
    CONDITIONAL = "conditional"  # Causes only if conditions met


class OutcomeScenario(str, Enum):
    """Scenario type for outcome events."""

    POSITIVE_RESOLUTION = "positive_resolution"  # "Yes" / positive outcome
    NEGATIVE_RESOLUTION = "negative_resolution"  # "No" / negative outcome
    MCQ_OPTION = "mcq_option"  # Multiple choice option
    DISCOVERED = "discovered"  # Edge-case outcomes created outside normal flow


class ReviewStatus(str, Enum):
    """Human review status for agent-generated events."""

    PENDING = "pending"  # Not yet reviewed (default)
    APPROVED = "approved"  # Verified as accurate
    REJECTED = "rejected"  # Inaccurate or hallucinated
    REVISED = "revised"  # Approved after manual correction


@register_model(
    "events",
    indexes=[
        "domain",
        "status",
        "event_type",
        "extracted_for_question_id",
        "is_outcome",
        "outcome_scenario",
        "review_status",
    ],
)
class Event(BaseModel):
    """Discrete occurrence or state change in the world.

    Events are nodes in the causal graph. They can cause other events,
    be caused by other events, and are documented by articles.
    """

    # Core identification
    id: str = Field(..., description="Unique event identifier")
    title: str = Field(..., min_length=5, max_length=300)
    description: str = Field(
        ..., min_length=20, description="Detailed description of the event"
    )

    # Classification
    event_type: EventType = Field(..., description="Type of event")
    domain: Domain = Field(..., description="Primary domain")
    tags: List[str] = Field(default_factory=list, description="Topic tags")

    # Temporal information
    occurred_date: Optional[datetime] = Field(
        None, description="When event occurred (None if predicted/future)"
    )
    predicted_date: Optional[datetime] = Field(
        None, description="When event is predicted to occur"
    )
    resolution_date: Optional[datetime] = Field(
        None, description="When event status was resolved/confirmed"
    )

    # Status
    status: EventStatus = Field(
        default=EventStatus.PREDICTED, description="Current status of the event"
    )

    # Documentation
    article_ids: List[str] = Field(
        default_factory=list, description="Articles that document or discuss this event"
    )

    # Provenance tracking (for evidence pipeline)
    extracted_for_question_id: Optional[str] = Field(
        None,
        description="Question ID this event was extracted for during evidence pipeline (None if pre-existing)",
    )
    source_article_id: Optional[str] = Field(
        None,
        description="Article ID this event was extracted from (for events created during evidence pipeline)",
    )

    # Metadata
    is_synthetic: bool = Field(
        default=False, description="Whether event is part of synthetic dataset"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event-specific metadata (entities, custom fields, etc.)",
    )

    # Outcome event fields
    is_outcome: bool = Field(
        default=False,
        description="True if this event represents a possible outcome scenario",
    )
    outcome_scenario: Optional[OutcomeScenario] = Field(
        None, description="Type of outcome scenario (only for is_outcome=True)"
    )
    outcome_option_index: Optional[int] = Field(
        None, description="Option index for MCQ outcomes (0-based)"
    )
    is_actual_outcome: Optional[bool] = Field(
        None,
        description="True if this outcome actually occurred (set after resolution)",
    )

    # Human review
    review_status: ReviewStatus = Field(
        default=ReviewStatus.PENDING,
        description="Human review status (pending/approved/rejected/revised)",
    )
    review_note: Optional[str] = Field(
        None,
        description="Optional reviewer note explaining approval/rejection reason",
    )

    # Audit
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    def get_outgoing_links(self, db) -> List["CausalHypothesis"]:
        """Get all causal hypotheses where this event is the source (cause).

        Args:
            db: Database instance (GenericDatabase)

        Returns:
            List of outgoing CausalHypothesis objects
        """
        from .causal_hypothesis import CausalHypothesis

        return db.get_many(CausalHypothesis, filters={"source_event_id": self.id})

    def get_incoming_links(self, db) -> List["CausalHypothesis"]:
        """Get all causal hypotheses where this event is the target (effect).

        Args:
            db: Database instance (GenericDatabase)

        Returns:
            List of incoming CausalHypothesis objects
        """
        from .causal_hypothesis import CausalHypothesis

        return db.get_many(CausalHypothesis, filters={"target_event_id": self.id})

    def get_all_links(self, db) -> Dict[str, List["CausalHypothesis"]]:
        """Get both outgoing and incoming causal hypotheses.

        Args:
            db: Database instance (GenericDatabase)

        Returns:
            Dict with 'outgoing' and 'incoming' keys containing hypothesis lists
        """
        return {
            "outgoing": self.get_outgoing_links(db),
            "incoming": self.get_incoming_links(db),
        }

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "evt_pol_20241105_001",
                "title": "2024 US Presidential Election Result",
                "description": "The outcome of the 2024 United States presidential election determining the 47th president",
                "event_type": "outcome",
                "domain": "politics",
                "tags": ["election", "presidential", "usa"],
                "occurred_date": "2024-11-05T23:00:00Z",
                "resolution_date": "2024-11-06T08:00:00Z",
                "status": "occurred",
                "article_ids": [
                    "art_pol_20241020_001",
                    "art_pol_20241105_123",
                    "art_pol_20241106_001",
                ],
                "metadata": {
                    "candidates": ["Candidate A", "Candidate B"],
                    "swing_states": ["Pennsylvania", "Michigan", "Wisconsin"],
                },
            }
        }
    )
