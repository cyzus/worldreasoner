"""Causal hypothesis model - LLM-proposed causal relationships between events."""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from .event import CausalRelationType
from ...core.database import register_model


@register_model(
    "causal_hypotheses",
    indexes=["source_event_id", "target_event_id", "confidence", "strength"],
)
class CausalHypothesis(BaseModel):
    """LLM-proposed causal relationship between events.

    These represent causal relationships discovered through hindsight analysis.
    They are NOT validated against ground truth - confidence/strength scores are
    LLM estimates. Multiple analyses may discover the same relationship.

    This is the single source of truth for causal relationships in the graph.
    No separate "validated" links - these ARE the graph edges.
    """

    # Core identification
    id: str = Field(..., description="Unique hypothesis identifier")

    # Causal relationship
    source_event_id: str = Field(..., description="Event ID of the cause")
    target_event_id: str = Field(
        ..., description="Event ID of the effect (the outcome)"
    )
    relation_type: CausalRelationType = Field(
        default=CausalRelationType.CORRELATES, description="Type of causal relationship"
    )

    # Confidence and strength
    strength: float = Field(
        ..., le=1.0, description="Strength of the causal effect (-1 to 1)"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in this causal link (0-1)"
    )

    # Temporal characteristics
    time_lag_hours: Optional[float] = Field(
        None, description="Typical time delay between cause and effect"
    )

    # Explanation and evidence
    reasoning: str = Field(
        ..., min_length=1, description="LLM's explanation of the causal mechanism"
    )
    evidence_article_ids: List[str] = Field(
        default_factory=list, description="Articles that support this causal claim"
    )

    # Discovery tracking (can be discovered multiple times)
    discovered_by_question_ids: List[str] = Field(
        default_factory=list,
        description="Question IDs that led to discovering this relationship",
    )
    identified_by: str = Field(
        default="evidence_pipeline",
        description="Source of this hypothesis (pipeline, manual, etc.)",
    )
    first_identified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this hypothesis was first discovered",
    )
    last_confirmed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this hypothesis was most recently rediscovered",
    )

    def meets_thresholds(
        self, min_confidence: float = 0.6, min_strength: float = 0.3
    ) -> bool:
        """Check if hypothesis meets minimum quality thresholds.

        Args:
            min_confidence: Minimum confidence threshold
            min_strength: Minimum strength threshold

        Returns:
            True if hypothesis meets both thresholds
        """
        return self.confidence >= min_confidence and self.strength >= min_strength

    def has_evidence(self) -> bool:
        """Check if hypothesis cites evidence articles.

        Returns:
            True if at least one evidence article is cited
        """
        return len(self.evidence_article_ids) > 0

    def add_discovery(self, question_id: str) -> None:
        """Record that this hypothesis was discovered by another question.

        Updates last_confirmed_at and adds question_id if not already present.

        Args:
            question_id: Question ID that discovered this relationship
        """
        if question_id not in self.discovered_by_question_ids:
            self.discovered_by_question_ids.append(question_id)
        self.last_confirmed_at = datetime.now(timezone.utc)
