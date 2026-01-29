"""Integration tests for the EvidencePipeline."""

import pytest
from datetime import datetime, timezone, timedelta

from src.pipelines.evidence.pipeline import EvidencePipeline
from src.config.pipeline import EvidencePipelineConfig
from src.config.database import DatabaseConfig
from src.domain.models import Question, QuestionType, Domain
from src.core.database import GenericDatabase


@pytest.fixture
def resolved_questions_with_scores():
    """Provides a list of resolved questions with quality scores."""
    now = datetime.now(timezone.utc)
    return [
        Question(
            id="resolved_q_1",
            question_text="Q1",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=3,
            resolution_date=now - timedelta(days=10),
            ground_truth=True,
            quality_score=0.9,
        ),
        Question(
            id="resolved_q_2",
            question_text="Q2",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=3,
            resolution_date=now - timedelta(days=10),
            ground_truth=True,
            quality_score=0.5,
        ),
        Question(
            id="resolved_q_3",
            question_text="Q3",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=3,
            resolution_date=now - timedelta(days=10),
            ground_truth=True,
            quality_score=0.7,
        ),
        Question(
            id="unscored_q",
            question_text="Q4",
            question_type=QuestionType.BINARY,
            domain=Domain.TECH,
            difficulty=3,
            resolution_date=now - timedelta(days=10),
            ground_truth=True,
            quality_score=None,  # No score
        ),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evidence_pipeline_quality_filtering(
    persistent_test_db_path, resolved_questions_with_scores
):
    """Test that the EvidencePipeline correctly filters and sorts questions by quality score."""

    # Save test questions to the database
    db = GenericDatabase(persistent_test_db_path)
    db.create_table(Question)
    for q in resolved_questions_with_scores:
        db.save(Question, q)

    evidence_config = EvidencePipelineConfig(
        max_questions=10, skip_already_processed=False
    )
    db_config = DatabaseConfig(db_path=persistent_test_db_path)

    # Run pipeline with a quality score threshold of 0.6
    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        min_quality_score=0.6,
    )

    # Mock the _process_single_question to avoid running the full pipeline
    async def mock_process(question):
        return {"question_id": question.id}

    with patch.object(pipeline, "_process_single_question", side_effect=mock_process):
        await pipeline.run()

        processed_questions = pipeline.resolved_questions

        # Should process 2 questions (0.9 and 0.7)
        assert len(processed_questions) == 2

        # Should be sorted by score
        assert processed_questions[0].id == "resolved_q_1"  # score 0.9
        assert processed_questions[1].id == "resolved_q_3"  # score 0.7

        processed_ids = {q.id for q in processed_questions}
        assert "resolved_q_2" not in processed_ids  # score 0.5, below threshold
        assert "unscored_q" not in processed_ids  # no score, below threshold
