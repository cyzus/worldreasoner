"""Test that auto-collection handles None resolution_date gracefully."""

import pytest
from unittest.mock import Mock
from src.tools.collectors.web_search import WebSearchTool


def test_auto_collect_with_none_resolution_date():
    """Test that auto-collection is skipped when resolution_date is None."""

    sample_results = [
        {
            "title": "Test Article",
            "url": "https://example.com/article",
            "content": "Test content",
            "engines": ["test"],
            "publishedDate": "2026-01-06T19:35:15",
        }
    ]

    mock_collector_instance = Mock()

    # Create tool without db_path, so question_resolution_date will be None
    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id=None,
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    # Manually enable auto-collect but leave resolution_date as None (simulating the bug)
    tool.auto_collect_enabled = True
    tool.article_collector = mock_collector_instance
    # tool.question_resolution_date is None at this point

    # Run auto-collection
    summary = tool._auto_collect_articles(sample_results)

    print("\n" + "=" * 60)
    print("Auto-collection summary (None resolution date):")
    print(summary)
    print("=" * 60)

    # Should gracefully handle None and not collect anything
    assert "no resolution date" in summary.lower()
    assert mock_collector_instance.forward.call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
