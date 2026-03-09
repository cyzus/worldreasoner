
import pytest
from datetime import datetime, timezone
from src.tools.reasoning.causal_reasoner import CausalReasonerTool
from src.domain.models import Event, EventStatus, EventType, Domain

@pytest.fixture
def causal_reasoner(test_db):
    return CausalReasonerTool(db_path=test_db.db_path)

def create_event(db, event_id, occurred_date=None, predicted_date=None, is_outcome=False):
    status = EventStatus.OCCURRED if occurred_date else EventStatus.PREDICTED
    event = Event(
        id=event_id,
        title=f"Event {event_id}",
        description=f"Description for {event_id}",
        event_type=EventType.OUTCOME,
        domain=Domain.POLITICS,
        status=status,
        occurred_date=occurred_date,
        predicted_date=predicted_date,
        is_outcome=is_outcome
    )
    db.save(Event, event)
    return event

def test_validate_chronology_occurred_dates(causal_reasoner, test_db):
    """Test validation with two occurred dates (standard case)."""
    date1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    date2 = datetime(2025, 1, 2, tzinfo=timezone.utc)
    
    create_event(test_db, "evt_1", occurred_date=date1)
    create_event(test_db, "evt_2", occurred_date=date2)
    
    # Valid chronology
    assert causal_reasoner._validate_chronology("evt_1", "evt_2") is True
    
    # Invalid chronology
    assert causal_reasoner._validate_chronology("evt_2", "evt_1") is False

def test_validate_chronology_predicted_outcome(causal_reasoner, test_db):
    """Test validation when target is a predicted outcome (no occurred_date)."""
    date1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    pred_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
    
    create_event(test_db, "evt_cause", occurred_date=date1)
    create_event(test_db, "evt_outcome", predicted_date=pred_date, is_outcome=True)
    
    # BEFORE FIX: This currently fails because evt_outcome.occurred_date is None
    # AFTER FIX: This should pass because we check predicted_date if occurred_date is None
    assert causal_reasoner._validate_chronology("evt_cause", "evt_outcome") is True

def test_validate_chronology_both_predicted(causal_reasoner, test_db):
    """Test validation when both events are predicted."""
    pred1 = datetime(2025, 6, 1, tzinfo=timezone.utc)
    pred2 = datetime(2025, 7, 1, tzinfo=timezone.utc)
    
    create_event(test_db, "evt_pred_1", predicted_date=pred1)
    create_event(test_db, "evt_pred_2", predicted_date=pred2)
    
    assert causal_reasoner._validate_chronology("evt_pred_1", "evt_pred_2") is True
    assert causal_reasoner._validate_chronology("evt_pred_2", "evt_pred_1") is False

def test_validate_chronology_missing_dates(causal_reasoner, test_db):
    """Test validation allows link when no dates are available (benefit of the doubt)."""
    create_event(test_db, "evt_no_date_1")
    create_event(test_db, "evt_no_date_2")
    
    assert causal_reasoner._validate_chronology("evt_no_date_1", "evt_no_date_2") is True
