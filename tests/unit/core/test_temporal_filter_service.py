"""Unit tests for TemporalFilterService."""

from datetime import datetime, timedelta, timezone

from src.services.temporal_filter_service import TemporalFilterService
from src.domain.models import Article, Event
from src.domain.models.event import EventType
from src.utils.enums import Domain


# Helper to build valid Article instances for tests
_LONG_CONTENT = "x" * 120  # Satisfy min_length=100 constraint
_LONG_DESC = "Test event description that is long enough"  # Satisfy min_length=20


def _article(id: str, published_date, **kwargs):
    """Create a test Article with valid defaults for required fields."""
    defaults = {
        "id": id,
        "title": f"Test Article {id} Title",
        "url": f"http://example.com/{id}",
        "content": _LONG_CONTENT,
        "source": "test-source",
        "domain": Domain.GENERAL,
        "published_date": published_date,
    }
    defaults.update(kwargs)
    return Article(**defaults)


def _event(id: str, occurred_date, **kwargs):
    """Create a test Event with valid defaults for required fields."""
    defaults = {
        "id": id,
        "title": f"Test Event {id}",
        "description": _LONG_DESC,
        "event_type": EventType.INDICATOR,
        "domain": Domain.POLITICS,
        "occurred_date": occurred_date,
    }
    defaults.update(kwargs)
    return Event(**defaults)


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
            _article("a1", datetime(2024, 3, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 4, 1, tzinfo=timezone.utc)),
            _article("a3", datetime(2024, 5, 1, tzinfo=timezone.utc)),
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
            _article("a1", datetime(2024, 1, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 4, 1, tzinfo=timezone.utc)),
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
            _article("a1", datetime(2024, 4, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 6, 1, tzinfo=timezone.utc)),  # Exactly at end
            _article("a3", datetime(2024, 7, 1, tzinfo=timezone.utc)),  # After end
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
            _article("a1", datetime(2020, 1, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 4, 1, tzinfo=timezone.utc)),
        ]

        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(articles, None, window_end)

        assert len(filtered) == 2

    def test_filter_events_by_occurred_date(self):
        """Should filter events using occurred_date field."""
        events = [
            _event("e1", datetime(2024, 3, 1, tzinfo=timezone.utc)),
            _event("e2", datetime(2024, 5, 1, tzinfo=timezone.utc)),
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            events, window_start, window_end, date_field="occurred_date"
        )

        assert len(filtered) == 2

    def test_filter_items_without_dates(self):
        """Should skip items without dates."""
        # Use Events here because Event.occurred_date is Optional[datetime]
        # while Article.published_date is required.
        events = [
            _event("e1", None),
            _event("e2", datetime(2024, 4, 1, tzinfo=timezone.utc)),
        ]

        window_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        window_end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_window(
            events, window_start, window_end, date_field="occurred_date"
        )

        assert len(filtered) == 1
        assert filtered[0].id == "e2"


class TestFilterByCutoff:
    """Tests for filter_by_cutoff method."""

    def test_filter_articles_before_cutoff(self):
        """Should include articles before cutoff."""
        articles = [
            _article("a1", datetime(2024, 3, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 4, 1, tzinfo=timezone.utc)),
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(articles, cutoff_date)

        assert len(filtered) == 2

    def test_filter_articles_at_or_after_cutoff(self):
        """Should exclude articles at or after cutoff (strictly before)."""
        articles = [
            _article("a1", datetime(2024, 4, 1, tzinfo=timezone.utc)),
            _article("a2", datetime(2024, 5, 1, tzinfo=timezone.utc)),  # Exactly at cutoff
            _article("a3", datetime(2024, 6, 1, tzinfo=timezone.utc)),  # After cutoff
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(articles, cutoff_date)

        assert len(filtered) == 1
        assert filtered[0].id == "a1"

    def test_filter_events_by_cutoff(self):
        """Should filter events using occurred_date field."""
        events = [
            _event("e1", datetime(2024, 3, 1, tzinfo=timezone.utc)),
            _event("e2", datetime(2024, 6, 1, tzinfo=timezone.utc)),
        ]

        cutoff_date = datetime(2024, 5, 1, tzinfo=timezone.utc)

        filtered = TemporalFilterService.filter_by_cutoff(
            events, cutoff_date, date_field="occurred_date"
        )

        assert len(filtered) == 1
        assert filtered[0].id == "e1"
