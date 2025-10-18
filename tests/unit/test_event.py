"""Unit tests for Event data model."""

from datetime import datetime, timezone, timedelta
import pytest

from src.data.models.event import (
    Event,
    EventType,
    EventStatus,
    CausalLink,
    CausalRelationType
)


def test_event_creation():
    """Test basic event creation."""
    event = Event(
        id="evt_test_001",
        title="Test Event",
        description="This is a test event for unit testing",
        event_type=EventType.OUTCOME,
        domain="politics"
    )
    
    assert event.id == "evt_test_001"
    assert event.status == EventStatus.PREDICTED
    assert event.is_synthetic is False
    assert len(event.causes) == 0
    assert len(event.article_ids) == 0


def test_event_validation():
    """Test event field validation."""
    # Title too short
    with pytest.raises(ValueError):
        Event(
            id="evt_test_002",
            title="Test",
            description="This is a test event",
            event_type=EventType.OUTCOME,
            domain="politics"
        )
    
    # Description too short
    with pytest.raises(ValueError):
        Event(
            id="evt_test_003",
            title="Valid Title",
            description="Short",
            event_type=EventType.OUTCOME,
            domain="politics"
        )


def test_causal_link_creation():
    """Test creating causal links between events."""
    cause_event = Event(
        id="evt_cause_001",
        title="Cause Event",
        description="This event causes another event",
        event_type=EventType.DECISION,
        domain="politics"
    )
    
    target_event_id = "evt_effect_001"
    
    # Add causal link
    cause_event.add_causal_link(
        target_event_id=target_event_id,
        relation_type=CausalRelationType.CAUSES,
        strength=0.8,
        confidence=0.9,
        reasoning="Policy decisions typically lead to market reactions",
        evidence_article_ids=["art_001", "art_002"]
    )
    
    assert len(cause_event.causes) == 1
    link = cause_event.causes[0]
    assert link.source_event_id == "evt_cause_001"
    assert link.target_event_id == target_event_id
    assert link.relation_type == CausalRelationType.CAUSES
    assert link.strength == 0.8
    assert link.confidence == 0.9
    assert len(link.evidence_article_ids) == 2


def test_causal_link_types():
    """Test different types of causal relationships."""
    event = Event(
        id="evt_test_004",
        title="Test Event",
        description="Testing different causal link types",
        event_type=EventType.DECISION,
        domain="politics"
    )
    
    # Test all relation types
    event.add_causal_link("evt_target_1", relation_type=CausalRelationType.CAUSES)
    event.add_causal_link("evt_target_2", relation_type=CausalRelationType.ENABLES)
    event.add_causal_link("evt_target_3", relation_type=CausalRelationType.PREVENTS)
    event.add_causal_link("evt_target_4", relation_type=CausalRelationType.CORRELATES)
    event.add_causal_link("evt_target_5", relation_type=CausalRelationType.CONDITIONAL)
    
    assert len(event.causes) == 5
    assert event.causes[0].relation_type == CausalRelationType.CAUSES
    assert event.causes[1].relation_type == CausalRelationType.ENABLES
    assert event.causes[2].relation_type == CausalRelationType.PREVENTS


def test_mark_occurred():
    """Test marking event as occurred."""
    event = Event(
        id="evt_test_005",
        title="Future Event",
        description="This event hasn't occurred yet",
        event_type=EventType.OUTCOME,
        domain="politics",
        predicted_date=datetime.now(timezone.utc) + timedelta(days=30)
    )
    
    assert event.status == EventStatus.PREDICTED
    assert event.occurred_date is None
    assert event.outcome_verified is False
    
    # Mark as occurred
    occurred_time = datetime.now(timezone.utc)
    event.mark_occurred(
        occurred_date=occurred_time,
        outcome_value="Candidate A wins"
    )
    
    assert event.status == EventStatus.OCCURRED
    assert event.occurred_date == occurred_time
    assert event.outcome_value == "Candidate A wins"
    assert event.outcome_verified is True
    assert event.resolution_date is not None


def test_get_causal_descendants():
    """Test retrieving events caused by this event."""
    event = Event(
        id="evt_parent_001",
        title="Parent Event",
        description="This event causes multiple other events",
        event_type=EventType.DECISION,
        domain="finance"
    )
    
    # Add multiple causal links
    event.add_causal_link("evt_child_001", strength=0.7)
    event.add_causal_link("evt_child_002", strength=0.5)
    event.add_causal_link("evt_child_003", strength=0.9)
    
    descendants = event.get_causal_descendants()
    assert len(descendants) == 3
    assert "evt_child_001" in descendants
    assert "evt_child_002" in descendants
    assert "evt_child_003" in descendants


def test_get_evidence_articles():
    """Test retrieving all articles documenting event and causal links."""
    event = Event(
        id="evt_test_006",
        title="Test Event",
        description="Event with article documentation",
        event_type=EventType.OUTCOME,
        domain="politics",
        article_ids=["art_001", "art_002"]
    )
    
    # Add causal links with evidence articles
    event.add_causal_link(
        "evt_target_001",
        evidence_article_ids=["art_003", "art_004"]
    )
    event.add_causal_link(
        "evt_target_002",
        evidence_article_ids=["art_002", "art_005"]  # art_002 is duplicate
    )
    
    evidence = event.get_evidence_articles()
    
    # Should deduplicate article IDs
    assert len(evidence) == 5
    assert "art_001" in evidence
    assert "art_002" in evidence
    assert "art_003" in evidence
    assert "art_004" in evidence
    assert "art_005" in evidence


def test_event_serialization():
    """Test JSON serialization/deserialization."""
    event = Event(
        id="evt_test_007",
        title="Serialization Test Event",
        description="Testing JSON serialization capabilities",
        event_type=EventType.OUTCOME,
        domain="technology",
        tags=["ai", "product-launch"],
        predicted_date=datetime(2024, 12, 1, 10, 0, 0),
        importance=0.8,
        entities={
            "company": "TechCorp",
            "product": "AI Assistant"
        }
    )
    
    event.add_causal_link(
        "evt_market_001",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7
    )
    
    # Serialize to dict
    event_dict = event.model_dump()
    assert event_dict["id"] == "evt_test_007"
    assert event_dict["event_type"] == "outcome"
    assert len(event_dict["causes"]) == 1
    
    # Deserialize from dict
    event_restored = Event(**event_dict)
    assert event_restored.id == event.id
    assert event_restored.title == event.title
    assert len(event_restored.causes) == 1


def test_event_types():
    """Test all event type classifications."""
    types = [
        EventType.DECISION,
        EventType.OUTCOME,
        EventType.INDICATOR,
        EventType.MILESTONE,
        EventType.EXTERNAL_SHOCK
    ]
    
    for event_type in types:
        event = Event(
            id=f"evt_{event_type.value}_001",
            title=f"Test {event_type.value}",
            description=f"Testing event type: {event_type.value}",
            event_type=event_type,
            domain="politics"
        )
        assert event.event_type == event_type


def test_event_status_transitions():
    """Test event status lifecycle."""
    event = Event(
        id="evt_test_008",
        title="Status Transition Test",
        description="Testing event status transitions",
        event_type=EventType.OUTCOME,
        domain="politics"
    )
    
    # Start as predicted
    assert event.status == EventStatus.PREDICTED
    
    # Mark as occurred
    event.mark_occurred(
        occurred_date=datetime.now(timezone.utc),
        outcome_value="Result confirmed"
    )
    assert event.status == EventStatus.OCCURRED
    
    # Can manually set other statuses
    event.status = EventStatus.CANCELLED
    assert event.status == EventStatus.CANCELLED
    
    event.status = EventStatus.UNCERTAIN
    assert event.status == EventStatus.UNCERTAIN


def test_complex_causal_graph():
    """Test building a complex causal graph."""
    # Create a chain of events
    events = []
    for i in range(5):
        event = Event(
            id=f"evt_chain_{i}",
            title=f"Event {i} in Chain",
            description=f"Event number {i} in a causal chain",
            event_type=EventType.OUTCOME,
            domain="finance"
        )
        events.append(event)
    
    # Create causal chain: 0 -> 1 -> 2 -> 3 -> 4
    for i in range(4):
        events[i].add_causal_link(
            target_event_id=events[i + 1].id,
            strength=0.8 - (i * 0.1),  # Decreasing strength
            confidence=0.9
        )
    
    # Verify chain structure
    assert len(events[0].causes) == 1
    assert len(events[3].causes) == 1
    assert len(events[4].causes) == 0  # Terminal node
    
    # Verify descendants
    assert events[0].get_causal_descendants() == ["evt_chain_1"]
    assert events[2].get_causal_descendants() == ["evt_chain_3"]


def test_compute_importance():
    """Test computed importance from graph structure."""
    # Create event with no connections (low importance)
    isolated_event = Event(
        id="evt_isolated",
        title="Isolated Event",
        description="Event with no causal connections",
        event_type=EventType.INDICATOR,
        domain="politics"
    )
    assert isolated_event.compute_importance() == 0.0
    
    # Create event with causal effects and articles (higher importance)
    important_event = Event(
        id="evt_important",
        title="Important Event",
        description="Event with many causal effects and media coverage",
        event_type=EventType.OUTCOME,
        domain="politics",
        article_ids=["art1", "art2", "art3", "art4", "art5"]
    )
    
    # Add multiple strong causal links
    important_event.add_causal_link("evt_target1", strength=0.9, confidence=0.95)
    important_event.add_causal_link("evt_target2", strength=0.8, confidence=0.9)
    important_event.add_causal_link("evt_target3", strength=0.7, confidence=0.85)
    
    # Add incoming causal links
    important_event.caused_by_ids = ["evt_cause1", "evt_cause2"]
    
    importance = important_event.compute_importance()
    
    # Should have high importance due to:
    # - 3 outgoing causal links (with high strength)
    # - 5 articles
    # - 2 incoming causal links
    assert importance > 0.5
    assert importance <= 1.0
    
    # Test with weak causal links
    weak_event = Event(
        id="evt_weak",
        title="Weakly Connected Event",
        description="Event with weak causal effects",
        event_type=EventType.INDICATOR,
        domain="finance",
        article_ids=["art1"]
    )
    weak_event.add_causal_link("evt_target", strength=0.2, confidence=0.5)
    
    weak_importance = weak_event.compute_importance()
    assert weak_importance < importance  # Should be less than important event
