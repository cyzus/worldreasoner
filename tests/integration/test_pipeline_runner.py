"""Integration tests for the unified pipeline runner.

Tests the PipelineRunner class which provides a common interface
for running all pipeline types with progress tracking.
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.cli.core.pipeline_runner import (
    PipelineRunner,
    PipelineType,
    PipelineResult,
    PipelineProgress,
)
from src.core.database import GenericDatabase
from src.domain.models import Question, QuestionType, Domain


class TestPipelineRunner:
    """Integration tests for the unified pipeline runner."""

    @pytest.fixture
    def runner(self, test_db_path):
        """Create a PipelineRunner instance."""
        return PipelineRunner(db_path=test_db_path)

    @pytest.fixture
    def sample_questions(self, test_db_path):
        """Create sample resolved questions for testing."""
        db = GenericDatabase(test_db_path)
        db.create_table(Question)

        # Create test questions with proper resolution
        questions = []
        for i in range(3):
            question = Question(
                id=f"q_test_{i}",
                question_text=f"Test question {i}?",
                question_type=QuestionType.BINARY,
                domain=Domain.POLITICS,
                source="test",
                metadata={},
                ground_truth=True if i % 2 == 0 else False,
                resolution_date=datetime.now(timezone.utc) - timedelta(days=30),
                created_at=datetime.now(timezone.utc) - timedelta(days=60),
            )
            db.save(Question, question)
            questions.append(question)

        return [q.id for q in questions]

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_evidence_pipeline_runs(self, runner, sample_questions):
        """Test that evidence pipeline runs without errors."""
        progress_updates = []

        def on_progress(p: PipelineProgress):
            progress_updates.append(p)
            assert p.current <= p.total
            assert p.stage == "evidence"

        result = await runner.run(
            PipelineType.EVIDENCE,
            sample_questions,
            on_progress=on_progress,
            force_reprocess=True,  # Process even if evidence exists
        )

        # Verify result structure
        assert isinstance(result, PipelineResult)
        assert len(progress_updates) == len(sample_questions)
        assert result.success_count + result.failure_count + result.skip_count == len(
            sample_questions
        )
        assert result.duration_seconds > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_forecast_pipeline_runs(self, runner, sample_questions):
        """Test that forecast pipeline runs without errors."""
        progress_updates = []

        def on_progress(p: PipelineProgress):
            progress_updates.append(p)

        result = await runner.run(
            PipelineType.FORECAST,
            sample_questions,
            on_progress=on_progress,
            mode="knowledge_only",  # Use knowledge-only for faster testing
        )

        assert isinstance(result, PipelineResult)
        assert len(progress_updates) == len(sample_questions)
        assert result.duration_seconds > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_clear_evidence(self, runner, sample_questions):
        """Test evidence clearing functionality."""
        result = await runner.clear_evidence(sample_questions)

        assert "cleared" in result
        assert "failed" in result
        assert len(result["cleared"]) + len(result["failed"]) == len(sample_questions)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_pipeline_with_invalid_questions(self, runner):
        """Test pipeline behavior with invalid question IDs."""
        invalid_ids = ["q_invalid_1", "q_invalid_2"]

        result = await runner.run(
            PipelineType.EVIDENCE,
            invalid_ids,
            on_progress=None,
        )

        # All should fail (question not found)
        assert result.failure_count == len(invalid_ids)
        assert result.success_count == 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_skip_existing_evidence(self, runner, sample_questions, test_db_path):
        """Test that pipeline skips questions with existing evidence."""
        from src.domain.models import CausalHypothesis

        db = GenericDatabase(test_db_path)
        db.create_table(CausalHypothesis)

        # Add a hypothesis to the first question
        hypothesis = CausalHypothesis(
            id="hyp_test_1",
            question_id=sample_questions[0],
            cause_event_id="evt_test_1",
            effect_event_id="evt_test_2",
            causal_mechanism="Test mechanism",
            confidence=0.8,
            causal_strength=0.7,
            created_at=datetime.now(timezone.utc),
        )
        db.save(CausalHypothesis, hypothesis)

        # Run without force_reprocess
        result = await runner.run(
            PipelineType.EVIDENCE,
            sample_questions[:1],  # Only first question
            on_progress=None,
            force_reprocess=False,
        )

        # Should be skipped
        assert result.skip_count == 1
        assert result.success_count == 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_force_reprocess(self, runner, sample_questions, test_db_path):
        """Test that force_reprocess processes questions with existing evidence."""
        from src.domain.models import CausalHypothesis

        db = GenericDatabase(test_db_path)
        db.create_table(CausalHypothesis)

        # Add a hypothesis to the first question
        hypothesis = CausalHypothesis(
            id="hyp_test_1",
            question_id=sample_questions[0],
            cause_event_id="evt_test_1",
            effect_event_id="evt_test_2",
            causal_mechanism="Test mechanism",
            confidence=0.8,
            causal_strength=0.7,
            created_at=datetime.now(timezone.utc),
        )
        db.save(CausalHypothesis, hypothesis)

        # Run with force_reprocess
        result = await runner.run(
            PipelineType.EVIDENCE,
            sample_questions[:1],
            on_progress=None,
            force_reprocess=True,
        )

        # Should not be skipped
        assert result.skip_count == 0
        # May succeed or fail depending on pipeline execution, but shouldn't skip

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_progress_callback_accuracy(self, runner, sample_questions):
        """Test that progress callbacks report accurate information."""
        progress_updates = []

        def on_progress(p: PipelineProgress):
            progress_updates.append(p)
            # Verify progress is sequential
            assert p.current > 0
            assert p.current <= p.total
            # Verify question_id is provided
            assert p.question_id in sample_questions

        result = await runner.run(
            PipelineType.EVIDENCE,
            sample_questions,
            on_progress=on_progress,
        )

        # Verify we got progress for each question
        assert len(progress_updates) == len(sample_questions)

        # Verify progress is sequential
        for i, update in enumerate(progress_updates, 1):
            assert update.current == i


class TestPipelineResult:
    """Test PipelineResult data structure."""

    def test_result_properties(self):
        """Test PipelineResult property calculations."""
        result = PipelineResult(
            processed=[{"id": "q1"}, {"id": "q2"}],
            failed=[{"id": "q3", "error": "test error"}],
            skipped=[{"id": "q4", "reason": "has evidence"}],
            duration_seconds=10.5,
        )

        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.skip_count == 1
        assert result.duration_seconds == 10.5

    def test_empty_result(self):
        """Test empty PipelineResult."""
        result = PipelineResult([], [], [], 0.0)

        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.skip_count == 0
