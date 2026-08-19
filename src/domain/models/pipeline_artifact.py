"""Versioned artifacts for resumable benchmark construction."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.database import register_model


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineRunStatus(str, Enum):
    """Lifecycle state for one question-level construction run."""

    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    COMPLETE = "complete"


class StageAttemptStatus(str, Enum):
    """Outcome of one bounded pipeline-stage attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"
    NEEDS_REVIEW = "needs_review"


class ArtifactStatus(str, Enum):
    """Validation and commit state shared by versioned artifacts."""

    DRAFT = "draft"
    VALIDATED = "validated"
    REJECTED = "rejected"
    COMMITTED = "committed"


class AliasEntityKind(str, Enum):
    """Entity namespaces exposed to an agent through short aliases."""

    ARTICLE = "article"
    EVENT = "event"
    OUTCOME = "outcome"


class AliasScopeType(str, Enum):
    """Artifact scopes in which an alias has a stable meaning."""

    EVIDENCE_DOSSIER = "evidence_dossier"
    EXPLANATION = "explanation"
    GRAPH_REVISION = "graph_revision"


class EvidenceSupportType(str, Enum):
    """How an approved article supports an explanation claim."""

    DIRECT = "direct"
    CONTEXTUAL = "contextual"


@register_model(
    "pipeline_runs",
    indexes=["question_id", "dataset_version", "status", "current_stage"],
)
class PipelineRun(BaseModel):
    """Persistent state and provenance for one construction workflow."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    question_id: str
    dataset_version: str
    workflow_version: str
    status: PipelineRunStatus = PipelineRunStatus.PENDING
    current_stage: Optional[str] = None
    model_configuration: Dict[str, Any] = Field(default_factory=dict)
    prompt_bundle_version: Optional[str] = None
    parent_run_id: Optional[str] = None
    token_usage: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    trace_ids: List[str] = Field(default_factory=list)
    error_summary: Optional[str] = None
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


@register_model(
    "pipeline_stage_attempts",
    indexes=["run_id", "stage_name", "status", "idempotency_key"],
)
class StageAttempt(BaseModel):
    """Append-only record of a bounded stage invocation."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    stage_name: str
    attempt_number: int = Field(ge=1)
    idempotency_key: str
    status: StageAttemptStatus = StageAttemptStatus.RUNNING
    input_artifact_ids: List[str] = Field(default_factory=list)
    output_artifact_ids: List[str] = Field(default_factory=list)
    failure_code: Optional[str] = None
    retryable: bool = False
    diagnostic: Optional[str] = None
    decisions: Dict[str, Any] = Field(default_factory=dict)
    token_usage: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


@register_model(
    "search_dossiers",
    indexes=["run_id", "question_id", "dataset_version", "status"],
)
class SearchDossier(BaseModel):
    """Versioned search activity and unresolved evidence needs."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    question_id: str
    dataset_version: str
    queries: List[str] = Field(default_factory=list)
    selected_article_ids: List[str] = Field(default_factory=list)
    rejected_articles: Dict[str, List[str]] = Field(default_factory=dict)
    intended_coverage: List[str] = Field(default_factory=list)
    unresolved_gaps: List[str] = Field(default_factory=list)
    coverage_statistics: Dict[str, Any] = Field(default_factory=dict)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)


@register_model(
    "approved_evidence_dossiers",
    indexes=["run_id", "question_id", "dataset_version", "status"],
)
class ApprovedEvidenceDossier(BaseModel):
    """Closed evidence set that downstream reasoning is allowed to read."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    question_id: str
    dataset_version: str
    search_dossier_id: str
    article_version_ids: List[str] = Field(default_factory=list)
    coverage_summary: Dict[str, Any] = Field(default_factory=dict)
    remaining_gaps: List[str] = Field(default_factory=list)
    readiness_decision: str
    status: ArtifactStatus = ArtifactStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)


class EvidenceReference(BaseModel):
    """Structured support link from a claim to approved evidence."""

    article_alias: str
    article_version_id: str
    support_type: EvidenceSupportType
    passage: Optional[str] = None
    locator: Optional[str] = None


class ExplanationSection(BaseModel):
    """Human-readable explanation section with explicit citations."""

    id: str
    text: str
    citation_aliases: List[str] = Field(default_factory=list)


class EventCandidate(BaseModel):
    """Event proposed by explanation synthesis before graph construction."""

    alias: str
    title: str
    description: str
    occurred_date: Optional[datetime] = None
    evidence_refs: List[EvidenceReference] = Field(default_factory=list)


@register_model(
    "explanation_artifacts",
    indexes=["run_id", "question_id", "dataset_version", "status"],
)
class ExplanationArtifact(BaseModel):
    """Immutable explanation revision grounded in an approved dossier."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    question_id: str
    dataset_version: str
    evidence_dossier_id: str
    sections: List[ExplanationSection] = Field(default_factory=list)
    event_candidates: List[EventCandidate] = Field(default_factory=list)
    model: str
    prompt_version: str
    supersedes_id: Optional[str] = None
    validation_metadata: Dict[str, Any] = Field(default_factory=dict)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)


class GraphNodeProposal(BaseModel):
    """One event node in a staged graph revision."""

    alias: str
    title: str
    description: str
    occurred_date: Optional[datetime] = None
    evidence_aliases: List[str] = Field(default_factory=list)
    is_outcome: bool = False


class GraphEdgeProposal(BaseModel):
    """One directed relationship in a staged graph revision."""

    source_alias: str
    target_alias: str
    relation: str
    reasoning: str
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class OutcomeImpactProposal(BaseModel):
    """Proposed effect of an event on one outcome option."""

    event_alias: str
    outcome_alias: str
    direction: str
    magnitude: float = Field(ge=0.0, le=1.0)
    reasoning: str


@register_model(
    "graph_revisions",
    indexes=["run_id", "question_id", "dataset_version", "status"],
)
class GraphRevision(BaseModel):
    """Complete graph proposal awaiting deterministic validation and commit."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    question_id: str
    dataset_version: str
    explanation_artifact_id: str
    parent_revision_id: Optional[str] = None
    nodes: List[GraphNodeProposal] = Field(default_factory=list)
    edges: List[GraphEdgeProposal] = Field(default_factory=list)
    outcome_impacts: List[OutcomeImpactProposal] = Field(default_factory=list)
    validation_results: Dict[str, Any] = Field(default_factory=dict)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)


@register_model(
    "agent_aliases",
    indexes=["run_id", "scope_id", "alias", "entity_kind"],
)
class AgentAlias(BaseModel):
    """Persistent agent-facing alias scoped to one versioned artifact."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    scope_id: str
    scope_type: AliasScopeType
    alias: str = Field(pattern=r"^[A-Z][0-9]{2,}$")
    entity_kind: AliasEntityKind
    target_id: str
    is_canonical: bool = True
    created_at: datetime = Field(default_factory=_now)
