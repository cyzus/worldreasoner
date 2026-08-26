"""Tests for reproducible event-source validation selection."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.cli.commands.dataset import (
    _current_validation_pairs,
    _sample_validation_pairs,
    _select_event_article_pairs,
)
from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    DateLabel,
    Domain,
    EntityLabel,
    Event,
    EventEvidenceVerification,
    EventStatus,
    EventType,
    RepairAction,
    SupportLabel,
)


def _article(article_id: str) -> Article:
    return Article(
        id=article_id,
        title=f"Source article {article_id}",
        content="Substantive source content. " * 10,
        source="Test Source",
        published_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        domain=Domain.POLITICS,
    )


def _event(event_id: str, article_ids: list[str]) -> Event:
    return Event(
        id=event_id,
        title=f"Event {event_id}",
        description="A sufficiently detailed event description for validation.",
        event_type=EventType.DECISION,
        domain=Domain.POLITICS,
        occurred_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
        source_article_id=article_ids[0],
        article_ids=article_ids,
    )


def _database(path: Path) -> GenericDatabase:
    db = GenericDatabase(str(path))
    db.create_table(Article)
    db.create_table(Event)
    return db


def test_selection_file_preserves_explicit_pair_order(tmp_path: Path) -> None:
    db = _database(tmp_path / "quality.db")
    first = _article("article-1")
    second = _article("article-2")
    event = _event("event-1", [first.id, second.id])
    for article in [first, second]:
        db.save(Article, article)
    db.save(Event, event)
    selection = tmp_path / "pairs.txt"
    selection.write_text(
        f"{event.id}::{second.id}\n{event.id}::{first.id}\n",
        encoding="utf-8",
    )

    pairs = _select_event_article_pairs(
        db,
        event_id=None,
        selection_file=selection,
        all_sources=False,
    )

    assert [(item.id, article.id) for item, article in pairs] == [
        (event.id, second.id),
        (event.id, first.id),
    ]


def test_selection_file_rejects_uncited_article(tmp_path: Path) -> None:
    db = _database(tmp_path / "quality.db")
    cited = _article("article-cited")
    uncited = _article("article-uncited")
    event = _event("event-1", [cited.id])
    for article in [cited, uncited]:
        db.save(Article, article)
    db.save(Event, event)
    selection = tmp_path / "pairs.txt"
    selection.write_text(
        f"{event.id}::{uncited.id}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Article is not cited"):
        _select_event_article_pairs(
            db,
            event_id=None,
            selection_file=selection,
            all_sources=False,
        )


def test_all_sources_deduplicates_primary_article(tmp_path: Path) -> None:
    db = _database(tmp_path / "quality.db")
    first = _article("article-1")
    second = _article("article-2")
    event = _event("event-1", [first.id, second.id])
    for article in [first, second]:
        db.save(Article, article)
    db.save(Event, event)

    pairs = _select_event_article_pairs(
        db,
        event_id=event.id,
        selection_file=None,
        all_sources=True,
    )

    assert [article.id for _, article in pairs] == [first.id, second.id]


def test_current_validation_pairs_excludes_old_verifier_decisions() -> None:
    records = [
        EventEvidenceVerification(
            extraction_id=f"extraction-{index}",
            event_id=f"event-{index}",
            article_id=f"article-{index}",
            dataset_version="v2.0",
            support=SupportLabel.FULL,
            date_validity=DateLabel.CORRECT,
            entity_match=EntityLabel.CORRECT,
            action=RepairAction.ACCEPT,
            confidence=0.9,
            model="test-model",
            prompt_version=prompt_version,
        )
        for index, prompt_version in enumerate(
            [
                "event-evidence-verifier-v1",
                "event-evidence-verifier-v2",
                "markdown-visible-v2",
            ],
            1,
        )
    ]

    pairs = _current_validation_pairs(records, "v2.0")

    assert pairs == {("event-2", "article-2"), ("event-3", "article-3")}


def test_question_stratified_sampling_spreads_questions_and_domains() -> None:
    pairs = []
    for domain in [Domain.POLITICS, Domain.SCIENCE]:
        for question_index in range(3):
            for pair_index in range(4):
                suffix = f"{domain.value}-{question_index}-{pair_index}"
                article = _article(f"article-{suffix}")
                event = _event(f"event-{suffix}", [article.id])
                event.domain = domain
                event.extracted_for_question_id = (
                    f"question-{domain.value}-{question_index}"
                )
                pairs.append((event, article))

    selected = _sample_validation_pairs(
        pairs,
        limit=6,
        sampling="question-stratified",
        seed=42,
    )

    assert len(selected) == 6
    assert len({event.extracted_for_question_id for event, _ in selected}) == 6
    assert {event.domain for event, _ in selected} == {
        Domain.POLITICS,
        Domain.SCIENCE,
    }


def test_question_stratified_sampling_is_reproducible() -> None:
    pairs = []
    for index in range(10):
        article = _article(f"article-{index}")
        event = _event(f"event-{index}", [article.id])
        event.extracted_for_question_id = f"question-{index}"
        pairs.append((event, article))

    first = _sample_validation_pairs(pairs, 5, "question-stratified", 7)
    second = _sample_validation_pairs(pairs, 5, "question-stratified", 7)

    assert [(event.id, article.id) for event, article in first] == [
        (event.id, article.id) for event, article in second
    ]
