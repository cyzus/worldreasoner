"""Unit tests for estimated_start_time field."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.domain.models import Question
from src.domain.models.question import QuestionType
from src.domain.models.domain import Domain


def test_estimated_start_time_optional():
    """Test that estimated_start_time is optional."""
    q = Question(
        id="test_1",
        question_text="Will X happen by the end of 2025?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
        # estimated_start_time not provided
    )
    assert q.estimated_start_time is None


def test_estimated_start_time_valid():
    """Test valid estimated_start_time."""
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    resolution = datetime(2025, 12, 31, tzinfo=timezone.utc)

    q = Question(
        id="test_2",
        question_text="Will X happen by the end of 2025?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=resolution,
        estimated_start_time=start,
    )
    assert q.estimated_start_time == start


def test_estimated_start_time_validation_future():
    """Test that estimated_start_time must be before resolution_date."""
    resolution = datetime(2025, 12, 31, tzinfo=timezone.utc)
    invalid_start = datetime(2026, 1, 1, tzinfo=timezone.utc)  # After resolution

    with pytest.raises(ValidationError, match="must be before resolution_date"):
        Question(
            id="test_3",
            question_text="Will X happen by the end of 2025?",
            question_type=QuestionType.BINARY,
            domain=Domain.GENERAL,
            source="test",
            difficulty=3,
            resolution_date=resolution,
            estimated_start_time=invalid_start,
        )


def test_estimated_start_time_validation_same_as_resolution():
    """Test that estimated_start_time cannot equal resolution_date."""
    same_date = datetime(2025, 12, 31, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="must be before resolution_date"):
        Question(
            id="test_4",
            question_text="Will X happen by the end of 2025?",
            question_type=QuestionType.BINARY,
            domain=Domain.GENERAL,
            source="test",
            difficulty=3,
            resolution_date=same_date,
            estimated_start_time=same_date,  # Same as resolution
        )


def test_estimated_start_time_serialization():
    """Test JSON serialization with estimated_start_time."""
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    resolution = datetime(2025, 12, 31, tzinfo=timezone.utc)

    q = Question(
        id="test_5",
        question_text="Will X happen by the end of 2025?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=resolution,
        estimated_start_time=start,
    )

    # Serialize to JSON
    json_data = q.model_dump_json()

    # Deserialize from JSON
    q2 = Question.model_validate_json(json_data)

    assert q2.estimated_start_time == start


def test_estimated_start_time_none_serialization():
    """Test JSON serialization when estimated_start_time is None."""
    q = Question(
        id="test_6",
        question_text="Will X happen by the end of 2025?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
        estimated_start_time=None,
    )

    # Serialize to JSON
    json_data = q.model_dump_json()

    # Deserialize from JSON
    q2 = Question.model_validate_json(json_data)

    assert q2.estimated_start_time is None


def test_estimated_start_time_past_date():
    """Test that estimated_start_time can be a past date."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    resolution = datetime(2020, 12, 31, tzinfo=timezone.utc)

    q = Question(
        id="test_7",
        question_text="Did X happen in 2020?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=resolution,
        estimated_start_time=start,
    )

    assert q.estimated_start_time == start
    assert q.estimated_start_time < q.resolution_date


def test_estimated_start_time_very_close_to_resolution():
    """Test that estimated_start_time can be very close to resolution_date (but still before)."""
    resolution = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    start = datetime(2025, 12, 31, 23, 59, 58, tzinfo=timezone.utc)  # 1 second before

    q = Question(
        id="test_8",
        question_text="Will X happen by the end of 2025?",
        question_type=QuestionType.BINARY,
        domain=Domain.GENERAL,
        source="test",
        difficulty=3,
        resolution_date=resolution,
        estimated_start_time=start,
    )

    assert q.estimated_start_time == start
    assert q.estimated_start_time < q.resolution_date
