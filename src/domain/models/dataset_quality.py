"""Versioned records produced by the dataset quality pipeline."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.database import register_model


class ArticleQualityFlag(str, Enum):
    """Deterministic issues detected in a stored article snapshot."""

    JSON_WRAPPER = "json_wrapper"
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    CONSENT_LEADING = "consent_leading"
    TRUNCATED = "truncated"
    TOO_LONG = "too_long"
    LINK_HEAVY = "link_heavy"
    RAW_HTML = "raw_html"
    EXACT_DUPLICATE = "exact_duplicate"
    ERROR_PAGE = "error_page"
    ACCESS_BLOCK = "access_block"
    LIKELY_WRONG_PAGE = "likely_wrong_page"


class QualityStatus(str, Enum):
    """Processing status for a derived quality artifact."""

    PENDING = "pending"
    COMPLETE = "complete"
    NEEDS_REPAIR = "needs_repair"
    FAILED = "failed"


class SupportLabel(str, Enum):
    """Degree to which cited evidence supports an event claim."""

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"
    CONTRADICTORY = "contradictory"


class DateLabel(str, Enum):
    """Validity of the event's claimed date."""

    CORRECT = "correct"
    NEAR_MATCH = "near_match"
    INCORRECT = "incorrect"
    UNCLEAR = "unclear"


class EntityLabel(str, Enum):
    """Validity of entities named in an event claim."""

    CORRECT = "correct"
    AMBIGUOUS = "ambiguous"
    INCORRECT = "incorrect"


class RepairAction(str, Enum):
    """Allowed outcomes of event-source validation."""

    ACCEPT = "accept"
    REVISE = "revise"
    RELINK = "relink"
    MERGE = "merge"
    REJECT = "reject"
    DEFER_UNVERIFIABLE = "defer_unverifiable"


@register_model(
    "article_quality_records",
    indexes=[
        "article_id",
        "dataset_version",
        "normalized_content_hash",
        "status",
    ],
)
class ArticleQualityRecord(BaseModel):
    """Derived, versioned representation of an immutable article snapshot."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    article_id: str
    dataset_version: str
    original_content_hash: str
    normalized_content_hash: str
    normalized_content: str
    clean_markdown: Optional[str] = None
    flags: List[ArticleQualityFlag] = Field(default_factory=list)
    status: QualityStatus = QualityStatus.PENDING
    normalizer_version: str
    cleaner_model: Optional[str] = None
    cleaner_prompt_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


@register_model(
    "event_evidence_extractions",
    indexes=["event_id", "article_id", "dataset_version", "status"],
)
class EventEvidenceExtraction(BaseModel):
    """Exact evidence passages extracted for one event-source pair."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    event_id: str
    article_id: str
    dataset_version: str
    supporting_passages: List[str] = Field(default_factory=list)
    contradicting_passages: List[str] = Field(default_factory=list)
    date_passages: List[str] = Field(default_factory=list)
    proposed_claim: Optional[str] = None
    proposed_date: Optional[str] = None
    all_passages_traceable: bool = False
    traceability_failures: List[str] = Field(default_factory=list)
    traceability_version: Optional[str] = None
    status: QualityStatus = QualityStatus.PENDING
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@register_model(
    "event_evidence_verifications",
    indexes=["event_id", "article_id", "dataset_version", "action"],
)
class EventEvidenceVerification(BaseModel):
    """Independent verification of exact passages for an event-source pair."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    extraction_id: str
    event_id: str
    article_id: str
    dataset_version: str
    support: SupportLabel
    date_validity: DateLabel
    entity_match: EntityLabel
    action: RepairAction
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@register_model(
    "dataset_repair_records",
    indexes=["event_id", "dataset_version", "action"],
)
class DatasetRepairRecord(BaseModel):
    """Append-only record of an applied or proposed benchmark repair."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_version: str
    event_id: str
    action: RepairAction
    extraction_id: Optional[str] = None
    verification_id: Optional[str] = None
    before: Dict[str, Any] = Field(default_factory=dict)
    after: Dict[str, Any] = Field(default_factory=dict)
    applied: bool = False
    actor: str = "automated_quality_pipeline"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
