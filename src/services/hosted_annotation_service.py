"""Hosted, blinded annotation-study loading and persistence."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.database import GenericDatabase
from src.domain.models.annotation import (
    AnnotationAssignment,
    AnnotationAssignmentStatus,
    AnnotationResponse,
    AnnotationSubmission,
)


SOURCE_LABELS = {"full", "partial", "none", "contradictory"}
DATE_LABELS = {"correct", "near_match", "incorrect", "unclear"}
ENTITY_LABELS = {"correct", "ambiguous", "incorrect"}
DATE_BASES = {
    "explicit_occurrence_date",
    "relative_or_contextual_date",
    "publication_date_only",
    "no_date_evidence",
}
CONSENT_VERSION = "2026-08-26"

_ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&'-]*|[A-Z]{2,})"
    r"(?:\s+(?:of|the|and|for|[A-Z][A-Za-z0-9&'-]*|[A-Z]{2,})){0,4}\b"
)
_ENTITY_STOPWORDS = {
    "A",
    "An",
    "Article",
    "Event",
    "Hindsight",
    "The",
    "This",
}

QUALITY_CHECKS: Dict[str, Dict[str, Any]] = {
    "comprehension_claim": {
        "kind": "comprehension",
        "prompt": "Which text is the claim you must validate?",
        "options": [
            ["full_claim", "The full event claim"],
            ["short_title", "Only the short event title"],
            ["article_title", "The cited article title"],
        ],
        "expected": "full_claim",
        "max_attempts": 2,
    },
    "comprehension_date": {
        "kind": "comprehension",
        "prompt": "Does an article publication date alone prove when an event occurred?",
        "options": [["yes", "Yes"], ["no", "No"]],
        "expected": "no",
        "max_attempts": 2,
    },
    "attention_support": {
        "kind": "attention",
        "after_item": 10,
        "prompt": "This is an attention check. Please select Partial.",
        "options": [
            ["full", "Full"],
            ["partial", "Partial"],
            ["none", "None"],
            ["contradictory", "Contradictory"],
        ],
        "expected": "partial",
        "max_attempts": 1,
    },
    "attention_date": {
        "kind": "attention",
        "after_item": 35,
        "prompt": "This is an attention check. Please select Unclear.",
        "options": [
            ["correct", "Correct"],
            ["near_match", "Near match"],
            ["incorrect", "Incorrect"],
            ["unclear", "Unclear"],
        ],
        "expected": "unclear",
        "max_attempts": 1,
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _response_prefix(assignment_id: str, annotation_id: str) -> str:
    value = f"{assignment_id}|{annotation_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def _extract_claimed_entities(title: str, description: str) -> List[str]:
    """Extract readable entity candidates without making an NLP model dependency."""
    candidates: List[str] = []
    for match in _ENTITY_PATTERN.finditer(f"{title}. {description}"):
        candidate = match.group(0).strip(" .,:;()[]")
        if candidate in _ENTITY_STOPWORDS or candidate.isdigit():
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates[:8]


@dataclass(frozen=True)
class HostedAnnotationPacket:
    """Immutable participant-facing packet loaded from generated artifacts."""

    root: Path
    packet_id: str
    checksum: str
    manifest: Dict[str, Any]
    items: List[Dict[str, str]]

    @classmethod
    def load(cls, root: Path) -> "HostedAnnotationPacket":
        root = root.resolve()
        manifest_path = root / "manifest.json"
        queue_path = root / "review_queue.csv"
        if not manifest_path.is_file() or not queue_path.is_file():
            raise ValueError(
                f"Annotation packet requires manifest.json and review_queue.csv: {root}"
            )

        manifest_bytes = manifest_path.read_bytes()
        queue_bytes = queue_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        with queue_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError("Annotation packet contains no items")

        packet_id = str(manifest.get("packet_id") or "").strip()
        if not packet_id:
            raise ValueError("Annotation packet manifest has no packet_id")
        annotation_ids = [row.get("annotation_id", "") for row in rows]
        if not all(annotation_ids) or len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("Annotation packet has missing or duplicate annotation IDs")

        checksum = hashlib.sha256(manifest_bytes + b"\n" + queue_bytes).hexdigest()
        return cls(
            root=root,
            packet_id=packet_id,
            checksum=checksum,
            manifest=manifest,
            items=rows,
        )

    def public_payload(self) -> Dict[str, Any]:
        allowed = {
            "annotation_id",
            "item_id",
            "event_title",
            "event_description",
            "claimed_date",
            "domain",
            "article_title",
            "article_source",
            "article_published_date",
        }
        return {
            "packet_id": self.packet_id,
            "packet_checksum": self.checksum,
            "consent_version": CONSENT_VERSION,
            "item_count": len(self.items),
            "items": [
                {
                    **{key: value for key, value in row.items() if key in allowed},
                    "claimed_entities": _extract_claimed_entities(
                        row.get("event_title", ""),
                        row.get("event_description", ""),
                    ),
                }
                for row in self.items
            ],
            "quality_checks": [
                {key: value for key, value in check.items() if key != "expected"}
                | {"id": check_id}
                for check_id, check in QUALITY_CHECKS.items()
            ],
        }

    def item(self, annotation_id: str) -> Optional[Dict[str, str]]:
        return next(
            (row for row in self.items if row["annotation_id"] == annotation_id),
            None,
        )

    def article_html(self, annotation_id: str, view: str) -> str:
        row = self.item(annotation_id)
        if row is None:
            raise KeyError(annotation_id)
        key = "cleaned_path" if view == "cleaned" else "snapshot_path"
        relative = Path(row[key])
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate.read_text(encoding="utf-8")


class HostedAnnotationService:
    """Assignment, autosave, checks, and finalization for one study packet."""

    def __init__(self, db: GenericDatabase, packet: HostedAnnotationPacket) -> None:
        self.db = db
        self.packet = packet
        for model in (
            AnnotationAssignment,
            AnnotationResponse,
            AnnotationSubmission,
        ):
            self.db.create_table(model)

    def start_assignment(
        self,
        prolific_pid: str,
        study_id: Optional[str],
        session_id: Optional[str],
        consented: bool,
        consent_version: str,
    ) -> Tuple[AnnotationAssignment, str]:
        prolific_pid = prolific_pid.strip()
        if not prolific_pid:
            raise ValueError("Prolific ID is required")
        if not consented or consent_version != CONSENT_VERSION:
            raise ValueError("Current informed consent is required")

        existing = self.db.get_many(
            AnnotationAssignment,
            filters={
                "packet_id": self.packet.packet_id,
                "prolific_pid": prolific_pid,
            },
        )
        if existing:
            assignment = max(existing, key=lambda item: item.created_at)
            if (
                assignment.prolific_session_id
                and session_id
                and assignment.prolific_session_id != session_id
            ):
                raise ValueError("This participant already has another study session")
        else:
            assignment = AnnotationAssignment(
                packet_id=self.packet.packet_id,
                packet_checksum=self.packet.checksum,
                prolific_pid=prolific_pid,
                prolific_study_id=study_id or None,
                prolific_session_id=session_id or None,
                consent_version=consent_version,
                consent_accepted_at=_now(),
                access_token_hash="pending",
            )

        if assignment.consent_version != consent_version:
            assignment.consent_version = consent_version
            assignment.consent_accepted_at = _now()

        token = secrets.token_urlsafe(32)
        assignment.access_token_hash = _token_hash(token)
        assignment.updated_at = _now()
        self.db.save(AnnotationAssignment, assignment)
        return assignment, token

    def authenticate(self, assignment_id: str, token: str) -> AnnotationAssignment:
        assignment = self.db.get(AnnotationAssignment, assignment_id)
        if assignment is None or not hmac.compare_digest(
            assignment.access_token_hash,
            _token_hash(token),
        ):
            raise PermissionError("Invalid annotation assignment token")
        if assignment.packet_checksum != self.packet.checksum:
            raise RuntimeError("The study packet changed after assignment creation")
        return assignment

    def latest_responses(self, assignment_id: str) -> Dict[str, AnnotationResponse]:
        responses = self.db.get_many(
            AnnotationResponse,
            filters={"assignment_id": assignment_id},
        )
        latest: Dict[str, AnnotationResponse] = {}
        for response in responses:
            current = latest.get(response.annotation_id)
            if current is None or response.revision > current.revision:
                latest[response.annotation_id] = response
        return latest

    def assignment_payload(self, assignment: AnnotationAssignment) -> Dict[str, Any]:
        responses = self.latest_responses(assignment.id)
        return {
            "assignment_id": assignment.id,
            "status": assignment.status.value,
            "current_item_index": assignment.current_item_index,
            "quality_checks": assignment.quality_checks,
            "responses": {
                annotation_id: response.model_dump(mode="json")
                for annotation_id, response in responses.items()
            },
        }

    @staticmethod
    def validate_response(payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        source_support = str(payload.get("source_support") or "")
        date_validity = str(payload.get("date_validity") or "")
        date_basis = str(payload.get("date_basis") or "")
        entity_match = str(payload.get("entity_match") or "")
        corrected_event_date = str(payload.get("corrected_event_date") or "").strip()
        evidence_excerpt = str(payload.get("evidence_excerpt") or "").strip()
        reason = str(payload.get("reason") or "").strip()

        if source_support not in SOURCE_LABELS:
            errors.append("Select source support")
        if date_validity not in DATE_LABELS:
            errors.append("Select date validity")
        if date_basis not in DATE_BASES:
            errors.append("Select what establishes the event date")
        if entity_match not in ENTITY_LABELS:
            errors.append("Select entity match")
        if date_validity == "incorrect":
            if not corrected_event_date:
                errors.append("Enter the corrected event date")
            elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", corrected_event_date):
                errors.append("Use YYYY-MM-DD for the corrected event date")
            else:
                try:
                    datetime.strptime(corrected_event_date, "%Y-%m-%d")
                except ValueError:
                    errors.append("Enter a valid corrected event date")
        if source_support in {"full", "partial", "contradictory"} and not evidence_excerpt:
            errors.append("Add one exact article excerpt")
        if date_validity in {"correct", "near_match", "incorrect"} and date_basis in {
            "publication_date_only",
            "no_date_evidence",
        }:
            errors.append(
                "Publication metadata alone cannot establish event-date validity; "
                "choose Unclear or identify article date evidence"
            )
        if (source_support == "none" or entity_match == "incorrect") and date_validity != "unclear":
            errors.append("Use Unclear for date when the event or entity is unsupported")
        if (
            source_support not in {"", "full"}
            or date_validity not in {"", "correct"}
            or entity_match not in {"", "correct"}
        ) and not reason:
            errors.append("Explain every rejected or qualified judgment")
        return errors

    def save_response(
        self,
        assignment: AnnotationAssignment,
        annotation_id: str,
        payload: Dict[str, Any],
    ) -> AnnotationResponse:
        if assignment.status != AnnotationAssignmentStatus.IN_PROGRESS:
            raise ValueError("This assignment can no longer be edited")
        item = self.packet.item(annotation_id)
        if item is None:
            raise KeyError(annotation_id)
        errors = self.validate_response(payload)
        if errors:
            raise ValueError("; ".join(errors))

        latest = self.latest_responses(assignment.id).get(annotation_id)
        revision = 1 if latest is None else latest.revision + 1
        prefix = _response_prefix(assignment.id, annotation_id)
        response = AnnotationResponse(
            id=f"{prefix}-r{revision}",
            assignment_id=assignment.id,
            annotation_id=annotation_id,
            item_id=item["item_id"],
            source_support=str(payload["source_support"]),
            date_validity=str(payload["date_validity"]),
            date_basis=str(payload["date_basis"]),
            entity_match=str(payload["entity_match"]),
            corrected_event_date=(
                str(payload.get("corrected_event_date") or "").strip() or None
            ),
            evidence_excerpt=str(payload.get("evidence_excerpt") or "").strip(),
            reason=str(payload.get("reason") or "").strip(),
            duration_seconds=max(0, int(payload.get("duration_seconds") or 0)),
            revision=revision,
        )
        self.db.save(AnnotationResponse, response)
        assignment.current_item_index = min(
            max(0, int(payload.get("current_item_index") or 0)),
            len(self.packet.items) - 1,
        )
        assignment.updated_at = _now()
        self.db.save(AnnotationAssignment, assignment)
        return response

    def record_quality_check(
        self,
        assignment: AnnotationAssignment,
        check_id: str,
        answer: str,
    ) -> Dict[str, Any]:
        definition = QUALITY_CHECKS.get(check_id)
        if definition is None:
            raise KeyError(check_id)
        previous = assignment.quality_checks.get(check_id, {})
        attempts = int(previous.get("attempts", 0)) + 1
        passed = answer == definition["expected"]
        complete = passed or definition["kind"] == "attention" or attempts >= int(
            definition["max_attempts"]
        )
        result = {
            "answer": answer,
            "attempts": attempts,
            "passed": passed,
            "complete": complete,
        }
        assignment.quality_checks = {**assignment.quality_checks, check_id: result}
        if definition["kind"] == "comprehension" and complete and not passed:
            assignment.status = AnnotationAssignmentStatus.RETURN_REQUIRED
        assignment.updated_at = _now()
        self.db.save(AnnotationAssignment, assignment)
        return result | {"should_return": assignment.status == AnnotationAssignmentStatus.RETURN_REQUIRED}

    def finalize(self, assignment: AnnotationAssignment) -> AnnotationSubmission:
        if assignment.status == AnnotationAssignmentStatus.SUBMITTED:
            existing = self.db.get_many(
                AnnotationSubmission,
                filters={"assignment_id": assignment.id},
            )
            if existing:
                return existing[0]
        if assignment.status != AnnotationAssignmentStatus.IN_PROGRESS:
            raise ValueError("This assignment cannot be submitted")

        responses = self.latest_responses(assignment.id)
        missing = [
            row["annotation_id"]
            for row in self.packet.items
            if row["annotation_id"] not in responses
        ]
        if missing:
            raise ValueError(f"Complete all study items ({len(missing)} remaining)")

        required_checks = set(QUALITY_CHECKS)
        completed_checks = {
            check_id
            for check_id, result in assignment.quality_checks.items()
            if result.get("complete")
        }
        if required_checks - completed_checks:
            raise ValueError("Complete the tutorial and attention checks")

        submission = AnnotationSubmission(
            assignment_id=assignment.id,
            packet_id=self.packet.packet_id,
            packet_checksum=self.packet.checksum,
            prolific_pid=assignment.prolific_pid,
            response_count=len(responses),
            quality_checks=assignment.quality_checks,
        )
        with self.db.batch():
            self.db.save(AnnotationSubmission, submission)
            assignment.status = AnnotationAssignmentStatus.SUBMITTED
            assignment.submitted_at = submission.submitted_at
            assignment.updated_at = submission.submitted_at
            self.db.save(AnnotationAssignment, assignment)
        return submission
