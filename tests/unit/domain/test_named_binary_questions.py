from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.domain.models.question import Domain, Question, QuestionType
from src.services.forecast_submission_service import ForecastSubmissionService


def _question() -> Question:
    return Question(
        id="q_named_binary",
        question_text="Men's Knockout - Slovakia vs. Finland",
        question_type=QuestionType.BINARY,
        domain=Domain.SPORTS,
        source="polymarket",
        difficulty=2,
        resolution_date=datetime(2026, 2, 1, tzinfo=timezone.utc),
        options=["Slovakia", "Finland"],
        ground_truth="Finland",
    )


def test_named_binary_question_accepts_option_label_prediction():
    assert _question().validate_prediction("Finland")


def test_named_binary_submission_parses_option_label():
    valid, parsed, error = ForecastSubmissionService(MagicMock()).validate_prediction(
        _question(),
        "Finland",
    )

    assert valid
    assert parsed == "Finland"
    assert error is None


def test_named_binary_submission_maps_boolean_to_option_order():
    service = ForecastSubmissionService(MagicMock())

    valid, parsed, error = service.validate_prediction(_question(), "false")

    assert valid
    assert parsed == "Finland"
    assert error is None
