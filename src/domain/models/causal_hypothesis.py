"""Causal hypothesis model - proposed causal explanations from LLM analysis."""

from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field

from .event import CausalRelationType
from ...core.database import register_model


@register_model('causal_hypotheses', indexes=['target_event_id', 'confidence', 'strength'])
class CausalHypothesis(BaseModel):
    """A proposed causal explanation extracted by LLM with hindsight.

    CausalHypothesis is an intermediate validation layer between LLM output
    and permanent CausalLink objects in the event graph. This allows for
    quality control, deduplication, and consistency checks before committing
    causal relationships to the graph.
    """

    # Core identification
    id: str = Field(..., description="Unique hypothesis identifier")

    # Causal relationship
    source_event_id: str = Field(
        ...,
        description="Event ID of the cause"
    )
    target_event_id: str = Field(
        ...,
        description="Event ID of the effect (the outcome)"
    )
    relation_type: CausalRelationType = Field(
        default=CausalRelationType.CAUSES,
        description="Type of causal relationship"
    )

    # Confidence and strength
    strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strength of the causal effect (0-1)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in this causal link (0-1)"
    )

    # Explanation and evidence
    reasoning: str = Field(
        ...,
        min_length=10,
        description="LLM's explanation of the causal mechanism"
    )
    evidence_article_ids: List[str] = Field(
        default_factory=list,
        description="Articles that support this causal claim"
    )

    # Context
    question_id: str = Field(
        ...,
        description="Question that triggered this analysis"
    )

    # Metadata
    identified_by: str = Field(
        default="evidence_pipeline",
        description="Source of this hypothesis (pipeline, manual, etc.)"
    )
    identified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this hypothesis was generated"
    )

    # Validation status
    validated: bool = Field(
        default=False,
        description="Whether this hypothesis has been validated and added to graph"
    )
    validation_notes: str = Field(
        default="",
        description="Notes from validation process"
    )

    def meets_thresholds(
        self,
        min_confidence: float = 0.6,
        min_strength: float = 0.3
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

    def mark_validated(self, notes: str = "") -> None:
        """Mark hypothesis as validated and added to graph.

        Args:
            notes: Optional validation notes
        """
        self.validated = True
        self.validation_notes = notes
