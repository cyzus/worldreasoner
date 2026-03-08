"""Test timezone-aware vs timezone-naive datetime comparison."""

import pytest
from datetime import datetime
from unittest.mock import Mock
from src.tools.collectors.web_search import WebSearchTool


def test_auto_collect_with_timezone_mismatch():
    """Test that auto-collection handles timezone-aware vs naive datetime comparison."""

    # Yahoo news articles have timezone-aware dates like "2026-01-08T07:44:00.957837"
    sample_results = [
        {
            "title": "Test Article with timezone",
            "url": "https://www.yahoo.com/news/test-article.html",
            "content": "Test content",
            "engines": ["yahoo news"],
            "publishedDate": "2025-12-31T15:49:00+00:00",  # Timezone-aware (UTC)
        }
    ]

    mock_collector_instance = Mock()

    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id=None,
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    # Set up with timezone-NAIVE resolution date (typical from database)
    tool.auto_collect_enabled = True
    tool.question_resolution_date = datetime(2026, 1, 1)  # Naive datetime
    tool.article_collector = mock_collector_instance

    # Run auto-collection - should NOT raise TypeError
    summary = tool._auto_collect_articles(sample_results)

    print("\n" + "=" * 60)
    print("Auto-collection summary (timezone mismatch handled):")
    print(summary)
    print("=" * 60)

    # Should successfully collect the article (date is before resolution)
    assert mock_collector_instance.forward.call_count == 1
    assert "1 article" in summary.lower()


def test_auto_collect_timezone_aware_after_resolution():
    """Test that timezone-aware dates after resolution are correctly filtered."""

    sample_results = [
        {
            "title": "Future Article",
            "url": "https://www.yahoo.com/news/future.html",
            "content": "Future content",
            "engines": ["yahoo news"],
            "publishedDate": "2026-06-01T00:00:00+00:00",  # After resolution
        }
    ]

    mock_collector_instance = Mock()

    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id=None,
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    tool.auto_collect_enabled = True
    tool.question_resolution_date = datetime(2026, 1, 1)  # Naive
    tool.article_collector = mock_collector_instance

    summary = tool._auto_collect_articles(sample_results)

    print("\n" + "=" * 60)
    print("Auto-collection summary (future with timezone):")
    print(summary)
    print("=" * 60)

    # Should be skipped as after_resolution
    assert mock_collector_instance.forward.call_count == 0
    assert "after resolution" in summary.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
