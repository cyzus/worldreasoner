"""Standalone FastAPI application for hosted annotation studies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.core.database import GenericDatabase
from src.services.hosted_annotation_service import (
    HostedAnnotationPacket,
    HostedAnnotationService,
)


WEB_ROOT = Path(__file__).with_name("annotation_web")


class AssignmentStartRequest(BaseModel):
    prolific_pid: str = Field(min_length=1, max_length=128)
    study_id: Optional[str] = Field(default=None, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=128)
    consented: bool
    consent_version: str = Field(min_length=1, max_length=64)


class AnnotationResponseRequest(BaseModel):
    source_support: str
    date_validity: str
    date_basis: str
    entity_match: str
    corrected_event_date: Optional[str] = Field(default=None, max_length=10)
    evidence_excerpt: str = Field(default="", max_length=12000)
    reason: str = Field(default="", max_length=4000)
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    current_item_index: int = Field(default=0, ge=0)


class QualityCheckRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=128)


def create_annotation_app(
    packet_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    completion_url: Optional[str] = None,
) -> FastAPI:
    """Create the isolated participant-facing annotation application."""
    configured_packet_dir = packet_dir or os.environ.get("ANNOTATION_PACKET_DIR")
    if not configured_packet_dir:
        raise RuntimeError("ANNOTATION_PACKET_DIR or packet_dir is required")
    resolved_packet_dir = Path(configured_packet_dir)
    resolved_db_path = db_path or Path(
        os.environ.get(
            "ANNOTATION_DB_PATH",
            "data/annotation/hosted_annotations.db",
        )
    )
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

    packet = HostedAnnotationPacket.load(resolved_packet_dir)
    service = HostedAnnotationService(
        GenericDatabase(str(resolved_db_path), use_temporal_context=False),
        packet,
    )
    app = FastAPI(
        title="WorldReasoner Annotation",
        description="Blinded event-source reliability annotation",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.annotation_service = service
    app.state.completion_url = completion_url or os.environ.get(
        "PROLIFIC_COMPLETION_URL"
    )
    app.state.study_information = {
        "research_contact": os.environ.get(
            "ANNOTATION_RESEARCH_CONTACT",
            "research@example.org",
        ),
        "research_organisation": os.environ.get(
            "ANNOTATION_RESEARCH_ORGANISATION",
            "the research team",
        ),
    }

    def authenticated_assignment(
        assignment_id: str,
        assignment_token: Optional[str],
    ):
        if not assignment_token:
            raise HTTPException(status_code=401, detail="Assignment token is required")
        try:
            return service.authenticate(assignment_id, assignment_token)
        except PermissionError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/", response_class=HTMLResponse)
    async def participant_page() -> HTMLResponse:
        return HTMLResponse((WEB_ROOT / "index.html").read_text(encoding="utf-8"))

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "healthy", "packet_id": packet.packet_id}

    @app.get("/api/study")
    async def study() -> Dict[str, Any]:
        return packet.public_payload() | {
            "study_information": app.state.study_information,
        }

    @app.post("/api/assignments")
    async def start_assignment(request: AssignmentStartRequest) -> Dict[str, Any]:
        try:
            assignment, token = service.start_assignment(
                request.prolific_pid,
                request.study_id,
                request.session_id,
                request.consented,
                request.consent_version,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return service.assignment_payload(assignment) | {"assignment_token": token}

    @app.get("/api/assignments/{assignment_id}")
    async def assignment_state(
        assignment_id: str,
        x_assignment_token: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        assignment = authenticated_assignment(assignment_id, x_assignment_token)
        return service.assignment_payload(assignment)

    @app.put("/api/assignments/{assignment_id}/responses/{annotation_id}")
    async def save_response(
        assignment_id: str,
        annotation_id: str,
        request: AnnotationResponseRequest,
        x_assignment_token: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        assignment = authenticated_assignment(assignment_id, x_assignment_token)
        try:
            response = service.save_response(
                assignment,
                annotation_id,
                request.model_dump(),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown annotation item") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return response.model_dump(mode="json")

    @app.post("/api/assignments/{assignment_id}/checks/{check_id}")
    async def record_check(
        assignment_id: str,
        check_id: str,
        request: QualityCheckRequest,
        x_assignment_token: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        assignment = authenticated_assignment(assignment_id, x_assignment_token)
        try:
            return service.record_quality_check(
                assignment,
                check_id,
                request.answer,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Unknown quality check") from error

    @app.post("/api/assignments/{assignment_id}/submit")
    async def submit_assignment(
        assignment_id: str,
        x_assignment_token: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        assignment = authenticated_assignment(assignment_id, x_assignment_token)
        try:
            submission = service.finalize(assignment)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "submission_id": submission.id,
            "submitted_at": submission.submitted_at.isoformat(),
            "completion_url": app.state.completion_url,
        }

    @app.get("/api/articles/{annotation_id}/{view}", response_class=HTMLResponse)
    async def article(annotation_id: str, view: str) -> HTMLResponse:
        if view != "cleaned":
            raise HTTPException(status_code=404, detail="Unknown article view")
        try:
            content = packet.article_html(annotation_id, view)
        except (KeyError, FileNotFoundError) as error:
            raise HTTPException(status_code=404, detail="Article unavailable") from error
        return HTMLResponse(
            content,
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
                )
            },
        )

    return app
