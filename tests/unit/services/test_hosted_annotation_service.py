import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.annotation_app import create_annotation_app
from src.core.database import GenericDatabase
from src.domain.models.annotation import AnnotationAssignment
from src.services.hosted_annotation_service import (
    HostedAnnotationPacket,
    HostedAnnotationService,
)


def _packet(tmp_path: Path, item_count: int = 2) -> Path:
    root = tmp_path / "packet"
    article_dir = root / "articles"
    article_dir.mkdir(parents=True)
    rows = []
    for index in range(item_count):
        article_id = f"article-{index}"
        annotation_id = f"annotation-{index}"
        clean_path = f"articles/{article_id}_cleaned.html"
        snapshot_path = f"articles/{article_id}_snapshot.html"
        (root / clean_path).write_text(
            f"<html><body>Evidence for event {index} on 12 May.</body></html>",
            encoding="utf-8",
        )
        (root / snapshot_path).write_text(
            f"<html><body>Snapshot for event {index}.</body></html>",
            encoding="utf-8",
        )
        rows.append(
            {
                "annotation_id": annotation_id,
                "item_id": f"event-{index}::{article_id}",
                "event_id": f"event-{index}",
                "article_id": article_id,
                "question_id": "question-1",
                "event_title": f"Event {index}",
                "event_description": f"Cambridge Council event {index} occurred.",
                "claimed_date": "2026-05-12T00:00:00+00:00",
                "domain": "general",
                "article_title": f"Article {index}",
                "article_source": "Test Source",
                "article_published_date": "2026-05-13T00:00:00+00:00",
                "cleaned_path": clean_path,
                "snapshot_path": snapshot_path,
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"packet_id": "test-packet", "selected_pairs": item_count}),
        encoding="utf-8",
    )
    with (root / "review_queue.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return root


def _valid_response(index: int = 0) -> dict:
    return {
        "source_support": "full",
        "date_validity": "correct",
        "date_basis": "explicit_occurrence_date",
        "entity_match": "correct",
        "evidence_excerpt": f"Evidence for event {index} on 12 May.",
        "reason": "",
        "duration_seconds": 30,
        "current_item_index": index,
    }


def test_packet_public_payload_excludes_internal_paths(tmp_path: Path) -> None:
    packet = HostedAnnotationPacket.load(_packet(tmp_path))

    payload = packet.public_payload()

    assert payload["item_count"] == 2
    assert "cleaned_path" not in payload["items"][0]
    assert "snapshot_path" not in payload["items"][0]
    assert "Cambridge Council" in payload["items"][0]["claimed_entities"]
    assert packet.article_html("annotation-0", "cleaned").startswith("<html>")


def test_response_validation_rejects_publication_date_as_occurrence_proof(
    tmp_path: Path,
) -> None:
    packet = HostedAnnotationPacket.load(_packet(tmp_path))
    service = HostedAnnotationService(
        GenericDatabase(str(tmp_path / "annotations.db")),
        packet,
    )
    payload = _valid_response()
    payload["date_basis"] = "publication_date_only"

    errors = service.validate_response(payload)

    assert any("Publication metadata alone" in error for error in errors)


def test_incorrect_date_requires_valid_correction(tmp_path: Path) -> None:
    service = HostedAnnotationService(
        GenericDatabase(str(tmp_path / "annotations.db")),
        HostedAnnotationPacket.load(_packet(tmp_path)),
    )
    payload = _valid_response()
    payload.update(
        {
            "date_validity": "incorrect",
            "corrected_event_date": "2026-02-31",
            "reason": "The article gives a different date.",
        }
    )

    errors = service.validate_response(payload)

    assert "Enter a valid corrected event date" in errors


def test_hosted_annotation_end_to_end(tmp_path: Path) -> None:
    app = create_annotation_app(
        packet_dir=_packet(tmp_path),
        db_path=tmp_path / "hosted.db",
    )
    client = TestClient(app)

    study = client.get("/api/study")
    assert study.status_code == 200
    assert study.json()["item_count"] == 2
    assert study.json()["consent_version"]

    declined = client.post(
        "/api/assignments",
        json={
            "prolific_pid": "participant-declined",
            "study_id": "study-1",
            "session_id": "session-declined",
            "consented": False,
            "consent_version": study.json()["consent_version"],
        },
    )
    assert declined.status_code == 409

    started = client.post(
        "/api/assignments",
        json={
            "prolific_pid": "participant-1",
            "study_id": "study-1",
            "session_id": "session-1",
            "consented": True,
            "consent_version": study.json()["consent_version"],
        },
    )
    assert started.status_code == 200
    assignment_id = started.json()["assignment_id"]
    token = started.json()["assignment_token"]
    headers = {"X-Assignment-Token": token}

    assignment = app.state.annotation_service.db.get(
        AnnotationAssignment,
        assignment_id,
    )
    assert assignment.consent_accepted_at is not None

    for check_id, answer in (
        ("comprehension_claim", "full_claim"),
        ("comprehension_date", "no"),
        ("attention_support", "partial"),
        ("attention_date", "unclear"),
    ):
        checked = client.post(
            f"/api/assignments/{assignment_id}/checks/{check_id}",
            headers=headers,
            json={"answer": answer},
        )
        assert checked.status_code == 200
        assert checked.json()["passed"] is True

    for index in range(2):
        saved = client.put(
            f"/api/assignments/{assignment_id}/responses/annotation-{index}",
            headers=headers,
            json=_valid_response(index),
        )
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1

    submitted = client.post(
        f"/api/assignments/{assignment_id}/submit",
        headers=headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["submission_id"]

    state = client.get(
        f"/api/assignments/{assignment_id}",
        headers=headers,
    )
    assert state.json()["status"] == "submitted"
    assert len(state.json()["responses"]) == 2

    article = client.get("/api/articles/annotation-0/cleaned")
    assert article.status_code == 200
    assert "Evidence for event 0" in article.text

    snapshot = client.get("/api/articles/annotation-0/snapshot")
    assert snapshot.status_code == 404
