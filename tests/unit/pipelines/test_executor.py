"""Unit tests for PipelineExecutor."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from src.pipelines.executor import PipelineExecutor
from src.pipelines.types import PipelineType, PipelineProgress, PipelineResult
from src.config import Config
from src.domain.models import Question, QuestionType, Domain


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return Mock(spec=Config)


@pytest.fixture
def test_db_path(tmp_path):
    """Create temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def executor(mock_config, test_db_path):
    """Create PipelineExecutor instance."""
    return PipelineExecutor(mock_config, test_db_path)


@pytest.fixture
def sample_question():
    """Create a sample question."""
    return Question(
        id="q_test",
        question_text="Will AI surpass human intelligence by 2030?",
        question_type=QuestionType.BINARY,
        domain=Domain.TECH,
        source="test",
        difficulty=3,
        resolution_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


class TestExecute:
    """Test main execute method."""

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_evidence(self, executor):
        """Execute dispatches EVIDENCE type to _run_evidence."""
        with patch.object(
            executor, "_run_evidence", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            await executor.execute(
                PipelineType.EVIDENCE, ["q1", "q2"], on_progress=None
            )

            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == ["q1", "q2"]  # question_ids

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_adaptive_evidence(self, executor):
        """Execute dispatches ADAPTIVE_EVIDENCE type to _run_adaptive_evidence."""
        with patch.object(
            executor, "_run_adaptive_evidence", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            await executor.execute(
                PipelineType.ADAPTIVE_EVIDENCE, ["q1"], on_progress=None
            )

            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_forecast(self, executor):
        """Execute dispatches FORECAST type to _run_forecast."""
        with patch.object(
            executor, "_run_forecast", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            await executor.execute(PipelineType.FORECAST, ["q1"], on_progress=None)

            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_collection(self, executor):
        """Execute dispatches COLLECTION type to _run_collection."""
        with patch.object(
            executor, "_run_collection", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            await executor.execute(
                PipelineType.COLLECTION,
                [],
                on_progress=None,
                goal_path="config/test_goal.yaml",
            )

            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_measures_duration(self, executor):
        """Execute measures and sets duration_seconds."""
        with patch.object(
            executor, "_run_evidence", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            result = await executor.execute(
                PipelineType.EVIDENCE, ["q1"], on_progress=None
            )

            assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_passes_kwargs(self, executor):
        """Execute passes additional kwargs to type-specific methods."""
        with patch.object(
            executor, "_run_evidence", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult([], [], [], 0.0)

            await executor.execute(
                PipelineType.EVIDENCE,
                ["q1"],
                on_progress=None,
                force_reprocess=True,
                evidence_window_days=180,
            )

            # Check kwargs were passed
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["force_reprocess"] is True
            assert call_kwargs["evidence_window_days"] == 180


class TestProgressTracking:
    """Test progress callback functionality."""

    @pytest.mark.asyncio
    async def test_progress_callback_called(self, executor):
        """Progress callback is invoked during execution."""
        progress_updates = []

        def on_progress(p: PipelineProgress):
            progress_updates.append(p)

        # Mock the evidence pipeline execution
        with patch.object(
            executor, "_run_evidence", new_callable=AsyncMock
        ) as mock_run:
            # Simulate progress updates within the method
            async def mock_execution(*args, **kwargs):
                # on_progress is passed as second positional arg
                callback = args[1] if len(args) > 1 else kwargs.get("on_progress")
                if callback:
                    callback(PipelineProgress(1, 2, "q1", "test", "Processing"))
                return PipelineResult([{"id": "q1"}], [], [], 0.0)

            mock_run.side_effect = mock_execution

            await executor.execute(
                PipelineType.EVIDENCE, ["q1"], on_progress=on_progress
            )

            assert len(progress_updates) > 0
            assert progress_updates[0].current == 1
            assert progress_updates[0].total == 2


class TestClearEvidence:
    """Test clear_evidence method."""

    @pytest.mark.asyncio
    async def test_clear_evidence_success(self, executor):
        """Clear evidence delegates to QuestionService."""
        from src.services.question_service import QuestionService

        with patch.object(QuestionService, "clear_evidence") as mock_clear:
            mock_clear.return_value = {"articles": 5, "events": 3, "hypotheses": 2}

            result = await executor.clear_evidence(["q1", "q2"], cascade=True)

            assert len(result["cleared"]) == 2
            assert "q1" in result["cleared"]
            assert "q2" in result["cleared"]

    @pytest.mark.asyncio
    async def test_clear_evidence_handles_errors(self, executor):
        """Clear evidence handles errors gracefully."""
        from src.services.question_service import QuestionService

        with patch.object(QuestionService, "clear_evidence") as mock_clear:
            # First call succeeds, second fails
            mock_clear.side_effect = [
                {"articles": 1, "events": 1, "hypotheses": 1},
                Exception("Database error"),
            ]

            result = await executor.clear_evidence(["q1", "q2"], cascade=True)

            assert len(result["cleared"]) == 1
            assert len(result["failed"]) == 1
            assert result["failed"][0]["id"] == "q2"


class TestHelperMethods:
    """Test helper methods."""

    def test_load_article_sources(self, executor):
        """Load article sources from config file."""
        with patch("builtins.open", create=True) as mock_open:
            with patch("yaml.safe_load") as mock_yaml:
                mock_yaml.return_value = {
                    "sources": [
                        {
                            "domain": "tech",
                            "name": "TechSource",
                            "url": "http://tech.com",
                            "scraper_type": "rss",
                        },
                        {
                            "domain": "politics",
                            "name": "PoliSource",
                            "url": "http://poli.com",
                            "scraper_type": "rss",
                        },
                    ]
                }

                sources = executor._load_article_sources(domains=["tech"])

                assert len(sources) == 1
                assert sources[0].domain == "tech"

    def test_create_news_runner(self, executor):
        """Create NewsBasedRunner with configuration."""
        from src.pipelines.collection.runner_news import NewsBasedRunner

        with patch.object(executor, "_load_article_sources") as mock_load:
            mock_load.return_value = []

            runner = executor._create_news_runner(
                article_sources=[],
                domains=["tech"],
                question_types=["binary"],
                max_articles_per_source=5,
                days_back=7,
            )

            assert isinstance(runner, NewsBasedRunner)


class TestResultFormatting:
    """Test result formatting and structure."""

    @pytest.mark.asyncio
    async def test_result_has_correct_structure(self, executor):
        """Pipeline results have correct structure."""
        with patch.object(
            executor, "_run_evidence", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = PipelineResult(
                processed=[{"id": "q1", "articles": 5}],
                failed=[{"id": "q2", "error": "Failed"}],
                skipped=[{"id": "q3", "reason": "Already processed"}],
                duration_seconds=10.5,
            )

            result = await executor.execute(
                PipelineType.EVIDENCE, ["q1", "q2", "q3"], on_progress=None
            )

            assert result.success_count == 1
            assert result.failure_count == 1
            assert result.skip_count == 1
            # duration_seconds is overwritten by execute() with actual elapsed time
            assert result.duration_seconds >= 0
