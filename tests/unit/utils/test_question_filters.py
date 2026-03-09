"""Tests for question filtering utilities."""

import pytest
from datetime import datetime, timezone, timedelta

from src.domain.models import Question, QuestionType, Domain
from src.config.collection_goal import QualityRequirements
from src.services.question_filters import (
    filter_questions_by_type,
    filter_questions_by_category,
    apply_quality_requirements,
    filter_questions,
    filter_resolved_questions,
    filter_by_quality_score,
    tag_questions_with_source,
)


@pytest.fixture
def sample_questions():
    """Create sample questions for testing."""
    now = datetime.now(timezone.utc)

    return [
        Question(
            id="q_001",
            question_text="Will technology stocks rise this year based on current market trends?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=2,
            resolution_date=now + timedelta(days=30),
            resolution_criteria="Market index increases by 5% or more",
            source="test",
            metadata={"category": "tech"},
        ),
        Question(
            id="q_002",
            question_text="What will be the GDP growth rate for the next fiscal quarter assessment?",
            question_type=QuestionType.QUANTITY,
            domain=Domain.FINANCE,
            difficulty=4,
            resolution_date=now + timedelta(days=60),
            resolution_criteria="Official government statistics release",
            source="test",
            metadata={"category": "finance"},
        ),
        Question(
            id="q_003",
            question_text="Will the election results be announced within the expected timeframe?",
            question_type=QuestionType.BINARY,
            domain=Domain.POLITICS,
            difficulty=3,
            resolution_date=now + timedelta(days=90),
            resolution_criteria="Official electoral commission announcement",
            source="test",
            metadata={"category": "politics"},
            ground_truth=True,
        ),
    ]


def test_filter_questions_by_type(sample_questions):
    """Test filtering by question type."""
    filtered = filter_questions_by_type(
        sample_questions,
        allowed_types=["binary"],
    )

    assert len(filtered) == 2
    assert all(q.question_type == QuestionType.BINARY for q in filtered)


def test_filter_questions_by_category_dict(sample_questions):
    """Test filtering by category with dict."""
    filtered = filter_questions_by_category(
        sample_questions,
        category_filter={"tech": 1, "finance": 1},
    )

    assert len(filtered) == 2
    categories = {q.metadata["category"] for q in filtered}
    assert categories == {"tech", "finance"}


def test_filter_questions_by_category_list(sample_questions):
    """Test filtering by category with list."""
    filtered = filter_questions_by_category(
        sample_questions,
        category_filter=["politics"],
    )

    assert len(filtered) == 1
    assert filtered[0].metadata["category"] == "politics"


def test_apply_quality_requirements(sample_questions):
    """Test quality requirements filtering."""
    requirements = QualityRequirements(
        min_difficulty=3,
        max_difficulty=5,
        min_resolution_days=50,
        max_resolution_days=100,
    )

    filtered = apply_quality_requirements(sample_questions, requirements)

    # Should filter out q_001 (difficulty 2, resolution 30 days)
    # Should keep q_002 (difficulty 4, resolution 60 days)
    # Should keep q_003 despite 90 days resolution (has ground_truth)
    assert len(filtered) == 2
    assert "q_001" not in [q.id for q in filtered]


def test_filter_questions_combined(sample_questions):
    """Test combined filtering."""
    requirements = QualityRequirements(
        min_difficulty=2,
        max_difficulty=4,
    )

    filtered = filter_questions(
        sample_questions,
        type_filter=["binary"],
        category_filter=["tech", "politics"],
        quality_requirements=requirements,
    )

    # Should keep q_001 (boolean, tech, difficulty 2)
    # Should keep q_003 (boolean, politics, difficulty 3)
    # Should filter q_002 (not boolean)
    assert len(filtered) == 2
    assert all(q.question_type == QuestionType.BINARY for q in filtered)


def test_filter_resolved_questions(sample_questions):
    """Test filtering by resolution status."""
    resolved = filter_resolved_questions(sample_questions, resolved_only=True)
    assert len(resolved) == 1
    assert resolved[0].id == "q_003"

    unresolved = filter_resolved_questions(sample_questions, resolved_only=False)
    assert len(unresolved) == 2
    assert all(q.ground_truth is None for q in unresolved)


def test_filter_by_quality_score(sample_questions):
    """Test filtering by quality score."""
    # Add quality scores
    sample_questions[0].quality_score = 0.8
    sample_questions[1].quality_score = 0.6
    sample_questions[2].quality_score = 0.9

    filtered = filter_by_quality_score(sample_questions, min_score=0.7)

    assert len(filtered) == 2
    assert all(q.quality_score >= 0.7 for q in filtered)


def test_tag_questions_with_source(sample_questions):
    """Test tagging questions with source."""
    # Remove existing source/metadata
    for q in sample_questions:
        q.source = None
        q.metadata = {}

    tag_questions_with_source(sample_questions, "polymarket")

    for q in sample_questions:
        assert q.source == "polymarket"
        assert q.metadata["source"] == "polymarket"
        assert "category" in q.metadata
