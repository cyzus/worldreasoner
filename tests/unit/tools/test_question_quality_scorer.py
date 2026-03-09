"""Unit tests for the QuestionQualityScorer tool."""

import json
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone

from src.tools.generators.question_quality_scorer import QuestionQualityScorer, QualityAssessment
from src.tools.base.output_models import QuestionQualityOutput
from src.domain.models import Question, QuestionType, Domain
from src.core.collectors import ResultCollector


@pytest.fixture
def sample_questions():
    """Provides a list of sample Question objects for testing."""
    return [
        Question(
            id="q_001",
            question_text="Will AI sentience be achieved by 2030?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            source="test",
            difficulty=5,
            resolution_date=datetime(2030, 12, 31, tzinfo=timezone.utc),
            context="A simple question about AI.",
            resolution_criteria="Confirmed by a panel of experts.",
        ),
        Question(
            id="q_002",
            question_text="Who will win the 2028 US election?",
            question_type=QuestionType.MCQ,
            options=["Candidate A", "Candidate B"],
            domain=Domain.POLITICS,
            source="test",
            difficulty=4,
            resolution_date=datetime(2028, 11, 8, tzinfo=timezone.utc),
            context="A political question.",
            resolution_criteria="Official election results.",
        ),
    ]


@pytest.fixture
def mock_llm_response():
    """Provides a mock LLM JSON response."""
    return {
        "assessments": [
            {
                "question_id": "q_001",
                "composite_score": 0.85,
                "dimensions": {
                    "interestingness": 0.9,
                    "clarity": 1.0,
                    "verifiability": 0.8,
                    "temporal_validity": 1.0,
                    "context_sufficiency": 0.7,
                    "difficulty_appropriateness": 0.8,
                    "format_consistency": 0.9,
                },
                "reasoning": "A well-formed and interesting question.",
            },
            {
                "question_id": "q_002",
                "composite_score": 0.90,
                "dimensions": {
                    "interestingness": 1.0,
                    "clarity": 0.9,
                    "verifiability": 1.0,
                    "temporal_validity": 1.0,
                    "context_sufficiency": 0.8,
                    "difficulty_appropriateness": 0.8,
                    "format_consistency": 1.0,
                },
                "reasoning": "Excellent question, clear and verifiable.",
            },
        ],
        "overall_quality": "high",
    }


def _expected_weighted_score(dimensions: dict, weights: dict) -> float:
    """Helper to compute expected weighted composite score."""
    return sum(dimensions.get(d, 0.0) * w for d, w in weights.items())


@pytest.mark.asyncio
@patch("src.tools.generators.question_quality_scorer.LiteLLMClient")
async def test_question_quality_scorer_forward(
    mock_llm_client, sample_questions, mock_llm_response
):
    """Test the forward method of QuestionQualityScorer."""
    mock_llm_client.return_value.acomplete = AsyncMock(
        return_value=json.dumps(mock_llm_response)
    )

    scorer = QuestionQualityScorer()
    scorer.llm_client = mock_llm_client.return_value
    result = await scorer.forward(sample_questions)

    # Check that the LLM was called
    mock_llm_client.return_value.acomplete.assert_called_once()

    # forward() returns a QuestionQualityOutput model
    assert isinstance(result, QuestionQualityOutput)
    assert len(result.scores) == 2
    assert result.overall_quality == "high"

    # Composite scores are recalculated with weighted averages
    for score_entry, orig in zip(result.scores, mock_llm_response["assessments"]):
        expected = _expected_weighted_score(orig["dimensions"], scorer.dimension_weights)
        assert score_entry["composite_score"] == pytest.approx(expected, abs=1e-9)


def test_quality_assessment_model():
    """Test Pydantic model for QualityAssessment."""
    data = {
        "question_id": "q_test",
        "composite_score": 0.75,
        "dimensions": {"clarity": 0.8},
        "reasoning": "Looks good.",
    }
    assessment = QualityAssessment(**data)
    assert assessment.question_id == "q_test"
    assert assessment.composite_score == 0.75


@pytest.mark.asyncio
@patch("src.tools.generators.question_quality_scorer.LiteLLMClient")
async def test_scorer_with_collector(
    mock_llm_client, sample_questions, mock_llm_response
):
    """Test that the scorer correctly adds items to a ResultCollector."""
    mock_llm_client.return_value.acomplete = AsyncMock(
        return_value=json.dumps(mock_llm_response)
    )

    collector = ResultCollector[QualityAssessment]()
    scorer = QuestionQualityScorer(collector=collector)
    scorer.llm_client = mock_llm_client.return_value

    await scorer.forward(sample_questions)

    collected_items = collector.get_all()
    assert len(collected_items) == 2
    assert collected_items[0].question_id == "q_001"
    assert collected_items[1].question_id == "q_002"

    # Composite scores are recalculated with weighted averages
    for item, orig in zip(collected_items, mock_llm_response["assessments"]):
        expected = _expected_weighted_score(orig["dimensions"], scorer.dimension_weights)
        assert item.composite_score == pytest.approx(expected, abs=1e-9)


@pytest.mark.asyncio
async def test_scorer_with_no_questions():
    """Test that the scorer returns an empty list when no questions are provided."""
    scorer = QuestionQualityScorer()
    result_json = await scorer.forward([])
    result_data = json.loads(result_json)
    assert result_data == {"assessments": []}
