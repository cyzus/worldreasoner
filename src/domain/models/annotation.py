"""Persistent records for hosted human annotation studies."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.database import register_model


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AnnotationAssignmentStatus(str, Enum):
    """Lifecycle of one participant assignment."""

    IN_PROGRESS = "in_progress"
    RETURN_REQUIRED = "return_required"
    SUBMITTED = "submitted"


@register_model(
    "annotation_assignments",
    indexes=["packet_id", "prolific_pid", "prolific_session_id", "status"],
)
class AnnotationAssignment(BaseModel):
    """Participant identity and progress for one immutable study packet."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    packet_id: str
    packet_checksum: str
    prolific_pid: str
    prolific_study_id: Optional[str] = None
    prolific_session_id: Optional[str] = None
    consent_version: Optional[str] = None
    consent_accepted_at: Optional[datetime] = None
    access_token_hash: str
    status: AnnotationAssignmentStatus = AnnotationAssignmentStatus.IN_PROGRESS
    current_item_index: int = Field(default=0, ge=0)
    quality_checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    submitted_at: Optional[datetime] = None


@register_model(
    "annotation_responses",
    indexes=["assignment_id", "annotation_id", "item_id"],
)
class AnnotationResponse(BaseModel):
    """Latest autosaved response for one assignment and event-source item."""

    id: str
    assignment_id: str
    annotation_id: str
    item_id: str
    source_support: str
    date_validity: str
    date_basis: str
    entity_match: str
    corrected_event_date: Optional[str] = None
    evidence_excerpt: str = ""
    reason: str = ""
    duration_seconds: int = Field(default=0, ge=0)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


@register_model(
    "annotation_submissions",
    indexes=["assignment_id", "packet_id", "prolific_pid"],
)
class AnnotationSubmission(BaseModel):
    """Frozen completion record for one valid annotation assignment."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    assignment_id: str
    packet_id: str
    packet_checksum: str
    prolific_pid: str
    response_count: int
    quality_checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    submitted_at: datetime = Field(default_factory=_now)
