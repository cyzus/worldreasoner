"""Unit tests for DatabaseAwareTool base class."""

import pytest
import tempfile
import os

from src.tools.base.database_mixin import DatabaseAwareTool
from src.core.database import GenericDatabase
from src.domain.models import Article
from src.domain.models.domain import Domain


class TestDatabaseInitialization:
    """Test database initialization patterns."""

    def test_init_with_db_instance(self):
        """Should use provided database instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = GenericDatabase(db_path)
            tool = DatabaseAwareTool(db=db)

            assert tool.db is db
            assert tool.db is not None

    def test_init_with_db_path(self):
        """Should create database from path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            tool = DatabaseAwareTool(db_path=db_path)

            assert tool.db is not None
            assert isinstance(tool.db, GenericDatabase)

    def test_init_with_default(self):
        """Should use default worldreasoner.db."""
        tool = DatabaseAwareTool()

        assert tool.db is not None
        assert isinstance(tool.db, GenericDatabase)

    def test_init_with_ensure_tables(self):
        """Should create tables for specified models."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = GenericDatabase(db_path)
            tool = DatabaseAwareTool(db=db, ensure_tables=[Article])

            # Table should be created
            # We can verify by trying to save an article
            article = Article(
                id="test_article",
                title="Test Article Title",
                content="This is test content that must be at least 100 characters long to satisfy validation. More text here to meet requirement.",
                source="Test Source",
                domain=Domain.GENERAL,
                published_date="2024-01-01T00:00:00Z",
            )

            # Should not raise an error
            tool.db.save(Article, article)

            # Should be able to retrieve it
            retrieved = tool.db.get(Article, "test_article")
            assert retrieved is not None
            assert retrieved.id == "test_article"


class TestNotFoundResponse:
    """Test not_found_response helper method."""

    @pytest.fixture
    def tool_with_articles(self):
        """Create tool with some test articles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = GenericDatabase(db_path)
            tool = DatabaseAwareTool(db=db, ensure_tables=[Article])

            # Add some test articles
            for i in range(5):
                article = Article(
                    id=f"article_{i}",
                    title=f"Test Article {i} with minimum length requirement",
                    content="This is test content that must be at least 100 characters long to satisfy validation. Additional text here.",
                    source="Test Source",
                    domain=Domain.GENERAL,
                    published_date="2024-01-01T00:00:00Z",
                )
                tool.db.save(Article, article)

            yield tool

    def test_not_found_response_format(self, tool_with_articles):
        """Should return properly formatted error response."""
        import json

        response_str = tool_with_articles.not_found_response(
            "Article", "nonexistent_id", Article
        )

        # Should be valid JSON
        response = json.loads(response_str)

        # Should have error message
        assert "error" in response
        assert "nonexistent_id" in response["error"]
        assert "Article" in response["error"]

        # Should have available items
        assert "available_items" in response
        assert isinstance(response["available_items"], list)

    def test_not_found_response_includes_available_ids(self, tool_with_articles):
        """Should include list of available article IDs."""
        import json

        response_str = tool_with_articles.not_found_response(
            "Article", "nonexistent_id", Article, limit=3
        )

        response = json.loads(response_str)

        # Should include available IDs (limited to 3)
        assert len(response["available_items"]) <= 3
        assert all(isinstance(id, str) for id in response["available_items"])
        assert all(id.startswith("article_") for id in response["available_items"])

    def test_not_found_response_respects_limit(self, tool_with_articles):
        """Should respect limit parameter."""
        import json

        # Request only 2 items
        response_str = tool_with_articles.not_found_response(
            "Article", "missing", Article, limit=2
        )

        response = json.loads(response_str)

        # Should have at most 2 items
        assert len(response["available_items"]) <= 2

    def test_not_found_response_empty_database(self):
        """Should handle empty database gracefully."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = GenericDatabase(db_path)
            tool = DatabaseAwareTool(db=db, ensure_tables=[Article])

            response_str = tool.not_found_response("Article", "any_id", Article)

            response = json.loads(response_str)

            # Should still return valid response
            assert "error" in response
            assert "available_items" in response
            assert response["available_items"] == []


class TestIntegrationWithTools:
    """Test DatabaseAwareTool integration with actual tools."""

    def test_can_subclass_database_aware_tool(self):
        """Should be able to create tool subclasses."""

        class MyTool(DatabaseAwareTool):
            name = "my_tool"
            description = "Test tool"
            inputs = {}
            output_type = "string"

            def __init__(self, db=None, db_path=None):
                super().__init__(db=db, db_path=db_path, ensure_tables=[Article])

            def forward(self) -> str:
                return "test"

        # Should initialize successfully
        tool = MyTool()
        assert tool.db is not None
        assert tool.forward() == "test"

    def test_multiple_tables_initialization(self):
        """Should handle multiple table initialization."""
        from src.domain.models import Event

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = GenericDatabase(db_path)
            tool = DatabaseAwareTool(db=db, ensure_tables=[Article, Event])

            # Both tables should be created
            # Verify by saving items to both
            article = Article(
                id="a1",
                title="Test Article with minimum length",
                content="Content with minimum 100 characters required for validation. Additional text to meet requirement here.",
                source="Test",
                domain=Domain.GENERAL,
                published_date="2024-01-01T00:00:00Z",
            )
            tool.db.save(Article, article)

            from src.domain.models.event import EventType

            event = Event(
                id="e1",
                title="Test Event",
                description="Test event description with minimum length requirement",
                domain=Domain.GENERAL,
                event_type=EventType.MILESTONE,
            )
            tool.db.save(Event, event)

            # Should retrieve both
            assert tool.db.get(Article, "a1") is not None
            assert tool.db.get(Event, "e1") is not None
