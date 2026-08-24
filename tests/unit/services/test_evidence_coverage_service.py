"""Question-aware evidence coverage policy tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.pipeline import EvidenceSatisfactionConfig
from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    Domain,
    QualityStatus,
    Question,
    QuestionType,
)
from src.pipelines.construction.models import CoverageAssessmentDraft
from src.services.evidence_coverage_service import EvidenceCoverageService


def make_question(horizon_days: int, question_type: str = "binary") -> Question:
    resolution = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return Question(
        id=f"question-{horizon_days}-{question_type}",
        question_text="Will the documented test outcome occur by its resolution date?",
        question_type=question_type,
        domain=Domain.GENERAL,
        source="test",
        difficulty=2,
        estimated_start_time=resolution - timedelta(days=horizon_days),
        resolution_date=resolution,
        ground_truth=True,
    )


def test_adapts_article_target_by_horizon_and_type(tmp_path: Path) -> None:
    db = GenericDatabase(tmp_path / "coverage-profile.db")
    service = EvidenceCoverageService(db, EvidenceSatisfactionConfig())

    assert service.profile_for(make_question(20)).article_target == 8
    assert service.profile_for(make_question(100)).article_target == 12
    assert service.profile_for(make_question(300)).article_target == 16
    assert service.profile_for(make_question(20, "mcq")).article_target == 10


def test_requires_unique_sources_not_duplicate_article_volume(tmp_path: Path) -> None:
    db = GenericDatabase(tmp_path / "coverage-diversity.db")
    db.create_table(Article)
    db.create_table(ArticleQualityRecord)
    config = EvidenceSatisfactionConfig(min_articles=3, min_unique_sources=3)
    service = EvidenceCoverageService(db, config)
    question = make_question(20)
    records = []
    for index in range(3):
        article = Article(
            id=f"article-{index}",
            title=f"Supported evidence article number {index}",
            content="Substantive evidence content. " * 10,
            url=f"https://same.example.test/{index}",
            source="same.example.test",
            published_date=question.resolution_date,
            domain=Domain.GENERAL,
        )
        record = ArticleQualityRecord(
            id=f"record-{index}",
            article_id=article.id,
            dataset_version="test",
            original_content_hash=f"original-{index}",
            normalized_content_hash=f"normalized-{index}",
            normalized_content=article.content,
            status=QualityStatus.COMPLETE,
            clean_markdown=article.content,
            normalizer_version="test",
        )
        db.save(Article, article)
        db.save(ArticleQualityRecord, record)
        records.append(record)

    assert service.deterministic_gaps(question, records) == [
        "unique_sources (1 < 3)"
    ]


def test_semantic_ledger_exposes_specific_recovery_gaps(tmp_path: Path) -> None:
    db = GenericDatabase(tmp_path / "coverage-ledger.db")
    service = EvidenceCoverageService(db, EvidenceSatisfactionConfig())
    assessment = CoverageAssessmentDraft(
        ready=False,
        ledger={
            "outcome_resolution_supported": True,
            "timeline_covered": False,
            "key_developments_supported": True,
            "counterevidence_considered": False,
            "citations_traceable": True,
            "critical_gaps": ["official final result"],
        },
        rationale="The dossier lacks an intermediate timeline.",
    )

    assert service.semantic_gaps(assessment) == [
        "official final result",
        "timeline coverage",
        "counterevidence or alternative scenario coverage",
    ]


def test_semantic_ledger_enforces_declared_missing_needs(tmp_path: Path) -> None:
    db = GenericDatabase(tmp_path / "coverage-declared-gap.db")
    service = EvidenceCoverageService(db, EvidenceSatisfactionConfig())
    assessment = CoverageAssessmentDraft(
        ready=True,
        ledger={
            "outcome_resolution_supported": True,
            "timeline_covered": True,
            "key_developments_supported": True,
            "counterevidence_considered": True,
            "citations_traceable": True,
        },
        missing_evidence_needs=["official resolution statement"],
        rationale="One declared gap remains.",
    )

    assert service.semantic_gaps(assessment) == [
        "official resolution statement"
    ]


def test_hindsight_policy_allows_bounded_post_resolution_reporting(
    tmp_path: Path,
) -> None:
    db = GenericDatabase(tmp_path / "coverage-dates.db")
    service = EvidenceCoverageService(
        db,
        EvidenceSatisfactionConfig(hindsight_reporting_delay_days=30),
    )
    question = make_question(20)

    def article(days_after: int) -> Article:
        return Article(
            id=f"article-{days_after}",
            title=f"Retrospective report published after {days_after} days",
            content="Substantive retrospective evidence. " * 10,
            source="example.test",
            published_date=question.resolution_date + timedelta(days=days_after),
            domain=Domain.GENERAL,
        )

    assert service.is_hindsight_eligible(question, article(20)) is True
    assert service.is_hindsight_eligible(question, article(31)) is False
