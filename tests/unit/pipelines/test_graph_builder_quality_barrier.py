"""Tests for the cleaned-evidence barrier before graph construction."""

from datetime import datetime, timezone
from pathlib import Path

from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    Domain,
    QualityStatus,
    Question,
    QuestionType,
)
from src.pipelines.graph_builder.pipeline import GraphBuilderPipeline
from src.services.evidence_quality import EvidenceQualityService


def _question() -> Question:
    return Question(
        id="question-1",
        question_text="Will the council approve the proposed public policy?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=2,
        resolution_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
        causal_explanation="A source-backed explanation.",
    )


def _article() -> Article:
    return Article(
        id="article-1",
        title="Council considers a proposed public policy",
        content="The council considered the proposed policy at a public meeting. "
        * 8,
        url="https://example.com/article",
        source="Example",
        published_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        domain=Domain.GENERAL,
        collected_for_question_id="question-1",
    )


def test_graph_builder_waits_for_quality_managed_cleanup(tmp_path: Path) -> None:
    db_path = tmp_path / "quality.db"
    db = GenericDatabase(str(db_path))
    db.create_table(Article)
    article = _article()
    db.save(Article, article)
    pipeline = GraphBuilderPipeline(str(db_path), dataset_version="v2.0")

    assert pipeline._clean_evidence_block(_question()) is None

    service = EvidenceQualityService(db, "v2.0")
    record = service.process_article(article)

    reason = pipeline._clean_evidence_block(_question())
    assert reason is not None
    assert "await cleanup" in reason

    record.clean_markdown = "# Council considers policy\n\nThe council met."
    record.cleaner_model = "cleaner-model"
    record.status = QualityStatus.COMPLETE
    db.save(ArticleQualityRecord, record)

    assert pipeline._clean_evidence_block(_question()) is None
