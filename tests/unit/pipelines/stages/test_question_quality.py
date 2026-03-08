"""Unit tests for the QuestionQualityRankingStage."""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.pipelines.collection.stage_quality import QuestionQualityRankingStage
from src.config.pipeline import QuestionQualityConfig
from src.domain.models import Question, QuestionType, Domain
from src.tools.generators.question_quality_scorer import QualityAssessment


@pytest.fixture
def sample_questions():
    """Provides a list of sample Question objects for testing."""
    return [
        Question(
            id="q_001",
            question_text="Will tech stocks rise in Q1 2026?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=3,
            source="test",
            resolution_date=datetime.now(timezone.utc),
        ),
        Question(
            id="q_002",
            question_text="Which party wins the next election?",
            question_type=QuestionType.MCQ,
            domain=Domain.POLITICS,
            difficulty=4,
            source="test",
            resolution_date=datetime.now(timezone.utc),
            options=["A", "B"],
        ),
        Question(
            id="q_003",
            question_text="What will the GDP growth rate be?",
            question_type=QuestionType.QUANTITY,
            domain=Domain.FINANCE,
            difficulty=5,
            source="test",
            resolution_date=datetime.now(timezone.utc),
        ),
    ]


@pytest.fixture
def mock_assessments():
    """Provides a list of mock QualityAssessment objects."""
    return [
        QualityAssessment(
            question_id="q_001", composite_score=0.7, dimensions={}, reasoning=""
        ),
        QualityAssessment(
            question_id="q_002", composite_score=0.9, dimensions={}, reasoning=""
        ),
        QualityAssessment(
            question_id="q_003", composite_score=0.8, dimensions={}, reasoning=""
        ),
    ]


@pytest.mark.asyncio
async def test_quality_ranking_stage_process(sample_questions, mock_assessments):
    """Test the process method of QuestionQualityRankingStage."""
    config = QuestionQualityConfig(enabled=True, batch_size=2)
    stage = QuestionQualityRankingStage(config, db_path="dummy.db")

    # Mock the scorer's forward method
    with patch.object(stage.scorer, "forward", new_callable=MagicMock) as mock_forward:
        # This is a bit tricky because the stage uses a collector.
        # We'll simulate the collector's behavior.
        def side_effect(questions_batch):
            for q in questions_batch:
                assessment = next(
                    (a for a in mock_assessments if a.question_id == q.id), None
                )
                if assessment and stage.scorer.collector is not None:
                    stage.scorer.collector.add(assessment)
            return asyncio.sleep(0)  # scorer.forward is async

        mock_forward.side_effect = side_effect

        result = await stage.process(sample_questions)

        assert len(result) == 3
        # Check that questions are sorted by score (0.9, 0.8, 0.7)
        assert result[0].id == "q_002"
        assert result[0].quality_score == 0.9
        assert result[1].id == "q_003"
        assert result[1].quality_score == 0.8
        assert result[2].id == "q_001"
        assert result[2].quality_score == 0.7


@pytest.mark.asyncio
async def test_quality_ranking_stage_disabled(sample_questions):
    """Test that the stage does nothing when disabled."""
    config = QuestionQualityConfig(enabled=False)
    stage = QuestionQualityRankingStage(config, db_path="dummy.db")

    with patch.object(stage.scorer, "forward") as mock_forward:
        result = await stage.process(sample_questions)
        mock_forward.assert_not_called()
        # Output should be the same as input
        assert result == sample_questions


@pytest.mark.asyncio
async def test_question_not_in_assessment(sample_questions):
    """Test that a question not in the assessment results is handled gracefully."""
    config = QuestionQualityConfig(enabled=True)
    stage = QuestionQualityRankingStage(config, db_path="dummy.db")

    # Only provide assessment for q_001
    mock_assessment = [
        QualityAssessment(
            question_id="q_001", composite_score=0.7, dimensions={}, reasoning=""
        )
    ]

    with patch.object(stage.scorer, "forward", new_callable=MagicMock) as mock_forward:

        def side_effect(questions_batch):
            if stage.scorer.collector is not None:
                stage.scorer.collector.add(mock_assessment[0])
            return asyncio.sleep(0)

        mock_forward.side_effect = side_effect

        result = await stage.process(sample_questions)

        assert len(result) == 3
        q1 = next(q for q in result if q.id == "q_001")
        q2 = next(q for q in result if q.id == "q_002")
        assert q1.quality_score == 0.7
        assert q2.quality_score is None  # Should not have a score
