"""Event data model - represents discrete occurrences in causal graphs."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict
from ...utils.database import register_model


class EventType(str, Enum):
    """Classification of event types."""
    DECISION = "decision"  # Policy decision, corporate action, etc.
    OUTCOME = "outcome"    # Election result, product launch, etc.
    INDICATOR = "indicator"  # Economic indicator, poll result, etc.
    MILESTONE = "milestone"  # Deadline, scheduled event, etc.
    EXTERNAL_SHOCK = "external_shock"  # Natural disaster, crisis, etc.


class EventStatus(str, Enum):
    """Current status of the event."""
    PREDICTED = "predicted"      # Forecast target (hasn't occurred yet)
    OCCURRED = "occurred"        # Confirmed occurrence
    CANCELLED = "cancelled"      # Event cancelled/didn't happen
    UNCERTAIN = "uncertain"      # Unclear if occurred


class CausalRelationType(str, Enum):
    """Type of causal relationship between events."""
    CAUSES = "causes"              # Direct causation
    ENABLES = "enables"            # Makes possible
    PREVENTS = "prevents"          # Blocks or inhibits
    CORRELATES = "correlates"      # Associated but not causal
    CONDITIONAL = "conditional"    # Causes only if conditions met


class CausalLink(BaseModel):
    """Represents a directed causal relationship between events."""
    
    source_event_id: str = Field(..., description="Event that causes/influences")
    target_event_id: str = Field(..., description="Event that is caused/influenced")
    relation_type: CausalRelationType = Field(default=CausalRelationType.CAUSES)
    
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Strength of causal relationship (0-1)"
    )
    
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in this causal link (0-1)"
    )
    
    time_lag_hours: Optional[float] = Field(
        None,
        description="Typical time delay between cause and effect"
    )
    
    evidence_article_ids: List[str] = Field(
        default_factory=list,
        description="Articles that document this causal relationship"
    )
    
    reasoning: Optional[str] = Field(
        None,
        description="Explanation of the causal mechanism"
    )


@register_model('events', indexes=['domain', 'status', 'event_type'])
class Event(BaseModel):
    """Discrete occurrence or state change in the world.
    
    Events are nodes in the causal graph. They can cause other events,
    be caused by other events, and are documented by articles.
    """
    
    # Core identification
    id: str = Field(..., description="Unique event identifier")
    title: str = Field(..., min_length=5, max_length=300)
    description: str = Field(
        ..., 
        min_length=20,
        description="Detailed description of the event"
    )
    
    # Classification
    event_type: EventType = Field(..., description="Type of event")
    domain: str = Field(
        ..., 
        description="Primary domain: finance|politics|tech|health|climate"
    )
    tags: List[str] = Field(default_factory=list, description="Topic tags")
    
    # Temporal information
    occurred_date: Optional[datetime] = Field(
        None,
        description="When event occurred (None if predicted/future)"
    )
    predicted_date: Optional[datetime] = Field(
        None,
        description="When event is predicted to occur"
    )
    resolution_date: Optional[datetime] = Field(
        None,
        description="When event status was resolved/confirmed"
    )
    
    # Status
    status: EventStatus = Field(
        default=EventStatus.PREDICTED,
        description="Current status of the event"
    )
    
    # Causal relationships
    causes: List[CausalLink] = Field(
        default_factory=list,
        description="Events that this event causes (outgoing edges)"
    )
    caused_by_ids: List[str] = Field(
        default_factory=list,
        description="IDs of events that caused this event (incoming edges)"
    )
    
    # Documentation
    article_ids: List[str] = Field(
        default_factory=list,
        description="Articles that document or discuss this event"
    )
    
    # Outcome data (for resolved events)
    outcome_value: Optional[Any] = Field(
        None,
        description="Actual outcome value (for measurable events)"
    )
    outcome_verified: bool = Field(
        default=False,
        description="Whether outcome has been verified"
    )
    
    # Metadata
    is_synthetic: bool = Field(
        default=False,
        description="Whether event is part of synthetic dataset"
    )
    
    # Structured data
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named entities involved (people, orgs, places)"
    )
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event-specific metadata"
    )
    
    # Audit
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

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
                "causes": [
                    {
                        "source_event_id": "evt_pol_20241105_001",
                        "target_event_id": "evt_fin_20241106_001",
                        "relation_type": "causes",
                        "strength": 0.8,
                        "confidence": 0.9,
                        "evidence_article_ids": ["art_fin_20241106_042"],
                        "reasoning": "Election results typically cause immediate market reactions"
                    }
                ],
                "article_ids": [
                    "art_pol_20241020_001",
                    "art_pol_20241105_123",
                    "art_pol_20241106_001"
                ],
                "outcome_value": "Candidate A wins with 287 electoral votes",
                "outcome_verified": True,
                "entities": {
                    "candidates": ["Candidate A", "Candidate B"],
                    "swing_states": ["Pennsylvania", "Michigan", "Wisconsin"]
                }
            }
        }
    )

    def add_causal_link(
        self,
        target_event_id: str,
        relation_type: CausalRelationType = CausalRelationType.CAUSES,
        strength: float = 0.5,
        confidence: float = 0.5,
        reasoning: Optional[str] = None,
        evidence_article_ids: Optional[List[str]] = None
    ) -> None:
        """Add a causal link to another event.
        
        Args:
            target_event_id: ID of the event this event causes
            relation_type: Type of causal relationship
            strength: Strength of causal effect (0-1)
            confidence: Confidence in this causal link (0-1)
            reasoning: Explanation of causal mechanism
            evidence_article_ids: Articles documenting this relationship
        """
        link = CausalLink(
            source_event_id=self.id,
            target_event_id=target_event_id,
            relation_type=relation_type,
            strength=strength,
            confidence=confidence,
            reasoning=reasoning,
            evidence_article_ids=evidence_article_ids or []
        )
        self.causes.append(link)

    def mark_occurred(
        self,
        occurred_date: datetime,
        outcome_value: Optional[Any] = None
    ) -> None:
        """Mark event as occurred with outcome data.
        
        Args:
            occurred_date: When the event occurred
            outcome_value: The actual outcome/result
        """
        self.status = EventStatus.OCCURRED
        self.occurred_date = occurred_date
        self.resolution_date = datetime.now(timezone.utc)
        if outcome_value is not None:
            self.outcome_value = outcome_value
            self.outcome_verified = True

    def get_causal_descendants(self) -> List[str]:
        """Get all event IDs that this event directly causes.
        
        Returns:
            List of event IDs
        """
        return [link.target_event_id for link in self.causes]

    def get_evidence_articles(self) -> List[str]:
        """Get all article IDs that provide evidence for causal links.
        
        Returns:
            List of unique article IDs
        """
        evidence_ids = set(self.article_ids)
        for link in self.causes:
            evidence_ids.update(link.evidence_article_ids)
        return list(evidence_ids)

    def compute_importance(self) -> float:
        """Compute event importance from graph structure and metadata.
        
        Importance is derived from:
        - Number of causal effects (outgoing edges)
        - Strength of causal effects
        - Media coverage (article count)
        - Incoming causal links
        
        Returns:
            Importance score between 0 and 1
        """
        # Base score from outgoing causal effects
        outgoing_score = min(len(self.causes) * 0.15, 0.5)
        
        # Weighted by average strength of effects
        if self.causes:
            avg_strength = sum(link.strength for link in self.causes) / len(self.causes)
            outgoing_score *= avg_strength
        
        # Media coverage score
        article_score = min(len(self.article_ids) * 0.05, 0.3)
        
        # Incoming causal links (being caused by many events = important)
        incoming_score = min(len(self.caused_by_ids) * 0.1, 0.2)
        
        # Combine scores
        total_score = outgoing_score + article_score + incoming_score
        
        return min(total_score, 1.0)
