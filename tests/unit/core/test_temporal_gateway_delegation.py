"""Test that TemporalGateway delegates to TemporalFilterService correctly."""

import pytest
from datetime import datetime, timedelta, timezone

from src.core.temporal_gateway import TemporalGateway
from src.services.temporal_filter_service import TemporalFilterService
from src.domain.models import Article, Event
from src.domain.models.domain import Domain
from src.domain.models.event import EventType


@pytest.fixture
def cutoff_date():
    """Fixed cutoff date for testing."""
    return datetime(2024, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def sample_articles():
    """Sample articles with various published dates."""
    return [
        Article(
            id="a1",
            title="Article published before cutoff date number one",
            url="http://example.com/1",
            published_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
            content="This is test article content that must be at least 100 characters long to satisfy pydantic validation. Additional text added.",
            source="Test Source",
            domain=Domain.GENERAL,
        ),
        Article(
            id="a2",
            title="Article published before cutoff date number two",
            url="http://example.com/2",
            published_date=datetime(2024, 5, 15, tzinfo=timezone.utc),
            content="This is test article content that must be at least 100 characters long to satisfy pydantic validation. Additional text added.",
            source="Test Source",
            domain=Domain.GENERAL,
        ),
        Article(
            id="a3",
            title="Article published after the cutoff date",
            url="http://example.com/3",
            published_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            content="This is test article content that must be at least 100 characters long to satisfy pydantic validation. Additional text added.",
            source="Test Source",
            domain=Domain.GENERAL,
        ),
        Article(
            id="a4",
            title="Article published exactly at cutoff date",
            url="http://example.com/4",
            published_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            content="This is test article content that must be at least 100 characters long to satisfy pydantic validation. Additional text added.",
            source="Test Source",
            domain=Domain.GENERAL,
        ),
    ]


@pytest.fixture
def sample_events():
    """Sample events with various occurred dates."""
    return [
        Event(
            id="e1",
            title="Event One",
            description="Event that occurred before the cutoff date",
            occurred_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
            event_type=EventType.MILESTONE,
            domain=Domain.GENERAL,
        ),
        Event(
            id="e2",
            title="Event Two",
            description="Another event before cutoff",
            occurred_date=datetime(2024, 5, 15, tzinfo=timezone.utc),
            event_type=EventType.MILESTONE,
            domain=Domain.GENERAL,
        ),
        Event(
            id="e3",
            title="Event Three",
            description="Event that occurred after cutoff",
            occurred_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            event_type=EventType.MILESTONE,
            domain=Domain.GENERAL,
        ),
        Event(
            id="e4",
            title="Event Four",
            description="Event at exactly the cutoff date",
            occurred_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            event_type=EventType.MILESTONE,
            domain=Domain.GENERAL,
        ),
        Event(
            id="e5",
            title="Event Five",
            description="Event with no occurred date",
            occurred_date=None,
            event_type=EventType.OUTCOME,
            domain=Domain.GENERAL,
        ),
    ]


def test_filter_articles_delegates_to_service(cutoff_date, sample_articles):
    """Verify filter_articles() uses TemporalFilterService."""
    gateway = TemporalGateway(cutoff_date)

    # Filter using gateway
    gateway_result = gateway.filter_articles(sample_articles)

    # Filter using service directly
    service_result = TemporalFilterService.filter_by_cutoff(
        sample_articles, cutoff_date, date_field="published_date"
    )

    # Results should be identical
    assert len(gateway_result) == len(service_result)
    assert set(a.id for a in gateway_result) == set(a.id for a in service_result)

    # Should only include articles before cutoff (strictly before)
    assert len(gateway_result) == 2
    assert all(a.published_date < cutoff_date for a in gateway_result)
    assert "a1" in [a.id for a in gateway_result]
    assert "a2" in [a.id for a in gateway_result]


def test_filter_events_delegates_to_service(cutoff_date, sample_events):
    """Verify filter_events() uses TemporalFilterService."""
    gateway = TemporalGateway(cutoff_date)

    # Filter using gateway
    gateway_result = gateway.filter_events(sample_events)

    # Filter using service directly
    service_result = TemporalFilterService.filter_by_cutoff(
        sample_events, cutoff_date, date_field="occurred_date"
    )

    # Results should be identical
    assert len(gateway_result) == len(service_result)
    assert set(e.id for e in gateway_result) == set(e.id for e in service_result)

    # Should only include events before cutoff (strictly before)
    assert len(gateway_result) == 2
    assert all(e.occurred_date < cutoff_date for e in gateway_result)
    assert "e1" in [e.id for e in gateway_result]
    assert "e2" in [e.id for e in gateway_result]


def test_is_article_accessible_consistent(cutoff_date, sample_articles):
    """Verify is_article_accessible() matches filtering behavior."""
    gateway = TemporalGateway(cutoff_date)

    # Test each article individually
    for article in sample_articles:
        is_accessible = gateway.is_article_accessible(article)

        # Single article check should match filter result
        filter_result = TemporalFilterService.filter_by_cutoff(
            [article], cutoff_date, date_field="published_date"
        )

        assert is_accessible == (len(filter_result) > 0)


def test_is_event_accessible_consistent(cutoff_date, sample_events):
    """Verify is_event_accessible() matches filtering behavior."""
    gateway = TemporalGateway(cutoff_date)

    # Test each event individually
    for event in sample_events:
        is_accessible = gateway.is_event_accessible(event)

        # Events with None date should not be accessible
        if event.occurred_date is None:
            assert not is_accessible
        else:
            # Single event check should match filter result
            filter_result = TemporalFilterService.filter_by_cutoff(
                [event], cutoff_date, date_field="occurred_date"
            )

            assert is_accessible == (len(filter_result) > 0)


def test_filter_articles_empty_list(cutoff_date):
    """Verify empty list handling."""
    gateway = TemporalGateway(cutoff_date)

    result = gateway.filter_articles([])

    assert result == []


def test_filter_events_empty_list(cutoff_date):
    """Verify empty list handling."""
    gateway = TemporalGateway(cutoff_date)

    result = gateway.filter_events([])

    assert result == []


def test_boundary_conditions(cutoff_date, sample_articles, sample_events):
    """Verify strict 'before' behavior at boundary (items at cutoff excluded)."""
    gateway = TemporalGateway(cutoff_date)

    # Article at exactly cutoff should be excluded
    article_at_cutoff = [a for a in sample_articles if a.id == "a4"][0]
    assert not gateway.is_article_accessible(article_at_cutoff)

    # Event at exactly cutoff should be excluded
    event_at_cutoff = [e for e in sample_events if e.id == "e4"][0]
    assert not gateway.is_event_accessible(event_at_cutoff)

    # Article one second before cutoff should be included
    article_before = Article(
        id="a_before",
        title="Article just before cutoff boundary",
        url="http://example.com/before",
        published_date=cutoff_date - timedelta(seconds=1),
        content="This is test article content that must be at least 100 characters long to satisfy pydantic validation. Additional text added.",
        source="Test Source",
        domain=Domain.GENERAL,
    )
    assert gateway.is_article_accessible(article_before)

    # Event one second before cutoff should be included
    event_before = Event(
        id="e_before",
        title="Event Before",
        description="Event just before cutoff",
        occurred_date=cutoff_date - timedelta(seconds=1),
        event_type=EventType.MILESTONE,
        domain=Domain.GENERAL,
    )
    assert gateway.is_event_accessible(event_before)


def test_filter_events_with_none_dates(sample_events):
    """Verify events with None dates are excluded (using fixture that has one)."""
    cutoff_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
    gateway = TemporalGateway(cutoff_date)

    # Sample events includes e5 with None occurred_date
    result = gateway.filter_events(sample_events)

    # Event e5 should be filtered out (has None date)
    event_ids = [e.id for e in result]
    assert "e5" not in event_ids

    # Only events before cutoff should remain (e1, e2)
    assert len(result) == 2
    assert "e1" in event_ids
    assert "e2" in event_ids
