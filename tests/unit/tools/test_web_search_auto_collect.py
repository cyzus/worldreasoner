"""Test auto-collection feature in WebSearchTool."""

import logging
import pytest
from datetime import datetime
from unittest.mock import Mock
from src.tools.collectors.web_search import WebSearchTool


@pytest.fixture
def mock_db():
    """Mock database for testing."""
    return Mock()


@pytest.fixture
def mock_question():
    """Mock question with resolution date."""
    question = Mock()
    question.id = "test_question_123"
    question.resolution_date = datetime(2026, 1, 1)  # Future date
    return question


@pytest.fixture
def sample_search_results():
    """Real-world sample search results matching the user's output."""
    return [
        {
            "title": "Wildfires, floods and extreme heat: These are the biggest weather stories of 2025",
            "url": "https://www.msn.com/en-us/weather/topstories/these-are-the-biggest-weather-stories-of-2025/ar-AA1Tm5zH",
            "content": "Devastating wildfire, flooding and extreme heat events took place over the past year, several resulting in mass fatalities.",
            "engines": ["startpage news", "bing news"],
            "publishedDate": "2025-12-31T15:49:00",  # Has date
        },
        {
            "title": "Five Things to Know About Climate Change in 2025",
            "url": "https://www.climatecentral.org/climate-matters/five-things-to-know-about-climate-change-in-2025",
            "content": "In 2025, carbon pollution made 89% of record high daily temperatures set across 247 major U.S. cities more likely",
            "engines": ["bing news"],
            "publishedDate": None,  # No date
        },
        {
            "title": "Oceans are supercharging hurricanes past Category 5 | ScienceDaily",
            "url": "https://sciencedaily.com/releases/2025/12/251225080725.htm",
            "content": "Deep ocean hot spots packed with heat are making the strongest hurricanes and typhoons more likely",
            "engines": ["brave.news"],
            "publishedDate": None,  # No date
        },
        {
            "title": "2025 was so hot it pushed Earth past critical climate change mark",
            "url": "https://www.cbsnews.com/news/climate-change-2025-critical-mark-eclipsed/",
            "content": "2025 was the third hottest year on record and pushed Earth past a critical climate change mark",
            "engines": ["brave.news"],
            "publishedDate": None,  # No date
        },
    ]


def test_auto_collect_with_missing_dates(
    mock_db, mock_question, sample_search_results, caplog
):
    """Test that articles without publishedDate are properly skipped."""
    caplog.set_level(logging.DEBUG)

    mock_db.get.return_value = mock_question
    mock_collector_instance = Mock()

    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id="test_question_123",
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    tool.db = mock_db
    tool.question_id = mock_question.id
    tool.question = mock_question
    tool.auto_collect_enabled = True
    tool.question_resolution_date = mock_question.resolution_date
    tool.article_collector = mock_collector_instance

    summary = tool._auto_collect_articles(sample_search_results)

    print("\n" + "=" * 60)
    print("Auto-collection summary:")
    print(summary)
    print("=" * 60)

    if caplog.text:
        print("\nCaptured logs:")
        print(caplog.text)

    assert "skipped" in summary.lower()
    assert "no date" in summary.lower()
    assert mock_collector_instance.forward.call_count == 1

    call_args = mock_collector_instance.forward.call_args
    assert call_args.kwargs["url"] == sample_search_results[0]["url"]
    assert call_args.kwargs["title"] == sample_search_results[0]["title"]


def test_auto_collect_with_invalid_date_format(mock_db, mock_question, caplog):
    """Test error handling when publishedDate has an invalid format."""
    caplog.set_level(logging.DEBUG)

    results_with_bad_date = [
        {
            "title": "Test Article",
            "url": "https://example.com/article",
            "content": "Test content",
            "engines": ["test"],
            "publishedDate": "invalid-date-format",
        }
    ]

    mock_db.get.return_value = mock_question
    mock_collector_instance = Mock()

    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id="test_question_123",
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    tool.db = mock_db
    tool.question_id = mock_question.id
    tool.question = mock_question
    tool.auto_collect_enabled = True
    tool.question_resolution_date = mock_question.resolution_date
    tool.article_collector = mock_collector_instance

    summary = tool._auto_collect_articles(results_with_bad_date)

    print("\n" + "=" * 60)
    print("Auto-collection summary (bad date):")
    print(summary)
    print("=" * 60)

    # Invalid dates fall back to current time (datetime.now(timezone.utc))
    # which is after the resolution date (2026-01-01), so skipped as "after_resolution"
    assert "after resolution" in summary.lower()
    assert mock_collector_instance.forward.call_count == 0


def test_auto_collect_with_date_after_resolution(mock_db, mock_question, caplog):
    """Test that articles published after resolution date are skipped."""
    caplog.set_level(logging.DEBUG)

    results_future = [
        {
            "title": "Future Article",
            "url": "https://example.com/future",
            "content": "Future content",
            "engines": ["test"],
            "publishedDate": "2026-06-01T00:00:00",  # After resolution date (2026-01-01)
        }
    ]

    mock_db.get.return_value = mock_question
    mock_collector_instance = Mock()

    tool = WebSearchTool(
        db_path=None,
        collector=None,
        question_id="test_question_123",
        auto_collect_enabled=False,
        max_auto_collect=5,
        domain="general",
    )

    tool.db = mock_db
    tool.question_id = mock_question.id
    tool.question = mock_question
    tool.auto_collect_enabled = True
    tool.question_resolution_date = mock_question.resolution_date
    tool.article_collector = mock_collector_instance

    summary = tool._auto_collect_articles(results_future)

    print("\n" + "=" * 60)
    print("Auto-collection summary (future date):")
    print(summary)
    print("=" * 60)

    assert "after resolution" in summary.lower()
    assert mock_collector_instance.forward.call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
