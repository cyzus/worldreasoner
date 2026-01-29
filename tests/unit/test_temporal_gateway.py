"""Unit tests for TemporalGateway."""

import pytest
from datetime import datetime, timezone, timedelta

from src.core.temporal_gateway import TemporalGateway, TemporalContext, ValidationResult
from src.domain.models import (
    Article,
    Event,
    Question,
    Forecast,
    EventStatus,
    EventType,
    QuestionType,
)


class TestTemporalGateway:
    """Test TemporalGateway filtering logic."""

    @pytest.fixture
    def cutoff_date(self):
        """Cutoff date for tests: Nov 4, 2024."""
        return datetime(2024, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def gateway(self, cutoff_date):
        """Create temporal gateway."""
        return TemporalGateway(cutoff_date=cutoff_date)

    @pytest.fixture
    def article_before_cutoff(self, cutoff_date):
        """Article published before cutoff."""
        return Article(
            id="art_before",
            title="Article Before Cutoff",
            content="This article was published before the cutoff date. "
            * 10,  # > 100 chars
            source="Test Source",
            published_date=cutoff_date - timedelta(days=1),
            domain="tech",
        )

    @pytest.fixture
    def article_after_cutoff(self, cutoff_date):
        """Article published after cutoff."""
        return Article(
            id="art_after",
            title="Article After Cutoff",
            content="This article was published after the cutoff date. "
            * 10,  # > 100 chars
            source="Test Source",
            published_date=cutoff_date + timedelta(days=1),
            domain="tech",
        )

    @pytest.fixture
    def article_at_cutoff(self, cutoff_date):
        """Article published exactly at cutoff."""
        return Article(
            id="art_at_cutoff",
            title="Article At Cutoff",
            content="This article was published exactly at the cutoff date. "
            * 10,  # > 100 chars
            source="Test Source",
            published_date=cutoff_date,
            domain="tech",
        )

    @pytest.fixture
    def event_before_cutoff(self, cutoff_date):
        """Event that occurred before cutoff."""
        return Event(
            id="evt_before",
            title="Event Before Cutoff",
            description="This event occurred before the cutoff date.",
            event_type=EventType.OUTCOME,
            domain="tech",
            status=EventStatus.OCCURRED,
            occurred_date=cutoff_date - timedelta(days=2),
        )

    @pytest.fixture
    def event_after_cutoff(self, cutoff_date):
        """Event that occurred after cutoff."""
        return Event(
            id="evt_after",
            title="Event After Cutoff",
            description="This event occurred after the cutoff date.",
            event_type=EventType.OUTCOME,
            domain="tech",
            status=EventStatus.OCCURRED,
            occurred_date=cutoff_date + timedelta(days=2),
        )

    @pytest.fixture
    def event_none_date(self):
        """Event with None occurred_date."""
        return Event(
            id="evt_none",
            title="Event No Date",
            description="This event has no occurred_date.",
            event_type=EventType.MILESTONE,  # Use valid EventType
            domain="tech",
            status=EventStatus.PREDICTED,
            occurred_date=None,
        )

    # TemporalGateway initialization tests

    def test_init_with_timezone_aware_date(self, cutoff_date):
        """Should initialize with timezone-aware datetime."""
        gateway = TemporalGateway(cutoff_date=cutoff_date)
        assert gateway.cutoff_date == cutoff_date

    def test_init_with_naive_datetime_raises_error(self):
        """Should raise ValueError for naive datetime."""
        naive_date = datetime(2024, 11, 4, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            TemporalGateway(cutoff_date=naive_date)

    # Article filtering tests

    def test_filter_articles_before_cutoff(self, gateway, article_before_cutoff):
        """Articles before cutoff should be included."""
        articles = [article_before_cutoff]
        filtered = gateway.filter_articles(articles)
        assert len(filtered) == 1
        assert filtered[0].id == "art_before"

    def test_filter_articles_after_cutoff(self, gateway, article_after_cutoff):
        """Articles after cutoff should be excluded."""
        articles = [article_after_cutoff]
        filtered = gateway.filter_articles(articles)
        assert len(filtered) == 0

    def test_filter_articles_at_cutoff(self, gateway, article_at_cutoff):
        """Articles exactly at cutoff should be excluded (< not <=)."""
        articles = [article_at_cutoff]
        filtered = gateway.filter_articles(articles)
        assert len(filtered) == 0

    def test_filter_articles_mixed(
        self, gateway, article_before_cutoff, article_after_cutoff, article_at_cutoff
    ):
        """Should filter mixed list correctly."""
        articles = [article_before_cutoff, article_after_cutoff, article_at_cutoff]
        filtered = gateway.filter_articles(articles)
        assert len(filtered) == 1  # Only before cutoff (at cutoff is excluded)
        assert article_before_cutoff in filtered
        assert article_at_cutoff not in filtered
        assert article_after_cutoff not in filtered

    def test_filter_articles_empty_list(self, gateway):
        """Should handle empty list."""
        filtered = gateway.filter_articles([])
        assert filtered == []

    # Event filtering tests

    def test_filter_events_before_cutoff(self, gateway, event_before_cutoff):
        """Events before cutoff should be included."""
        events = [event_before_cutoff]
        filtered = gateway.filter_events(events)
        assert len(filtered) == 1
        assert filtered[0].id == "evt_before"

    def test_filter_events_after_cutoff(self, gateway, event_after_cutoff):
        """Events after cutoff should be excluded."""
        events = [event_after_cutoff]
        filtered = gateway.filter_events(events)
        assert len(filtered) == 0

    def test_filter_events_with_none_date(self, gateway, event_none_date):
        """Events with None occurred_date should be excluded."""
        events = [event_none_date]
        filtered = gateway.filter_events(events)
        assert len(filtered) == 0

    def test_filter_events_mixed(
        self, gateway, event_before_cutoff, event_after_cutoff, event_none_date
    ):
        """Should filter mixed event list correctly."""
        events = [event_before_cutoff, event_after_cutoff, event_none_date]
        filtered = gateway.filter_events(events)
        assert len(filtered) == 1  # Only before cutoff
        assert filtered[0].id == "evt_before"

    # Accessibility tests

    def test_is_article_accessible_before(self, gateway, article_before_cutoff):
        """Should return True for article before cutoff."""
        assert gateway.is_article_accessible(article_before_cutoff) is True

    def test_is_article_accessible_after(self, gateway, article_after_cutoff):
        """Should return False for article after cutoff."""
        assert gateway.is_article_accessible(article_after_cutoff) is False

    def test_is_event_accessible_before(self, gateway, event_before_cutoff):
        """Should return True for event before cutoff."""
        assert gateway.is_event_accessible(event_before_cutoff) is True

    def test_is_event_accessible_after(self, gateway, event_after_cutoff):
        """Should return False for event after cutoff."""
        assert gateway.is_event_accessible(event_after_cutoff) is False

    def test_is_event_accessible_none_date(self, gateway, event_none_date):
        """Should return False for event with None occurred_date."""
        assert gateway.is_event_accessible(event_none_date) is False

    # Forecast validation tests

    def test_validate_forecast_success(self, gateway, cutoff_date):
        """Valid forecast should pass validation."""
        question = Question(
            id="q_test",
            question_text="Will the technology event occur as predicted in the next week?",
            question_type=QuestionType.BINARY,
            domain="tech",
            source="test",
            difficulty=3,
            cutoff_date=cutoff_date,
            resolution_date=cutoff_date + timedelta(days=2),
            ground_truth=True,
        )

        forecast = Forecast(
            id="fcst_test",
            session_id="sess_test",
            question_id="q_test",
            prediction=True,
            confidence=0.7,
            reasoning="Based on thorough analysis of available information and trends, this prediction is made.",
            simulated_date=cutoff_date - timedelta(hours=1),
        )

        result = gateway.validate_forecast(forecast, question)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_forecast_simulated_date_after_cutoff(self, cutoff_date):
        """Forecast with simulated_date after cutoff should fail."""
        gateway = TemporalGateway(cutoff_date=cutoff_date)

        question = Question(
            id="q_test",
            question_text="Will the technology event occur as predicted in the next week?",
            question_type=QuestionType.BINARY,
            domain="tech",
            source="test",
            difficulty=3,
            cutoff_date=cutoff_date,
            resolution_date=cutoff_date + timedelta(days=2),
            ground_truth=True,
        )

        forecast = Forecast(
            id="fcst_test",
            session_id="sess_test",
            question_id="q_test",
            prediction=True,
            confidence=0.7,
            reasoning="Based on thorough analysis of available information and trends, this prediction is made.",
            simulated_date=cutoff_date + timedelta(hours=1),  # AFTER cutoff!
        )

        result = gateway.validate_forecast(forecast, question)
        assert result.valid is False
        assert len(result.errors) > 0
        assert "after cutoff" in result.errors[0]

    def test_validate_forecast_no_cutoff_date_uses_created_at(self, cutoff_date):
        """Should use question.created_at if cutoff_date is None."""
        gateway = TemporalGateway(cutoff_date=cutoff_date)

        question = Question(
            id="q_test",
            question_text="Will the technology event occur as predicted in the next week?",
            question_type=QuestionType.BINARY,
            domain="tech",
            source="test",
            difficulty=3,
            cutoff_date=None,  # No cutoff
            resolution_date=cutoff_date + timedelta(days=2),
            ground_truth=True,
            created_at=cutoff_date,
        )

        forecast = Forecast(
            id="fcst_test",
            session_id="sess_test",
            question_id="q_test",
            prediction=True,
            confidence=0.7,
            reasoning="Based on thorough analysis of available information and trends, this prediction is made.",
            simulated_date=cutoff_date - timedelta(hours=1),
        )

        result = gateway.validate_forecast(forecast, question)
        assert len(result.warnings) == 1
        assert "no cutoff_date" in result.warnings[0].lower()


class TestTemporalContext:
    """Test TemporalContext context manager."""

    def test_context_sets_cutoff(self):
        """Should set cutoff date when entering context."""
        cutoff = datetime(2024, 11, 4, tzinfo=timezone.utc)

        assert TemporalContext.get_current_cutoff() is None

        with TemporalContext(cutoff_date=cutoff):
            assert TemporalContext.get_current_cutoff() == cutoff

        assert TemporalContext.get_current_cutoff() is None

    def test_context_is_active(self):
        """Should report active status correctly."""
        cutoff = datetime(2024, 11, 4, tzinfo=timezone.utc)

        assert TemporalContext.is_active() is False

        with TemporalContext(cutoff_date=cutoff):
            assert TemporalContext.is_active() is True

        assert TemporalContext.is_active() is False

    def test_nested_contexts(self):
        """Should handle nested contexts correctly."""
        cutoff1 = datetime(2024, 11, 1, tzinfo=timezone.utc)
        cutoff2 = datetime(2024, 11, 4, tzinfo=timezone.utc)

        with TemporalContext(cutoff_date=cutoff1):
            assert TemporalContext.get_current_cutoff() == cutoff1

            with TemporalContext(cutoff_date=cutoff2):
                assert TemporalContext.get_current_cutoff() == cutoff2

            # Should restore outer context
            assert TemporalContext.get_current_cutoff() == cutoff1

        assert TemporalContext.get_current_cutoff() is None

    def test_context_with_naive_datetime_raises_error(self):
        """Should raise ValueError for naive datetime."""
        naive_date = datetime(2024, 11, 4, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            with TemporalContext(cutoff_date=naive_date):
                pass


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_init_valid(self):
        """Should initialize as valid."""
        result = ValidationResult(valid=True, errors=[])
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error_sets_invalid(self):
        """Adding error should set valid to False."""
        result = ValidationResult(valid=True, errors=[])
        result.add_error("Test error")
        assert result.valid is False
        assert "Test error" in result.errors

    def test_add_warning(self):
        """Should add warning without changing validity."""
        result = ValidationResult(valid=True, errors=[])
        result.add_warning("Test warning")
        assert result.valid is True
        assert "Test warning" in result.warnings

    def test_multiple_errors(self):
        """Should accumulate multiple errors."""
        result = ValidationResult(valid=True, errors=[])
        result.add_error("Error 1")
        result.add_error("Error 2")
        assert len(result.errors) == 2
        assert result.valid is False
