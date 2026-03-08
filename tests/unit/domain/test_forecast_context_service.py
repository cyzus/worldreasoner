"""Unit tests for ForecastContextService."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from src.services.forecast_context_service import ForecastContextService, ForecastContext
from src.domain.models import Question
from src.domain.models.question import QuestionType
from src.utils.enums import Domain


class TestParseContextFromHeaders:
    """Tests for parse_context_from_headers method."""

    def test_parse_valid_headers(self):
        """Should parse all headers correctly."""
        service = ForecastContextService(Mock())

        headers = {
            "x-question-id": "q123",
            "x-simulated-date": "2024-04-01T00:00:00Z",
            "x-knowledge-cutoff": "2024-01-01T00:00:00Z",
            "x-session-id": "session123",
            "x-model-name": "claude-3",
            "x-forecast-mode": "api",
            "x-database-path": "/path/to/db.sqlite",
        }

        context = service.parse_context_from_headers(headers)

        assert context.question_id == "q123"
        assert context.simulated_date == datetime(2024, 4, 1, tzinfo=timezone.utc)
        assert context.knowledge_cutoff == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert context.session_id == "session123"
        assert context.model_name == "claude-3"
        assert context.forecast_mode == "api"
        assert context.db_path == "/path/to/db.sqlite"

    def test_parse_minimal_headers(self):
        """Should parse with only required headers."""
        service = ForecastContextService(Mock())

        headers = {
            "X-Question-ID": "q123",  # Test case-insensitive
            "X-Simulated-Date": "2024-04-01T00:00:00Z",
        }

        context = service.parse_context_from_headers(headers)

        assert context.question_id == "q123"
        assert context.simulated_date == datetime(2024, 4, 1, tzinfo=timezone.utc)
        assert context.knowledge_cutoff is None
        assert context.model_name == "unknown"
        assert context.forecast_mode == "container"
        assert context.db_path is None

    def test_parse_generates_session_id_if_missing(self):
        """Should generate session_id if not provided."""
        service = ForecastContextService(Mock())

        headers = {"x-question-id": "q123", "x-simulated-date": "2024-04-01T00:00:00Z"}

        context = service.parse_context_from_headers(headers)

        assert context.session_id is not None
        assert context.session_id.startswith("session_q123_")

    def test_parse_missing_question_id(self):
        """Should raise ValueError if question_id missing."""
        service = ForecastContextService(Mock())

        headers = {"x-simulated-date": "2024-04-01T00:00:00Z"}

        with pytest.raises(ValueError, match="X-Question-ID"):
            service.parse_context_from_headers(headers)

    def test_parse_missing_simulated_date(self):
        """Should raise ValueError if simulated_date missing."""
        service = ForecastContextService(Mock())

        headers = {"x-question-id": "q123"}

        with pytest.raises(ValueError, match="X-Simulated-Date"):
            service.parse_context_from_headers(headers)

    def test_parse_invalid_date_format(self):
        """Invalid date format falls back to current UTC time via parse_flexible_datetime."""
        service = ForecastContextService(Mock())

        headers = {"x-question-id": "q123", "x-simulated-date": "invalid-date"}

        context = service.parse_context_from_headers(headers)
        # parse_flexible_datetime returns fallback (datetime.now(UTC)) for unparseable strings
        assert context.simulated_date is not None
        assert context.simulated_date.tzinfo is not None


class TestValidateContext:
    """Tests for validate_context method."""

    def test_validate_valid_context(self):
        """Should pass validation for valid context."""
        service = ForecastContextService(Mock())

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
            session_id="session123",
        )

        # Should not raise
        service.validate_context(context)

    def test_validate_knowledge_cutoff_after_simulated_date(self):
        """Should raise ValueError if knowledge_cutoff >= simulated_date."""
        service = ForecastContextService(Mock())

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=datetime(
                2024, 5, 1, tzinfo=timezone.utc
            ),  # After simulated_date
            session_id="session123",
        )

        with pytest.raises(ValueError, match="must be BEFORE"):
            service.validate_context(context)

    def test_validate_knowledge_cutoff_equals_simulated_date(self):
        """Should raise ValueError if knowledge_cutoff == simulated_date."""
        service = ForecastContextService(Mock())

        same_date = datetime(2024, 4, 1, tzinfo=timezone.utc)
        context = ForecastContext(
            question_id="q123",
            simulated_date=same_date,
            knowledge_cutoff=same_date,
            session_id="session123",
        )

        with pytest.raises(ValueError, match="must be BEFORE"):
            service.validate_context(context)

    def test_validate_no_knowledge_cutoff(self):
        """Should pass validation when no knowledge_cutoff."""
        service = ForecastContextService(Mock())

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=None,
            session_id="session123",
        )

        # Should not raise
        service.validate_context(context)


class TestGetQuestionForContext:
    """Tests for get_question_for_context method."""

    def test_get_question_from_cache(self):
        """Should return cached question if available."""
        db = Mock()
        service = ForecastContextService(db)

        question = Question(
            id="q123",
            question_text="Will the test question be resolved by June 2024?",
            question_type=QuestionType.BINARY,
            domain=Domain.POLITICS,
            source="test",
            difficulty=3,
            resolution_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=None,
            session_id="session123",
            question=question,  # Cached
        )

        result = service.get_question_for_context(context)

        assert result == question
        db.get.assert_not_called()  # Should not query DB

    def test_get_question_from_db(self):
        """Should load question from DB if not cached."""
        db = Mock()
        question = Question(
            id="q123",
            question_text="Will the test question be resolved by June 2024?",
            question_type=QuestionType.BINARY,
            domain=Domain.POLITICS,
            source="test",
            difficulty=3,
            resolution_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        db.get.return_value = question

        service = ForecastContextService(db)

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=None,
            session_id="session123",
            question=None,  # Not cached
        )

        result = service.get_question_for_context(context)

        assert result == question
        db.get.assert_called_once_with(Question, "q123")
        assert context.question == question  # Should cache

    def test_get_question_with_custom_db_path(self):
        """Should use custom db_path if provided in context."""
        db = Mock()
        db.db_path = "/default/db.sqlite"

        service = ForecastContextService(db)

        # Mock GenericDatabase constructor in service_base where get_db is defined
        import src.services.service_base

        original_db = src.services.service_base.GenericDatabase

        custom_db = Mock()
        question = Question(
            id="q123",
            question_text="Will the test question be resolved by June 2024?",
            question_type=QuestionType.BINARY,
            domain=Domain.POLITICS,
            source="test",
            difficulty=3,
            resolution_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        custom_db.get.return_value = question

        def mock_db_constructor(db_path):
            if db_path == "/custom/db.sqlite":
                return custom_db
            return db

        src.services.service_base.GenericDatabase = mock_db_constructor

        try:
            context = ForecastContext(
                question_id="q123",
                simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                knowledge_cutoff=None,
                session_id="session123",
                db_path="/custom/db.sqlite",
                question=None,
            )

            result = service.get_question_for_context(context)

            assert result == question
            custom_db.get.assert_called_once_with(Question, "q123")
        finally:
            src.services.service_base.GenericDatabase = original_db

    def test_get_question_not_found(self):
        """Should raise ValueError if question not found."""
        db = Mock()
        db.get.return_value = None

        service = ForecastContextService(db)

        context = ForecastContext(
            question_id="q123",
            simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            knowledge_cutoff=None,
            session_id="session123",
            question=None,
        )

        with pytest.raises(ValueError, match="Question not found"):
            service.get_question_for_context(context)
