"""Structured outputs exchanged with construction agents."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.domain.models import (
    CausalRelationType,
    Domain,
    EventCandidate,
    EventType,
    ExplanationSection,
    ImpactDirection,
)


class GeneratedQuestionDraft(BaseModel):
    """One resolved forecasting question proposed from source reporting."""

    question_text: str = Field(min_length=20)
    question_type: str
    domain: str
    difficulty: int = Field(ge=1, le=5)
    resolution_date: datetime
    estimated_start_time: datetime
    resolution_criteria: str
    ground_truth: str
    resolution_reasoning: str
    context: Optional[str] = None
    options: List[str] = Field(default_factory=list)
    source_article_ids: List[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """One bounded evidence-search query and its purpose."""

    query: str
    rationale: str


class SearchPlanDraft(BaseModel):
    """Queries intended to recover outcome and causal-chain evidence."""

    queries: List[SearchQuery] = Field(min_length=2, max_length=6)
    intended_coverage: List[str] = Field(default_factory=list)


class CoverageAssessmentDraft(BaseModel):
    """Model assessment consumed alongside deterministic readiness gates."""

    ready: bool
    covered_aspects: List[str] = Field(default_factory=list)
    missing_evidence_needs: List[str] = Field(default_factory=list)
    rationale: str


class ExplanationDraft(BaseModel):
    """Human-readable explanation plus graph-ready event inventory."""

    sections: List[ExplanationSection] = Field(min_length=1)
    event_candidates: List[EventCandidate] = Field(min_length=1)


class GraphNodeDraft(BaseModel):
    """SDK-constrained event node before persistence."""

    alias: str
    title: str
    description: str
    domain: Domain
    event_type: EventType = EventType.MILESTONE
    occurred_date: Optional[datetime] = None
    evidence_aliases: List[str] = Field(default_factory=list)
    is_outcome: bool = False


class GraphEdgeDraft(BaseModel):
    """SDK-constrained graph edge before persistence."""

    source_alias: str
    target_alias: str
    relation: CausalRelationType
    reasoning: str
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_aliases: List[str] = Field(default_factory=list)


class OutcomeImpactDraft(BaseModel):
    """SDK-constrained event-to-outcome impact before persistence."""

    event_alias: str
    outcome_alias: str
    direction: ImpactDirection
    magnitude: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence_aliases: List[str] = Field(default_factory=list)


class GraphDraft(BaseModel):
    """Complete graph proposal produced or repaired in one model call."""

    nodes: List[GraphNodeDraft] = Field(min_length=1)
    edges: List[GraphEdgeDraft] = Field(default_factory=list)
    outcome_impacts: List[OutcomeImpactDraft] = Field(default_factory=list)


class AgentUsage(BaseModel):
    """Best-effort usage metadata reported by the Agents SDK."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0


class AgentResult(BaseModel):
    """Typed agent output with usage and trace metadata."""

    output: object
    usage: AgentUsage = Field(default_factory=AgentUsage)
    trace_id: Optional[str] = None
