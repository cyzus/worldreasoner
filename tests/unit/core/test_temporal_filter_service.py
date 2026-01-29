"""Unit tests for TemporalFilterService."""

from datetime import datetime, timedelta, timezone

from src.core.temporal_filter_service import TemporalFilterService
from src.domain.models import Article, Event
from src.utils.enums import Domain


class TestGetEvidenceWindow:
    """Tests for get_evidence_window method."""

    def test_with_estimated_start_time(self):
        """Should use estimated_start_time as window start."""
        resolution_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        estimated_start = datetime(2024, 1, 1, tzinfo=timezone.utc)

        window_start, window_end = TemporalFilterService.get_evidence_window(
            resolution_date, estimated_start
        )

        assert window_start == estimated_start
        assert window_end == resolution_date

    def test_without_estimated_start_time(self):
        """Should use fallback window when no estimated_start_time."""
        resolution_date = datetime(2024, 6, 1, tzinfo=timezone.utc)

        window_start, window_end = TemporalFilterService.get_evidence_window(
            resolution_date, fallback_window_days=365
        )

        expected_start = resolution_date - timedelta(days=365)
        assert window_start == expected_start
        assert window_end == resolution_date

    def test_custom_fallback_window(self):
        """Should respect custom fallback_window_days."""
        resolution_date = datetime(2024, 6, 1, tzinfo=timezone.utc)

        window_start, window_end = TemporalFilterService.get_evidence_window(
            resolution_date, fallback_window_days=90
        )

        expected_start = resolution_date - timedelta(days=90)
        assert window_start == expected_start

    def test_timezone_aware_dates(self):
        """Should handle timezone-aware dates correctly."""
        resolution_date = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        estimated_start = datetime(2024, 1, 1, 8, 30, 0, tzinfo=timezone.utc)

        window_start, window_end = TemporalFilterService.get_evidence_window(
            resolution_date, estimated_start
        )

        assert window_start.tzinfo is not None
        assert window_end.tzinfo is not None


class TestFilterByWindow:
    """Tests for filter_by_window method."""

    def test_filter_articles_within_window(self):
        """Should include articles within the time window."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),
            Article(
                id="a3",
                title="Article 3",
                url="http://example.com/3",
                published_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
                content="Test 3",
            ),
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            articles, window_start, window_end
        )

        assert len(filtered) == 3

    def test_filter_articles_before_window_start(self):
        """Should exclude articles before window start."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),
        ]

        window_start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            articles, window_start, window_end
        )

        assert len(filtered) == 1
        assert filtered[0].id == "a2"

    def test_filter_articles_at_or_after_window_end(self):
        """Should exclude articles at or after window end (strictly before)."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),  # Exactly at end
            Article(
                id="a3",
                title="Article 3",
                url="http://example.com/3",
                published_date=datetime(2024, 7, 1, tzinfo=timezone.utc),
                content="Test 3",
            ),  # After end
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            articles, window_start, window_end
        )

        assert len(filtered) == 1
        assert filtered[0].id == "a1"

    def test_filter_with_none_window_start(self):
        """Should allow None window_start (no lower bound)."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),
        ]

        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(articles, None, window_end)

        assert len(filtered) == 2

    def test_filter_events_by_occurred_date(self):
        """Should filter events using occurred_date field."""
        events = [
            Event(
                id="e1",
                title="Event 1",
                description="Test 1",
                occurred_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
                domain=Domain.POLITICS,
            ),
            Event(
                id="e2",
                title="Event 2",
                description="Test 2",
                occurred_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
                domain=Domain.POLITICS,
            ),
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            events, window_start, window_end, date_field="occurred_date"
        )

        assert len(filtered) == 2

    def test_filter_items_without_dates(self):
        """Should skip items without dates."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=None,
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            articles, window_start, window_end
        )

        assert len(filtered) == 1
        assert filtered[0].id == "a2"


class TestFilterByCutoff:
    """Tests for filter_by_cutoff method."""

    def test_filter_articles_before_cutoff(self):
        """Should include articles before cutoff."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(articles, cutoff_date)

        assert len(filtered) == 2

    def test_filter_articles_at_or_after_cutoff(self):
        """Should exclude articles at or after cutoff (strictly before)."""
        articles = [
            Article(
                id="a1",
                title="Article 1",
                url="http://example.com/1",
                published_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
                content="Test 1",
            ),
            Article(
                id="a2",
                title="Article 2",
                url="http://example.com/2",
                published_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
                content="Test 2",
            ),  # Exactly at cutoff
            Article(
                id="a3",
                title="Article 3",
                url="http://example.com/3",
                published_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
                content="Test 3",
            ),  # After cutoff
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(articles, cutoff_date)

        assert len(filtered) == 1
        assert filtered[0].id == "a1"

    def test_filter_events_by_cutoff(self):
        """Should filter events using occurred_date field."""
        events = [
            Event(
                id="e1",
                title="Event 1",
                description="Test 1",
                occurred_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
                domain=Domain.POLITICS,
            ),
            Event(
                id="e2",
                title="Event 2",
                description="Test 2",
                occurred_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
                domain=Domain.POLITICS,
            ),
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(
            events, cutoff_date, date_field="occurred_date"
        )

        assert len(filtered) == 1
        assert filtered[0].id == "e1"
