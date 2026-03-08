
import pytest
from src.tools.inspectors.graph_inspector import GraphInspectorTool
from src.domain.models import Question, Event, CausalHypothesis, EventType, Domain, CausalRelationType
from datetime import datetime, timezone

@pytest.fixture
def graph_inspector(test_db):
    return GraphInspectorTool(question_id="q1", db_path=test_db.db_path)

def create_basics(db):
    # Create question
    q = Question(
        id="q1",
        question_text="Will it rain tomorrow in San Francisco, CA?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="test",
        difficulty=1,
        resolution_date=datetime.now(timezone.utc),
        outcome_event_ids=["evt_outcome"],
        target_event_id="evt_wrong_target" # Deprecated field pointing to wrong event
    )
    db.save(Question, q)
    
    # Create events
    e_root = Event(
        id="evt_root", title="Root Cause", description="This is a detailed description for the Root Cause event.", 
        event_type=EventType.INDICATOR, domain=Domain.GENERAL,
        status="occurred", occurred_date=datetime.now(timezone.utc)
    )
    e_mid = Event(
        id="evt_wrong_target", title="Intermediate", description="This is a detailed description for the Intermediate event.",
        event_type=EventType.INDICATOR, domain=Domain.GENERAL,
        status="occurred", occurred_date=datetime.now(timezone.utc)
    )
    e_outcome = Event(
        id="evt_outcome", title="Outcome", description="This is a detailed description for the Outcome event.",
        event_type=EventType.OUTCOME, domain=Domain.GENERAL,
        status="predicted", predicted_date=datetime.now(timezone.utc),
        is_outcome=True, is_actual_outcome=True
    )
    db.save(Event, e_root)
    db.save(Event, e_mid)
    db.save(Event, e_outcome)
    
    # Create hypotheses: Root -> Mid -> Outcome
    h1 = CausalHypothesis(
        id="h1", source_event_id="evt_root", target_event_id="evt_wrong_target",
        relation_type=CausalRelationType.CAUSES, strength=0.8, confidence=0.8,
        reasoning="This is a valid reasoning explanation.", discovered_by_question_ids=["q1"]
    )
    h2 = CausalHypothesis(
        id="h2", source_event_id="evt_wrong_target", target_event_id="evt_outcome",
        relation_type=CausalRelationType.CAUSES, strength=0.8, confidence=0.8,
        reasoning="This is a valid reasoning explanation.", discovered_by_question_ids=["q1"]
    )
    db.save(CausalHypothesis, h1)
    db.save(CausalHypothesis, h2)

def test_visualization_target_identification(graph_inspector, test_db):
    create_basics(test_db)
    
    # Run inspector
    output = graph_inspector.forward()
    
    # Expectation: 
    # BEFORE FIX: It likely uses q.target_event_id ("evt_wrong_target") as root
    # AFTER FIX: It should use q.outcome_event_ids ("evt_outcome") as root
    
    # If correct (Target = Outcome):
    # Chain: Root -> Mid -> Outcome (depth 2)
    
    # If incorrect (Target = Mid):
    # Chain: Root -> Mid (depth 1)
    # The Outcome event would appear as disconnected or childless
    
    # print(output) # Causing UnicodeEncodeError in Windows/GBK env
    # Check if correct target is being visualized as the root of chains
    
    
    # Check if correct target is being visualized as the root of chains
    # The output text should contain "Chain 1 (depth: 2)" if correct
    # Or "Chain 1 (depth: 1)" if incorrect
    
    assert "Chain 1 (depth: 2)" in output
    # Check for target icon next to outcome description
    assert "🎯 This is a detailed description for the Outcome event." in output
