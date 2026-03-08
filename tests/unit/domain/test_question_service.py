"""Unit tests for QuestionService domain logic."""

import pytest
from datetime import datetime, timezone

from src.core.database import GenericDatabase
from src.services.question_service import QuestionService
from src.domain.models import Question, Article, Event, CausalHypothesis
from src.domain.models import (
    QuestionType,
    Domain,
    EventStatus,
    EventType,
    CausalRelationType,
)


@pytest.fixture
def test_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test.db"
    db = GenericDatabase(str(db_path))
    from src.domain.models.event_outcome_impact import EventOutcomeImpact
    db.create_table(Question)
    db.create_table(Article)
    db.create_table(Event)
    db.create_table(CausalHypothesis)
    db.create_table(EventOutcomeImpact)
    return db


@pytest.fixture
def service(test_db):
    """Create QuestionService instance."""
    return QuestionService(test_db)


@pytest.fixture
def sample_question(test_db):
    """Create a sample question."""
    q = Question(
        id="q_test_001",
        question_text="Will AI surpass human intelligence by 2030?",
        question_type=QuestionType.BINARY,
        domain=Domain.TECH,
        source="test",
        difficulty=3,
        resolution_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    test_db.save(Question, q)
    return q


@pytest.fixture
def sample_article(test_db, sample_question):
    """Create a sample article collected for the question."""
    article = Article(
        id="art_001",
        url="https://example.com/ai-article",
        title="AI Progress Report on Deep Learning Advances",
        content="This is a detailed article about AI development and progress in the field of artificial intelligence. "
        * 3,  # Make it >100 chars
        source="TechNews",
        published_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        domain=Domain.TECH,
        collected_for_question_id=sample_question.id,
    )
    test_db.save(Article, article)
    return article


@pytest.fixture
def sample_event(test_db, sample_question, sample_article):
    """Create a sample event extracted for the question."""
    event = Event(
        id="evt_001",
        title="Major AI Breakthrough",
        description="Significant advancement in artificial intelligence research and development announced",
        event_type=EventType.MILESTONE,
        domain=Domain.TECH,
        occurred_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
        article_ids=[sample_article.id],
        extracted_for_question_id=sample_question.id,
    )
    test_db.save(Event, event)
    return event


@pytest.fixture
def sample_hypothesis(test_db, sample_question, sample_event):
    """Create a sample causal hypothesis."""
    # Create another event to link
    event2 = Event(
        id="evt_002",
        title="AI Funding Increase",
        description="Significant increase in funding for AI research and development programs",
        event_type=EventType.DECISION,
        domain=Domain.TECH,
        occurred_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
        article_ids=[],
        extracted_for_question_id=sample_question.id,
    )
    test_db.save(Event, event2)

    hypothesis = CausalHypothesis(
        id="hyp_001",
        source_event_id=event2.id,
        target_event_id=sample_event.id,
        relation_type=CausalRelationType.CAUSES,
        strength=0.8,
        confidence=0.8,
        reasoning="Increased funding typically enables more research and development",
        discovered_by_question_ids=[sample_question.id],
    )
    test_db.save(CausalHypothesis, hypothesis)
    return hypothesis


class TestHasEvidence:
    """Test has_evidence method."""

    def test_has_evidence_true(self, service, sample_question, sample_hypothesis):
        """Question with hypotheses has evidence."""
        assert service.has_evidence(sample_question.id) is True

    def test_has_evidence_false(self, service, sample_question):
        """Question without hypotheses has no evidence."""
        assert service.has_evidence(sample_question.id) is False

    def test_has_evidence_nonexistent_question(self, service):
        """Nonexistent question has no evidence."""
        assert service.has_evidence("nonexistent") is False


class TestGetEvidenceStatus:
    """Test get_evidence_status bulk check."""

    def test_bulk_check_mixed(
        self, service, test_db, sample_question, sample_hypothesis
    ):
        """Check multiple questions with mixed evidence status."""
        # Create another question without evidence
        q2 = Question(
            id="q_test_002",
            question_text="Will quantum computing be mainstream by 2025?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            source="test",
            difficulty=2,
            resolution_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        test_db.save(Question, q2)

        status = service.get_evidence_status([sample_question, q2])

        assert status[sample_question.id] is True
        assert status[q2.id] is False

    def test_bulk_check_empty_list(self, service):
        """Empty list returns empty dict."""
        assert service.get_evidence_status([]) == {}


class TestClearEvidence:
    """Test clear_evidence method."""

    def test_clear_evidence_success(
        self, service, sample_question, sample_article, sample_event, sample_hypothesis
    ):
        """Clear evidence removes articles, events, and hypotheses."""
        result = service.clear_evidence(sample_question.id, cascade=True)

        assert result["articles"] == 1
        assert result["events"] == 2  # evt_001 and evt_002
        assert result["hypotheses"] == 1

    def test_clear_evidence_nonexistent_question(self, service):
        """Clearing evidence for nonexistent question returns zeros."""
        result = service.clear_evidence("nonexistent", cascade=True)

        assert result["articles"] == 0
        assert result["events"] == 0
        assert result["hypotheses"] == 0

    def test_clear_evidence_preserves_pre_existing_events(
        self, service, test_db, sample_question, sample_article
    ):
        """Pre-existing events (target_event_id, related_event_ids) are preserved."""
        # Create a pre-existing event (referenced in question, not extracted for it)
        pre_event = Event(
            id="evt_pre",
            title="Pre-existing Event",
            description="Event that existed before question was created",
            event_type=EventType.OUTCOME,
            domain=Domain.TECH,
            occurred_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
            status=EventStatus.OCCURRED,
            article_ids=[],
            extracted_for_question_id=None,  # Not extracted for this question
        )
        test_db.save(Event, pre_event)

        # Update question to reference this event via outcome_event_ids
        sample_question.outcome_event_ids = [pre_event.id]
        test_db.save(Question, sample_question)

        # Clear evidence
        service.clear_evidence(sample_question.id, cascade=True)

        # Pre-existing event should not be deleted
        assert test_db.get(Event, pre_event.id) is not None


class TestAnalyzeCascade:
    """Test analyze_cascade method."""

    def test_analyze_cascade_identifies_orphaned_items(
        self, service, sample_question, sample_article, sample_event, sample_hypothesis
    ):
        """Analyze correctly identifies orphaned items."""
        analysis = service.analyze_cascade(sample_question.id)

        assert sample_article.id in analysis["orphaned"]["articles"]
        assert sample_event.id in analysis["orphaned"]["events"]
        assert sample_hypothesis.id in analysis["orphaned"]["causal_hypotheses_delete"]

    def test_analyze_cascade_nonexistent_question(self, service):
        """Analysis of nonexistent question returns error."""
        analysis = service.analyze_cascade("nonexistent")
        assert "error" in analysis

    def test_analyze_cascade_provenance_stats(
        self, service, sample_question, sample_article
    ):
        """Analysis includes provenance statistics."""
        analysis = service.analyze_cascade(sample_question.id)

        assert "provenance_stats" in analysis
        assert "articles_by_field" in analysis["provenance_stats"]
        assert "events_by_field" in analysis["provenance_stats"]


class TestDeleteQuestion:
    """Test delete_question method."""

    def test_delete_question_with_cascade(
        self,
        service,
        test_db,
        sample_question,
        sample_article,
        sample_event,
        sample_hypothesis,
    ):
        """Delete question with cascade removes all related items."""
        result = service.delete_question(
            sample_question.id, cascade=True, dry_run=False
        )

        assert result["success"] is True
        assert result["summary"]["questions"] == 1
        assert result["summary"]["articles"] > 0
        assert result["summary"]["events"] > 0

        # Question should be deleted
        assert test_db.get(Question, sample_question.id) is None

    def test_delete_question_without_cascade(self, service, test_db, sample_question):
        """Delete question without cascade only removes the question."""
        result = service.delete_question(
            sample_question.id, cascade=False, dry_run=False
        )

        assert result["success"] is True
        assert test_db.get(Question, sample_question.id) is None

    def test_delete_question_dry_run(self, service, test_db, sample_question):
        """Dry run doesn't delete anything."""
        result = service.delete_question(sample_question.id, cascade=True, dry_run=True)

        assert result["dry_run"] is True
        assert test_db.get(Question, sample_question.id) is not None

    def test_delete_nonexistent_question(self, service):
        """Deleting nonexistent question returns error."""
        result = service.delete_question("nonexistent", cascade=True, dry_run=False)
        assert "error" in result


class TestDeleteEvent:
    """Test delete_event method."""

    def test_delete_event_with_cascade(
        self, service, test_db, sample_event, sample_hypothesis
    ):
        """Delete event with cascade removes hypotheses."""
        result = service.delete_event(sample_event.id, cascade=True, dry_run=False)

        assert result["success"] is True
        assert test_db.get(Event, sample_event.id) is None

    def test_delete_event_dry_run(self, service, test_db, sample_event):
        """Dry run doesn't delete event."""
        result = service.delete_event(sample_event.id, cascade=True, dry_run=True)

        assert result["dry_run"] is True
        assert test_db.get(Event, sample_event.id) is not None

    def test_delete_event_referenced_by_question(
        self, service, test_db, sample_question
    ):
        """Cannot delete event referenced by a question."""
        # Create event referenced by question
        event = Event(
            id="evt_ref",
            title="Referenced Event",
            description="Event referenced by a question in the database",
            event_type=EventType.OUTCOME,
            domain=Domain.TECH,
            occurred_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            status=EventStatus.OCCURRED,
            article_ids=[],
        )
        test_db.save(Event, event)

        sample_question.outcome_event_ids = [event.id]
        test_db.save(Question, sample_question)

        result = service.delete_event(event.id, cascade=True, dry_run=False)
        assert "error" in result


class TestUpdateQuestion:
    """Test update_question method."""

    def test_update_question_success(self, service, test_db, sample_question):
        """Update question fields successfully."""
        result = service.update_question(
            sample_question.id, {"difficulty": 5, "quality_score": 0.9}
        )

        assert result["success"] is True
        assert "difficulty" in result["updated"]

        # Verify update
        updated_q = test_db.get(Question, sample_question.id)
        assert updated_q.difficulty == 5
        assert updated_q.quality_score == 0.9

    def test_update_nonexistent_question(self, service):
        """Updating nonexistent question returns error."""
        result = service.update_question("nonexistent", {"difficulty": 5})
        assert "error" in result
