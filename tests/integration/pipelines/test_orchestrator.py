"""Integration tests for the QuestionCollectionOrchestrator."""

import pytest
from src.pipelines.collection.orchestrator import (
    QuestionCollectionOrchestrator,
    OrchestratorConfig,
)
from src.config.collection_goal import CollectionGoal
from src.domain.models.question import Question
from src.core.database import GenericDatabase
from src.pipelines.collection.runner_base import QuestionSourceRunner, CollectionResult
from src.domain.models import Question, QuestionType, Domain
from datetime import datetime, timezone
from src.config.pipeline import QuestionQualityConfig


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orchestrator_with_quality_ranking(persistent_test_db_path):
    """Test that the orchestrator runs the quality ranking stage and saves scores."""
    # Setup - use a fresh database
    import os

    if os.path.exists(persistent_test_db_path):
        os.remove(persistent_test_db_path)

    db = GenericDatabase(persistent_test_db_path)
    db.create_table(Question)

    goal = CollectionGoal(
        total_questions=2,
        type_distribution={QuestionType.BINARY: 2},
        category_distribution={Domain.TECH: 2},
    )

    # Mock sources
    class MockSourceRunner(QuestionSourceRunner):
        async def collect(self, count: int, **kwargs) -> CollectionResult:
            questions = [
                Question(
                    id=f"q_mock_{i}",
                    question_text=f"This is a mock question of sufficient length {i}",
                    question_type=QuestionType.BINARY,
                    domain=Domain.TECH,
                    source="mock",
                    difficulty=1,
                    resolution_date=datetime.now(timezone.utc),
                )
                for i in range(count)
            ]
            return CollectionResult(
                success=True,
                questions=questions,
                source_name="mock",
                requested_count=count,
                actual_count=len(questions),
            )

    mock_source = MockSourceRunner(source_name="mock")

    config = OrchestratorConfig(
        quality_ranking=QuestionQualityConfig(enabled=True, batch_size=2)
    )

    orchestrator = QuestionCollectionOrchestrator(
        goal=goal,
        sources={"mock": mock_source},
        config=config,
        db_path=persistent_test_db_path,
    )

    # Mock the quality scorer to avoid actual LLM calls
    from src.tools.generators.question_quality_scorer import QualityAssessment

    async def mock_forward(questions):
        for q in questions:
            # Provide high scores that won't trigger skip_evidence
            orchestrator.quality_stage.scorer.collector.add(
                QualityAssessment(
                    question_id=q.id,
                    composite_score=0.88,
                    dimensions={
                        "verifiability": 0.9,
                        "interestingness": 0.85,
                        "clarity": 0.9,
                        "temporal_validity": 0.85,
                    },
                    reasoning="mocked",
                )
            )
        return "{}"

    orchestrator.quality_stage.scorer.forward = mock_forward

    # Run orchestrator
    result = await orchestrator.collect_until_goal_met()

    # Assertions
    assert result.goal_met
    assert len(result.questions) == 2

    # Check that questions in the DB have scores
    questions_from_db = db.get_many(Question)
    assert len(questions_from_db) == 2
    for question in questions_from_db:
        assert question.quality_score is not None
        assert 0.0 <= question.quality_score <= 1.0
