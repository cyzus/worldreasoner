"""Unit tests for MCP forecasting server tool functions.

Tests the MCP tool functions (get_question, fetch_article, submit_forecast, etc.)
by mocking the underlying services and context extraction.

Since @mcp.tool() wraps functions in FunctionTool objects (not directly callable),
we test via the underlying function references stored on the FunctionTool.fn attribute.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock
from pydantic import BaseModel

from src.services.forecast_context_service import ForecastContext
from src.domain.models import Question, Article
from src.domain.models.question import QuestionType
from src.utils.enums import Domain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LONG_CONTENT = (
    "The latest inflation data shows consumer prices rising at 4.2% annually. "
    "This marks a significant increase from previous quarters and has major implications "
    "for monetary policy decisions in the coming months."
)  # >100 chars


def _get_tool_fn(tool_obj):
    """Extract the underlying function from a FastMCP FunctionTool."""
    # FunctionTool stores the original function as .fn
    if hasattr(tool_obj, "fn"):
        return tool_obj.fn
    # Fallback: if it's already callable (e.g. during testing without FastMCP)
    return tool_obj


def _to_data(result):
    """Normalize tool output to dict for assertions."""
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True)
    if isinstance(result, str):
        return json.loads(result)
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported tool result type: {type(result)}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def forecast_context():
    """Standard forecast context for tests."""
    return ForecastContext(
        question_id="q123",
        simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
        knowledge_cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
        session_id="session_test_123",
        model_name="test-model",
        forecast_mode="container",
    )


@pytest.fixture
def test_question():
    """Standard test question."""
    return Question(
        id="q123",
        question_text="Will inflation exceed 5% by June 2024?",
        question_type=QuestionType.BINARY,
        domain=Domain.FINANCE,
        source="test",
        difficulty=3,
        resolution_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def test_article():
    """Standard test article."""
    return Article(
        id="art_001",
        title="Inflation Report Q1 2024",
        content=LONG_CONTENT,
        url="https://example.com/inflation",
        source="test_source",
        domain=Domain.FINANCE,
        published_date=datetime(2024, 3, 15, tzinfo=timezone.utc),
        word_count=150,
    )


@pytest.fixture
def mock_ctx():
    """Mock MCP Context object."""
    ctx = Mock()
    ctx.fastmcp_context = None
    return ctx


# ---------------------------------------------------------------------------
# _get_context_from_mcp tests
# ---------------------------------------------------------------------------


class TestGetContextFromMcp:
    """Tests for _get_context_from_mcp helper."""

    def test_returns_cached_context(self, forecast_context, mock_ctx):
        """Should return context from ContextVar if available."""
        from src.api.mcp_forecasting_server import _get_context_from_mcp, _current_context

        token = _current_context.set(forecast_context)
        try:
            result = _get_context_from_mcp(mock_ctx)
            assert result.question_id == "q123"
            assert result.simulated_date == datetime(2024, 4, 1, tzinfo=timezone.utc)
        finally:
            _current_context.reset(token)

    def test_raises_when_no_context(self, mock_ctx):
        """Should raise ValueError when no context available."""
        from src.api.mcp_forecasting_server import _get_context_from_mcp, _current_context

        token = _current_context.set(None)
        try:
            with pytest.raises(ValueError, match="Forecasting context not initialized"):
                _get_context_from_mcp(mock_ctx)
        finally:
            _current_context.reset(token)


# ---------------------------------------------------------------------------
# get_question tool tests
# ---------------------------------------------------------------------------


class TestGetQuestionTool:
    """Tests for get_question MCP tool."""

    def test_returns_question_details(self, mock_ctx, forecast_context, test_question):
        """Should return question details with temporal context."""
        from src.api.mcp_forecasting_server import get_question, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(get_question)

        token = _current_context.set(forecast_context)
        mock_context_service = Mock()
        mock_context_service.get_question_for_context.return_value = test_question
        original = server.context_service
        server.context_service = mock_context_service

        try:
            result = fn(mock_ctx)
            data = _to_data(result)

            assert data["question"]["id"] == "q123"
            assert data["question"]["question_type"] == "binary"
            assert data["question"]["domain"] == "finance"
            assert "temporal_context" in data
            assert "instructions" in data
            assert "FORECASTING SCENARIO" in data["instructions"]
        finally:
            _current_context.reset(token)
            server.context_service = original

    def test_returns_error_on_missing_context(self, mock_ctx):
        """Should return error JSON when context missing."""
        from src.api.mcp_forecasting_server import get_question, _current_context

        fn = _get_tool_fn(get_question)

        token = _current_context.set(None)
        try:
            result = fn(mock_ctx)
            data = _to_data(result)
            assert "error" in data
        finally:
            _current_context.reset(token)

    def test_falls_back_to_metadata_options_when_missing(self, mock_ctx, forecast_context):
        """Should include metadata options in response if top-level options is None."""
        from src.api.mcp_forecasting_server import get_question, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(get_question)

        question = Question(
            id="q_meta_opts",
            question_text="Will policy X pass by June 2026?",
            question_type=QuestionType.MCQ,
            domain=Domain.POLITICS,
            source="polymarket",
            difficulty=3,
            resolution_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            options=None,
            metadata={"options": ["Yes", "No"]},
        )

        token = _current_context.set(forecast_context)
        mock_context_service = Mock()
        mock_context_service.get_question_for_context.return_value = question
        original = server.context_service
        server.context_service = mock_context_service

        try:
            result = fn(mock_ctx)
            data = _to_data(result)
            assert data["question"]["options"] == ["Yes", "No"]
        finally:
            _current_context.reset(token)
            server.context_service = original


# ---------------------------------------------------------------------------
# fetch_article tool tests
# ---------------------------------------------------------------------------


class TestFetchArticleTool:
    """Tests for fetch_article MCP tool."""

    def test_returns_article_content(self, mock_ctx, forecast_context, test_article):
        """Should return article content within temporal window."""
        from src.api.mcp_forecasting_server import fetch_article, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(fetch_article)

        token = _current_context.set(forecast_context)
        original_db = server.db
        server.db = Mock()
        server.db.db_path = "test.db"

        with patch("src.api.mcp_forecasting_server.ArticleOperationsService") as MockArticleOps:
            mock_ops = Mock()
            mock_ops.fetch_article.return_value = test_article
            MockArticleOps.return_value = mock_ops

            try:
                result = fn(mock_ctx, "art_001")
                data = _to_data(result)

                assert data["id"] == "art_001"
                assert data["title"] == "Inflation Report Q1 2024"
                assert "content" in data
                mock_ops.fetch_article.assert_called_once_with(
                    "art_001", forecast_context.simulated_date
                )
            finally:
                _current_context.reset(token)
                server.db = original_db

    def test_returns_error_for_missing_article(self, mock_ctx, forecast_context):
        """Should return error when article not found."""
        from src.api.mcp_forecasting_server import fetch_article, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(fetch_article)

        token = _current_context.set(forecast_context)
        original_db = server.db
        server.db = Mock()
        server.db.db_path = "test.db"

        with patch("src.api.mcp_forecasting_server.ArticleOperationsService") as MockArticleOps:
            mock_ops = Mock()
            mock_ops.fetch_article.return_value = None
            MockArticleOps.return_value = mock_ops

            try:
                result = fn(mock_ctx, "nonexistent")
                data = _to_data(result)
                assert "error" in data
            finally:
                _current_context.reset(token)
                server.db = original_db

    def test_returns_error_for_future_article(self, mock_ctx, forecast_context):
        """Should return error when article is after simulated date."""
        from src.api.mcp_forecasting_server import fetch_article, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(fetch_article)

        token = _current_context.set(forecast_context)
        original_db = server.db
        server.db = Mock()
        server.db.db_path = "test.db"

        with patch("src.api.mcp_forecasting_server.ArticleOperationsService") as MockArticleOps:
            mock_ops = Mock()
            mock_ops.fetch_article.side_effect = ValueError(
                "Article published after simulated date"
            )
            MockArticleOps.return_value = mock_ops

            try:
                result = fn(mock_ctx, "art_future")
                data = _to_data(result)
                assert "error" in data
            finally:
                _current_context.reset(token)
                server.db = original_db


# ---------------------------------------------------------------------------
# temporal_search_articles tool tests
# ---------------------------------------------------------------------------


class TestTemporalSearchArticlesTool:
    """Tests for temporal_search_articles MCP tool."""

    @pytest.mark.asyncio
    async def test_search_returns_articles(self, mock_ctx, forecast_context, test_article):
        """Should return search results filtered by simulated date."""
        from src.api.mcp_forecasting_server import temporal_search_articles, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(temporal_search_articles)

        token = _current_context.set(forecast_context)
        original_db = server.db
        server.db = Mock()
        server.db.db_path = "test.db"

        original_hs = server.hybrid_search
        mock_hs = Mock()
        server.hybrid_search = mock_hs

        with patch(
            "src.api.mcp_forecasting_server.ArticleOperationsService"
        ) as MockArticleOps:
            mock_ops_instance = AsyncMock()
            mock_ops_instance.search_articles = AsyncMock(return_value=[test_article])
            MockArticleOps.return_value = mock_ops_instance

            try:
                result = await fn(mock_ctx, "inflation report")
                data = _to_data(result)

                assert data["count"] == 1
                assert data["articles"][0]["id"] == "art_001"
                assert data["query"] == "inflation report"
            finally:
                _current_context.reset(token)
                server.db = original_db
                server.hybrid_search = original_hs

    @pytest.mark.asyncio
    async def test_search_empty_results(self, mock_ctx, forecast_context):
        """Should return empty list when no articles match."""
        from src.api.mcp_forecasting_server import temporal_search_articles, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(temporal_search_articles)

        token = _current_context.set(forecast_context)
        original_db = server.db
        server.db = Mock()
        server.db.db_path = "test.db"
        original_hs = server.hybrid_search
        server.hybrid_search = Mock()

        with patch(
            "src.api.mcp_forecasting_server.ArticleOperationsService"
        ) as MockArticleOps:
            mock_ops_instance = AsyncMock()
            mock_ops_instance.search_articles = AsyncMock(return_value=[])
            MockArticleOps.return_value = mock_ops_instance

            try:
                result = await fn(mock_ctx, "nonexistent topic")
                data = _to_data(result)
                assert data["count"] == 0
                assert data["articles"] == []
            finally:
                _current_context.reset(token)
                server.db = original_db
                server.hybrid_search = original_hs


# ---------------------------------------------------------------------------
# submit_forecast tool tests
# ---------------------------------------------------------------------------


class TestSubmitForecastTool:
    """Tests for submit_forecast MCP tool."""

    def test_submit_valid_binary_forecast(
        self, mock_ctx, forecast_context, test_question
    ):
        """Should submit and confirm a valid binary forecast."""
        from src.api.mcp_forecasting_server import submit_forecast, _current_context
        import src.api.mcp_forecasting_server as server
        from src.domain.models import Forecast

        fn = _get_tool_fn(submit_forecast)

        token = _current_context.set(forecast_context)

        original_cs = server.context_service
        original_fs = server.forecast_service
        original_db = server.db

        mock_cs = Mock()
        mock_cs.get_question_for_context.return_value = test_question

        mock_forecast = Mock(spec=Forecast)
        mock_forecast.id = "forecast_001"
        mock_forecast.timestamp = datetime(2024, 4, 1, 12, 0, tzinfo=timezone.utc)

        mock_fs = Mock()
        mock_fs.validate_prediction.return_value = (True, 0.75, None)
        mock_fs.create_forecast.return_value = mock_forecast
        mock_fs.link_forecast_graph.return_value = {"events": 2, "hypotheses": 1}

        mock_db = Mock()

        server.context_service = mock_cs
        server.forecast_service = mock_fs
        server.db = mock_db

        try:
            result = fn(
                mock_ctx,
                prediction="0.75",
                confidence=0.8,
                reasoning="Analysis of economic indicators suggests...",
                articles_accessed=["art_001", "art_002"],
            )
            data = _to_data(result)

            assert data["forecast_id"] == "forecast_001"
            assert data["prediction"] == 0.75
            assert data["confidence"] == 0.8
            assert data["status"] == "submitted"
            assert data["graph_links"]["events"] == 2
        finally:
            _current_context.reset(token)
            server.context_service = original_cs
            server.forecast_service = original_fs
            server.db = original_db

    def test_submit_invalid_prediction(
        self, mock_ctx, forecast_context, test_question
    ):
        """Should return error for invalid prediction value."""
        from src.api.mcp_forecasting_server import submit_forecast, _current_context
        import src.api.mcp_forecasting_server as server

        fn = _get_tool_fn(submit_forecast)

        token = _current_context.set(forecast_context)

        original_cs = server.context_service
        original_fs = server.forecast_service
        original_db = server.db

        mock_cs = Mock()
        mock_cs.get_question_for_context.return_value = test_question

        mock_fs = Mock()
        mock_fs.validate_prediction.return_value = (
            False,
            None,
            "Prediction must be between 0 and 1",
        )

        server.context_service = mock_cs
        server.forecast_service = mock_fs
        server.db = Mock()

        try:
            result = fn(
                mock_ctx,
                prediction="1.5",
                confidence=0.8,
                reasoning="Bad prediction",
                articles_accessed=[],
            )
            data = _to_data(result)
            assert "error" in data
            assert "between 0 and 1" in data["error"]
        finally:
            _current_context.reset(token)
            server.context_service = original_cs
            server.forecast_service = original_fs
            server.db = original_db


# ---------------------------------------------------------------------------
# _get_hybrid_search tests
# ---------------------------------------------------------------------------


class TestGetHybridSearch:
    """Tests for _get_hybrid_search helper."""

    def test_returns_global_when_no_path(self):
        """Should return global hybrid_search when no db_path specified."""
        from src.api.mcp_forecasting_server import _get_hybrid_search
        import src.api.mcp_forecasting_server as server

        mock_hs = Mock()
        original = server.hybrid_search
        server.hybrid_search = mock_hs

        try:
            result = _get_hybrid_search()
            assert result is mock_hs
        finally:
            server.hybrid_search = original

    def test_returns_global_when_same_path(self):
        """Should return global hybrid_search when path matches."""
        from src.api.mcp_forecasting_server import _get_hybrid_search
        import src.api.mcp_forecasting_server as server

        mock_hs = Mock()
        mock_db = Mock()
        mock_db.db_path = "worldreasoner.db"
        original_hs = server.hybrid_search
        original_db = server.db
        server.hybrid_search = mock_hs
        server.db = mock_db

        try:
            result = _get_hybrid_search("worldreasoner.db")
            assert result is mock_hs
        finally:
            server.hybrid_search = original_hs
            server.db = original_db


# ---------------------------------------------------------------------------
# Database batch() context manager tests
# ---------------------------------------------------------------------------


class TestDatabaseBatch:
    """Tests for GenericDatabase.batch() context manager."""

    def test_batch_sets_and_clears_conn(self, test_db_path):
        """Should set _batch_conn during batch and clear after."""
        from src.core.database import GenericDatabase

        db = GenericDatabase(test_db_path)

        assert db._batch_conn is None
        with db.batch():
            assert db._batch_conn is not None
        assert db._batch_conn is None

    def test_batch_commits_on_success(self, test_db_path):
        """Should commit all operations when batch exits normally."""
        from src.core.database import GenericDatabase
        from src.domain.models import Article

        db = GenericDatabase(test_db_path)
        db.create_table(Article)

        art1 = Article(
            id="batch_1",
            title="Batch Test 1",
            content=LONG_CONTENT,
            url="https://example.com/1",
            source="test",
            domain=Domain.GENERAL,
            published_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            word_count=10,
        )
        art2 = Article(
            id="batch_2",
            title="Batch Test 2",
            content=LONG_CONTENT,
            url="https://example.com/2",
            source="test",
            domain=Domain.GENERAL,
            published_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            word_count=10,
        )

        with db.batch():
            db.save(Article, art1)
            db.save(Article, art2)

        # Both should be persisted
        result1 = db.get(Article, "batch_1")
        result2 = db.get(Article, "batch_2")
        assert result1 is not None
        assert result2 is not None
        assert result1.title == "Batch Test 1"
        assert result2.title == "Batch Test 2"

    def test_batch_rollback_on_error(self, test_db_path):
        """Should rollback all operations when an error occurs in batch."""
        from src.core.database import GenericDatabase
        from src.domain.models import Article

        db = GenericDatabase(test_db_path)
        db.create_table(Article)

        art = Article(
            id="rollback_test",
            title="Rollback Test",
            content=LONG_CONTENT,
            url="https://example.com/rollback",
            source="test",
            domain=Domain.GENERAL,
            published_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            word_count=10,
        )

        with pytest.raises(RuntimeError):
            with db.batch():
                db.save(Article, art)
                raise RuntimeError("Simulated error")

        # Should NOT be persisted due to rollback
        result = db.get(Article, "rollback_test")
        assert result is None

    def test_batch_cleans_up_on_error(self, test_db_path):
        """Should clean up _batch_conn even on error."""
        from src.core.database import GenericDatabase

        db = GenericDatabase(test_db_path)

        with pytest.raises(RuntimeError):
            with db.batch():
                assert db._batch_conn is not None
                raise RuntimeError("Simulated error")

        assert db._batch_conn is None

    def test_timeout_parameter(self, test_db_path):
        """Should use custom timeout for connections."""
        from src.core.database import GenericDatabase

        db = GenericDatabase(test_db_path, timeout=5.0)
        assert db._timeout == 5.0

    def test_default_timeout(self, test_db_path):
        """Should default to 30.0 seconds timeout."""
        from src.core.database import GenericDatabase

        db = GenericDatabase(test_db_path)
        assert db._timeout == 30.0
