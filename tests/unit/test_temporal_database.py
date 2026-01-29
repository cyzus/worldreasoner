"""Unit tests for GenericDatabase with temporal filtering."""

import pytest
from datetime import datetime, timezone, timedelta

from src.core.database import GenericDatabase
from src.core.temporal_gateway import TemporalContext
from src.domain.models import Article, Event, EventType, EventStatus


class TestGenericDatabaseTemporalFiltering:
    """Test GenericDatabase automatic temporal filtering."""

    @pytest.fixture
    def test_db_path(self, tmp_path):
        """Create temporary database for testing."""
        db_path = tmp_path / "test_temporal.db"
        db = GenericDatabase(str(db_path))
        db.create_table(Article)
        db.create_table(Event)
        return str(db_path)

    @pytest.fixture
    def cutoff_date(self):
        """Cutoff date: Nov 4, 2024."""
        return datetime(2024, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def populated_db(self, test_db_path, cutoff_date):
        """Database with test data."""
        db = GenericDatabase(test_db_path)

        # Create articles before and after cutoff
        articles = [
            Article(
                id="art_before_1",
                title="Article Before 1",
                content="This article was published before the cutoff date. "
                * 5,  # > 100 chars
                source="Test",
                published_date=cutoff_date - timedelta(days=2),
                domain="tech",
            ),
            Article(
                id="art_before_2",
                title="Article Before 2",
                content="This article was published before the cutoff date. "
                * 5,  # > 100 chars
                source="Test",
                published_date=cutoff_date - timedelta(days=1),
                domain="politics",
            ),
            Article(
                id="art_at_cutoff",
                title="Article At Cutoff",
                content="This article was published exactly at the cutoff date. "
                * 5,  # > 100 chars
                source="Test",
                published_date=cutoff_date,
                domain="tech",
            ),
            Article(
                id="art_after_1",
                title="Article After 1",
                content="This article was published after the cutoff date. "
                * 5,  # > 100 chars
                source="Test",
                published_date=cutoff_date + timedelta(days=1),
                domain="tech",
            ),
            Article(
                id="art_after_2",
                title="Article After 2",
                content="This article was published after the cutoff date. "
                * 5,  # > 100 chars
                source="Test",
                published_date=cutoff_date + timedelta(days=2),
                domain="politics",
            ),
        ]

        for article in articles:
            db.save(Article, article)

        # Create events before and after cutoff
        events = [
            Event(
                id="evt_before",
                title="Event Before",
                description="Event occurred before cutoff.",
                event_type=EventType.OUTCOME,
                domain="tech",
                status=EventStatus.OCCURRED,
                occurred_date=cutoff_date - timedelta(days=3),
            ),
            Event(
                id="evt_after",
                title="Event After",
                description="Event occurred after cutoff.",
                event_type=EventType.OUTCOME,
                domain="tech",
                status=EventStatus.OCCURRED,
                occurred_date=cutoff_date + timedelta(days=3),
            ),
            Event(
                id="evt_none",
                title="Event No Date",
                description="Event with no occurred_date.",
                event_type=EventType.MILESTONE,
                domain="tech",
                status=EventStatus.PREDICTED,
                occurred_date=None,
            ),
        ]

        for event in events:
            db.save(Event, event)

        return test_db_path

    # Initialization tests

    def test_init_with_cutoff_date(self, test_db_path, cutoff_date):
        """Should initialize with provided cutoff date."""
        db = GenericDatabase(db_path=test_db_path, cutoff_date=cutoff_date)
        assert db.cutoff_date == cutoff_date
        assert db.gateway.cutoff_date == cutoff_date

    def test_init_with_temporal_context(self, test_db_path, cutoff_date):
        """Should use TemporalContext cutoff if no cutoff provided."""
        with TemporalContext(cutoff_date=cutoff_date):
            db = GenericDatabase(db_path=test_db_path)
            assert db.cutoff_date == cutoff_date

    def test_init_without_cutoff_no_filtering(self, test_db_path):
        """Should work without temporal filtering if no cutoff provided."""
        db = GenericDatabase(db_path=test_db_path)
        assert db.cutoff_date is None
        assert db.gateway is None

    def test_init_with_naive_datetime_raises_error(self, test_db_path):
        """Should raise error for naive datetime."""
        naive_date = datetime(2024, 11, 4, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            GenericDatabase(db_path=test_db_path, cutoff_date=naive_date)

    # Article filtering tests

    def test_get_articles_filters_by_cutoff(self, populated_db, cutoff_date):
        """Should return only articles strictly before cutoff (< not <=)."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        articles = db.get_many(Article)

        # Should get: art_before_1, art_before_2 (art_at_cutoff is excluded)
        assert len(articles) == 2
        article_ids = [a.id for a in articles]
        assert "art_before_1" in article_ids
        assert "art_before_2" in article_ids
        assert "art_at_cutoff" not in article_ids
        assert "art_after_1" not in article_ids
        assert "art_after_2" not in article_ids

    def test_get_articles_with_domain_filter(self, populated_db, cutoff_date):
        """Should apply domain filter AND temporal filter."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        articles = db.get_many(Article, filters={"domain": "tech"})

        # Should get: art_before_1 (tech domain, strictly before cutoff)
        # art_at_cutoff is excluded (not strictly before)
        assert len(articles) == 1
        article_ids = [a.id for a in articles]
        assert "art_before_1" in article_ids
        assert "art_at_cutoff" not in article_ids

    def test_get_article_by_id_before_cutoff(self, populated_db, cutoff_date):
        """Should return article if before cutoff."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        article = db.get(Article, "art_before_1")
        assert article is not None
        assert article.id == "art_before_1"

    def test_get_article_by_id_after_cutoff(self, populated_db, cutoff_date):
        """Should return None for article after cutoff."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        article = db.get(Article, "art_after_1")
        assert article is None

    # Event filtering tests

    def test_get_events_filters_by_cutoff(self, populated_db, cutoff_date):
        """Should return only events before cutoff."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        events = db.get_many(Event)

        # Should get only: evt_before (occurred before cutoff)
        assert len(events) == 1
        assert events[0].id == "evt_before"

    def test_get_event_by_id_before_cutoff(self, populated_db, cutoff_date):
        """Should return event if before cutoff."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        event = db.get(Event, "evt_before")
        assert event is not None
        assert event.id == "evt_before"

    def test_get_event_by_id_after_cutoff(self, populated_db, cutoff_date):
        """Should return None for event after cutoff."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        event = db.get(Event, "evt_after")
        assert event is None

    def test_get_event_with_none_date(self, populated_db, cutoff_date):
        """Should return None for event with None occurred_date."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        event = db.get(Event, "evt_none")
        assert event is None

    # Filter tests (replacing search tests since GenericDatabase doesn't have search)

    def test_get_articles_with_domain_tech(self, populated_db, cutoff_date):
        """Should get tech domain articles with temporal filtering."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        results = db.get_many(Article, filters={"domain": "tech"})
        assert len(results) == 1  # art_before_1 only (art_at_cutoff excluded)

        # All results should be strictly before cutoff
        for article in results:
            assert article.published_date < cutoff_date

    def test_get_events_all_accessible(self, populated_db, cutoff_date):
        """Should get only accessible events with temporal filtering."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        results = db.get_many(Event)
        # Should only find evt_before (evt_after is post-cutoff, evt_none has None date)
        assert len(results) == 1
        assert results[0].id == "evt_before"

    # Access validation tests (using get() method)

    def test_access_article_accessible(self, populated_db, cutoff_date):
        """Should return article for accessible article."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        assert db.get(Article, "art_before_1") is not None

    def test_access_article_not_accessible(self, populated_db, cutoff_date):
        """Should return None for non-accessible article."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        assert db.get(Article, "art_after_1") is None

    def test_access_nonexistent(self, populated_db, cutoff_date):
        """Should return None for nonexistent article."""
        db = GenericDatabase(db_path=populated_db, cutoff_date=cutoff_date)

        assert db.get(Article, "art_nonexistent") is None

    # Save and create operations (non-temporal)

    def test_save_with_temporal_filtering(self, test_db_path, cutoff_date):
        """Save operation should work normally but reads are filtered."""
        db = GenericDatabase(db_path=test_db_path, cutoff_date=cutoff_date)

        article = Article(
            id="art_new",
            title="New Article",
            content="New content for testing temporal filtering behavior in the database layer with sufficient length. "
            * 2,  # > 100 chars
            source="Test",
            published_date=cutoff_date + timedelta(days=10),  # Future article
            domain="tech",
        )

        # Should be able to save (no temporal restriction on writes)
        result = db.save(Article, article)
        assert result is True

        # But shouldn't be able to read it back (temporal filtering)
        retrieved = db.get(Article, "art_new")
        assert retrieved is None  # Published after cutoff

    def test_create_table_works_normally(self, test_db_path, cutoff_date):
        """Create table should work normally."""
        db = GenericDatabase(db_path=test_db_path, cutoff_date=cutoff_date)

        # Should be able to create table
        db.create_table(Article)
        # No exception means success
