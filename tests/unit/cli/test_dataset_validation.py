"""Tests for reproducible event-source validation selection."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.cli.commands.dataset import _select_event_article_pairs
from src.core.database import GenericDatabase
from src.domain.models import Article, Domain, Event, EventStatus, EventType


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
