"""Unit tests for the QuestionQualityRankingStage."""

import pytest
from unittest.mock import AsyncMock
from src.domain.models.question import Question, QuestionType, Domain
from src.pipelines.collection.stage_quality import QuestionQualityRankingStage
from src.config.pipeline import QuestionQualityConfig
from src.tools.generators.question_quality_scorer import QualityAssessment
from datetime import datetime, timezone


@pytest.fixture
def sample_questions():
    """Returns a list of sample Question objects for testing."""
    return [
        Question(
            id="q_001",
            question_text="Will tech stocks rise in Q1 2026?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=1,
            source="test",
            resolution_date=datetime.now(timezone.utc),
        ),
        Question(
            id="q_002",
            question_text="Will AI adoption increase in 2026?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=1,
            source="test",
            resolution_date=datetime.now(timezone.utc),
        ),
        Question(
            id="q_003",
            question_text="Will semiconductor prices drop soon?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=1,
            source="test",
            resolution_date=datetime.now(timezone.utc),
        ),
    ]


@pytest.mark.asyncio
async def test_question_quality_ranking_stage(sample_questions):
    """Test the process method of QuestionQualityRankingStage."""
    config = QuestionQualityConfig(enabled=True, batch_size=2)
    stage = QuestionQualityRankingStage(config, db_path=":memory:")

    # Mock the scorer's forward method
    async def mock_forward_side_effect(questions):
        # This function will be the side effect of the mock
        for q in questions:
            if q.id == "q_001":
                stage.scorer.collector.add(
                    QualityAssessment(
                        question_id="q_001",
                        composite_score=0.9,
                        dimensions={},
                        reasoning="",
                    )
                )
            elif q.id == "q_002":
                stage.scorer.collector.add(
                    QualityAssessment(
                        question_id="q_002",
                        composite_score=0.7,
                        dimensions={},
                        reasoning="",
                    )
                )
            elif q.id == "q_003":
                stage.scorer.collector.add(
                    QualityAssessment(
                        question_id="q_003",
                        composite_score=0.95,
                        dimensions={},
                        reasoning="",
                    )
                )
        return "{}"

    stage.scorer.forward = AsyncMock(side_effect=mock_forward_side_effect)

    # Run the stage
    result = await stage.process(sample_questions)

    # Assertions
    assert len(result) == 3
    # Check that scores are attached
    assert result[0].quality_score == 0.95  # q_003
    assert result[1].quality_score == 0.9  # q_001
    assert result[2].quality_score == 0.7  # q_002

    # Check sorting
    assert result[0].id == "q_003"
    assert result[1].id == "q_001"
    assert result[2].id == "q_002"
