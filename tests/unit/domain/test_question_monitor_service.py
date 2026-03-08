"""Unit tests for QuestionMonitorService."""

import pytest
from datetime import datetime, timezone

from src.core.database import GenericDatabase
from src.config.pipeline import EvidenceSatisfactionConfig
from src.services.question_monitor_service import (
    QuestionMonitorService,
)
from src.domain.models.question import Question, QuestionType
from src.domain.models.forecast import Forecast, ForecastMode
from src.domain.models.causal_hypothesis import CausalHypothesis
from src.domain.models.event import Event, EventType, EventStatus, CausalRelationType
from src.domain.models.article import Article
from src.domain.models.domain import Domain



@pytest.fixture
def test_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test.db"
    db = GenericDatabase(str(db_path))
    db.create_table(Question)
    db.create_table(Forecast)
    db.create_table(CausalHypothesis)
    db.create_table(Event)
    db.create_table(Article)
    return db


@pytest.fixture
def service(test_db):
    """Create QuestionMonitorService instance."""
    config = EvidenceSatisfactionConfig(
        min_graph_depth=2,
        min_articles=5,
        min_hypotheses=1,
    )
    return QuestionMonitorService(test_db, config)


@pytest.fixture
def resolved_question(test_db):
    """Create a resolved question (has ground truth)."""
    q = Question(
        id="q_resolved_001",
        question_text="Did AI surpass human performance on benchmark X?",
        question_type=QuestionType.BINARY,
        domain=Domain.TECH,
        source="test",
        difficulty=3,
        resolution_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ground_truth={"answer": True},
    )
    test_db.save(Question, q)
    return q


@pytest.fixture
def unresolved_question(test_db):
    """Create an unresolved question (no ground truth)."""
    q = Question(
        id="q_unresolved_001",
        question_text="Will quantum computing be mainstream by 2030?",
        question_type=QuestionType.BINARY,
        domain=Domain.TECH,
        source="test",
        difficulty=2,
        resolution_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
        ground_truth=None,
    )
    test_db.save(Question, q)
    return q


@pytest.fixture
def skipped_question(test_db):
    """Create a question marked for skip."""
    q = Question(
        id="q_skipped_001",
        question_text="Trivial question that is long enough to pass validation check",
        question_type=QuestionType.BINARY,
        domain=Domain.TECH,
        source="test",
        difficulty=1,
        resolution_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ground_truth={"answer": False},
        skip_evidence=True,
    )
    test_db.save(Question, q)
    return q


@pytest.fixture
def question_with_evidence(test_db, resolved_question):
    """Create a question with sufficient evidence."""
    # Create target event
    event = Event(
        id="evt_target_001",
        title="AI Benchmark Result",
        description="AI system achieved human-level performance",
        event_type=EventType.OUTCOME,
        domain=Domain.TECH,
        occurred_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
    )
    test_db.save(Event, event)

    # Update question with outcome event
    resolved_question.outcome_event_ids = [event.id]
    test_db.save(Question, resolved_question)

    # Create actual Article records (service counts via db.count on articles table)
    for i in range(1, 6):
        art = Article(
            id=f"art_{i:03d}",
            title=f"Evidence article number {i} for AI benchmark",
            content="A" * 100,  # min_length=100
            source="test",
            published_date=datetime(2023, 12, i, tzinfo=timezone.utc),
            domain=Domain.TECH,
            collected_for_question_id=resolved_question.id,
        )
        test_db.save(Article, art)

    # Create a chain of 2 hypotheses for graph_depth >= 2
    # Chain: evt_root_001 -> evt_source_001 -> evt_target_001
    hypothesis1 = CausalHypothesis(
        id="hyp_001",
        source_event_id="evt_source_001",
        target_event_id=event.id,
        relation_type=CausalRelationType.CAUSES,
        strength=0.8,
        confidence=0.8,
        reasoning="Funding led to breakthrough",
        discovered_by_question_ids=[resolved_question.id],
        evidence_article_ids=["art_001", "art_002", "art_003", "art_004", "art_005"],
    )
    test_db.save(CausalHypothesis, hypothesis1)

    hypothesis2 = CausalHypothesis(
        id="hyp_002",
        source_event_id="evt_root_001",
        target_event_id="evt_source_001",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.7,
        reasoning="Root cause led to intermediate event",
        discovered_by_question_ids=[resolved_question.id],
        evidence_article_ids=["art_001"],
    )
    test_db.save(CausalHypothesis, hypothesis2)

    return resolved_question


class TestGetEvidenceNeeds:
    """Test get_evidence_needs method."""

    def test_returns_resolved_questions(
        self, service, resolved_question, unresolved_question
    ):
        """Only resolved questions are returned."""
        needs = service.get_evidence_needs()
        ids = [q.id for q in needs]
        assert resolved_question.id in ids
        assert unresolved_question.id not in ids

    def test_excludes_skipped_questions(
        self, service, resolved_question, skipped_question
    ):
        """Skipped questions are not returned."""
        needs = service.get_evidence_needs()
        ids = [q.id for q in needs]
        assert resolved_question.id in ids
        assert skipped_question.id not in ids

    def test_excludes_satisfied_questions(self, service, question_with_evidence):
        """Questions with sufficient evidence are excluded."""
        needs = service.get_evidence_needs()
        ids = [q.id for q in needs]
        # This question has evidence that meets thresholds
        assert question_with_evidence.id not in ids

    def test_domain_filter(self, service, test_db, resolved_question):
        """Domain filter works correctly."""
        # Create a finance question
        q = Question(
            id="q_finance_001",
            question_text="Finance question that is long enough to pass validation check",
            question_type=QuestionType.BINARY,
            domain=Domain.FINANCE,
            source="test",
            difficulty=2,
            resolution_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ground_truth={"answer": True},
        )
        test_db.save(Question, q)

        # Filter by tech
        needs = service.get_evidence_needs(domain="tech")
        ids = [q.id for q in needs]
        assert resolved_question.id in ids
        assert "q_finance_001" not in ids


class TestCheckSatisfaction:
    """Test check_satisfaction method."""

    def test_satisfied_with_sufficient_evidence(self, service, question_with_evidence):
        """Returns satisfied=True when evidence meets thresholds."""
        satisfaction = service.check_satisfaction(question_with_evidence.id)
        assert satisfaction.is_satisfied is True
        assert satisfaction.missing_requirements == []

    def test_unsatisfied_no_evidence(self, service, resolved_question):
        """Returns satisfied=False when no evidence."""
        satisfaction = service.check_satisfaction(resolved_question.id)
        assert satisfaction.is_satisfied is False
        assert satisfaction.hypothesis_count == 0
        assert len(satisfaction.missing_requirements) > 0

    def test_reports_missing_articles(self, service, test_db):
        """Reports correct missing requirements."""
        # Create question with some but not enough evidence
        q = Question(
            id="q_partial_001",
            question_text="Partial evidence question that is long enough to pass validation",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            source="test",
            difficulty=2,
            resolution_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ground_truth={"answer": True},
        )
        test_db.save(Question, q)

        # Create 2 actual articles collected for this question (config requires 5)
        for i in range(1, 3):
            art = Article(
                id=f"art_partial_{i:03d}",
                title=f"Partial evidence article number {i} for question",
                content="B" * 100,
                source="test",
                published_date=datetime(2023, 12, i, tzinfo=timezone.utc),
                domain=Domain.TECH,
                collected_for_question_id=q.id,
            )
            test_db.save(Article, art)

        # Create hypothesis
        hypothesis = CausalHypothesis(
            id="hyp_partial_001",
            source_event_id="evt_001",
            target_event_id="evt_002",
            relation_type=CausalRelationType.CAUSES,
            strength=0.8,
            confidence=0.8,
            reasoning="This reasoning is long enough to pass the validation check",
            discovered_by_question_ids=[q.id],
            evidence_article_ids=["art_partial_001", "art_partial_002"],
        )
        test_db.save(CausalHypothesis, hypothesis)

        satisfaction = service.check_satisfaction(q.id)
        assert satisfaction.is_satisfied is False
        assert satisfaction.article_count == 2
        # Check that articles is mentioned as missing
        missing_str = str(satisfaction.missing_requirements)
        assert "articles" in missing_str


class TestGetForecastReadiness:
    """Test get_forecast_readiness method."""

    def test_knowledge_only_always_available(self, service, resolved_question):
        """KNOWLEDGE_ONLY mode is always available."""
        readiness = service.get_forecast_readiness(resolved_question.id)
        assert ForecastMode.KNOWLEDGE_ONLY in readiness.available_modes

    def test_container_requires_satisfaction(
        self, service, unresolved_question, question_with_evidence
    ):
        """CONTAINER mode requires evidence satisfaction."""
        # Without evidence (unresolved_question has no evidence)
        readiness = service.get_forecast_readiness(unresolved_question.id)
        assert ForecastMode.CONTAINER not in readiness.available_modes

        # With sufficient evidence
        readiness = service.get_forecast_readiness(question_with_evidence.id)
        assert ForecastMode.CONTAINER in readiness.available_modes

    def test_tool_config_includes_causal(self, service, resolved_question):
        """Tool config allows causal tools for all modes."""
        readiness = service.get_forecast_readiness(resolved_question.id)
        for mode, config in readiness.tool_config.items():
            # Causal tools can be enabled for any mode
            assert hasattr(config, "causal_tools")

    def test_nonexistent_question_raises(self, service):
        """Raises error for nonexistent question."""
        with pytest.raises(ValueError):
            service.get_forecast_readiness("nonexistent")


class TestGetModelUsageStats:
    """Test get_model_usage_stats method."""

    def test_aggregates_by_model(self, service, test_db, resolved_question):
        """Aggregates forecasts by model name."""
        # Create forecasts from different models
        for i, model in enumerate(["gpt-4", "gpt-4", "claude-3"]):
            f = Forecast(
                id=f"f_{i:03d}",
                session_id="sess_001",
                question_id=resolved_question.id,
                prediction=True,
                confidence=0.8,
                reasoning="This reasoning needs to be at least 50 characters long to pass the pydantic validation check logic.",
                model_name=model,
                is_correct=True if i < 2 else False,
            )
            test_db.save(Forecast, f)

        stats = service.get_model_usage_stats()

        # Should have 2 models
        assert len(stats) == 2

        # gpt-4 should have 2 forecasts
        gpt4_stats = next(s for s in stats if s.model_name == "gpt-4")
        assert gpt4_stats.forecast_count == 2
        assert gpt4_stats.correct_count == 2
        assert gpt4_stats.accuracy == 1.0

    def test_filter_by_model(self, service, test_db, resolved_question):
        """Can filter to specific model."""
        for i, model in enumerate(["gpt-4", "claude-3"]):
            f = Forecast(
                id=f"f_filter_{i:03d}",
                session_id="sess_001",
                question_id=resolved_question.id,
                prediction=True,
                confidence=0.8,
                reasoning="This reasoning needs to be at least 50 characters long to pass the pydantic validation check logic.",
                model_name=model,
            )
            test_db.save(Forecast, f)

        stats = service.get_model_usage_stats(model_name="gpt-4")
        assert len(stats) == 1
        assert stats[0].model_name == "gpt-4"
