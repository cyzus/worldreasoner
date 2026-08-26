"""Tests for blinded event-source annotation packet generation."""

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    Domain,
    Event,
    EventStatus,
    EventType,
    QualityStatus,
    Question,
    QuestionType,
)
from scripts.analysis.build_event_annotation_artifacts import (
    _select_candidates,
    build_packet,
)


def test_explicit_selection_preserves_order_and_excludes_calibration(
    tmp_path: Path,
) -> None:
    rows = [
        {"item_id": "event-1::article-1", "automated_action": "unvalidated"},
        {"item_id": "event-2::article-2", "automated_action": "unvalidated"},
        {"item_id": "event-3::article-3", "automated_action": "accept"},
    ]
    selection = tmp_path / "selection.txt"
    selection.write_text(
        "event-2::article-2\nevent-1::article-1\n",
        encoding="utf-8",
    )
    excluded = tmp_path / "excluded.txt"
    excluded.write_text("event-3::article-3\n", encoding="utf-8")

    selected = _select_candidates(
        rows,
        limit=2,
        seed=7,
        selection_file=selection,
        exclude_selection_file=excluded,
        unvalidated_only=True,
    )

    assert [row["item_id"] for row in selected] == [
        "event-2::article-2",
        "event-1::article-1",
    ]


def test_build_packet_contains_clean_evidence_without_model_labels(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worldreasoner.db"
    db = GenericDatabase(str(db_path))
    for model in (Article, ArticleQualityRecord, Event, Question):
        db.create_table(model)

    question = Question(
        id="question-1",
        question_text="Will the council approve the proposed public policy?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=2,
        resolution_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
    )
    article = Article(
        id="article-1",
        title="Council considers a proposed public policy",
        content="Raw stored article text about the council meeting. " * 8,
        url="https://example.com/article",
        source="Example",
        published_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        domain=Domain.GENERAL,
        collected_for_question_id=question.id,
    )
    event = Event(
        id="event-1",
        title="Council approves policy",
        description="The city council approved the proposed public policy.",
        event_type=EventType.DECISION,
        domain=Domain.GENERAL,
        occurred_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
        article_ids=[article.id],
        source_article_id=article.id,
        extracted_for_question_id=question.id,
    )
    quality = ArticleQualityRecord(
        article_id=article.id,
        dataset_version="v2.0",
        original_content_hash="original",
        normalized_content_hash="normalized",
        normalized_content="# Snapshot\n\nRaw stored article text.",
        clean_markdown="# Article\n\nThe council approved the policy.",
        status=QualityStatus.COMPLETE,
        normalizer_version="article-normalizer-v5",
        cleaner_model="cleaner-model",
        cleaner_prompt_version="article-cleaner-v2",
    )
    db.save(Question, question)
    db.save(Article, article)
    db.save(Event, event)
    db.save(ArticleQualityRecord, quality)

    output_dir = tmp_path / "packet"
    html_path = build_packet(
        db_path=db_path,
        dataset_version="v2.0",
        output_dir=output_dir,
        packet_id="annotator-a",
        limit=10,
        seed=7,
        template_path=Path(
            "scripts/analysis/templates/event_annotation.template"
        ),
        storage_namespace="annotator-a",
    )

    html = html_path.read_text(encoding="utf-8")
    with (output_dir / "review_queue.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["event_id"] == event.id
    assert rows[0]["review_mode"] == "annotation_study"
    assert "question_text" not in rows[0]
    assert "resolved_outcome" not in rows[0]
    assert "cleaner-model" not in html
    assert "model_verification" not in html
    assert "Outcome relevance" not in html
    assert "Recommended action" not in html
    assert "['near_match','Near match']" in html
    assert "one-day timezone shift" in html
    assert "Judge the complete event claim" in html
    assert "exact evidence passage" in html
    assert "worldreasoner-event-annotation-annotator-a" in html
    assert "__QUEUE_DATA__" not in html
    assert (output_dir / rows[0]["cleaned_path"]).exists()
    assert (output_dir / rows[0]["snapshot_path"]).exists()
