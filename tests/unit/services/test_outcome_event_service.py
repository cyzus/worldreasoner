"""Outcome-event alignment tests for legacy question representations."""

from datetime import datetime, timezone
from pathlib import Path

from src.core.database import GenericDatabase
from src.domain.models import (
    Domain,
    Event,
    EventStatus,
    EventType,
    OutcomeScenario,
    Question,
    QuestionType,
)
from src.services.outcome_event_service import OutcomeEventService


def test_aligns_two_option_mcq_stored_as_binary_outcomes(tmp_path: Path) -> None:
    db = GenericDatabase(tmp_path / "legacy-mcq.db")
    db.create_table(Question)
    db.create_table(Event)
    resolution = datetime(2026, 2, 22, tzinfo=timezone.utc)
    question = Question(
        id="legacy-market",
        question_text="Which team will win the resolved championship game?",
        question_type=QuestionType.MCQ,
        domain=Domain.SPORTS,
        source="polymarket",
        difficulty=2,
        resolution_date=resolution,
        ground_truth="Finland",
        options=["Slovakia", "Finland"],
        outcome_event_ids=["yes", "no"],
    )
    db.save(Question, question)
    for event_id, scenario in (
        ("yes", OutcomeScenario.POSITIVE_RESOLUTION),
        ("no", OutcomeScenario.NEGATIVE_RESOLUTION),
    ):
        db.save(
            Event,
            Event(
                id=event_id,
                title=f"{event_id.title()} - championship game",
                description="Legacy binary market outcome",
                domain=Domain.SPORTS,
                event_type=EventType.OUTCOME,
                is_outcome=True,
                outcome_scenario=scenario,
                status=EventStatus.PREDICTED,
                is_actual_outcome=False,
                extracted_for_question_id=question.id,
            ),
        )

    outcomes = OutcomeEventService(db).ensure_actual_outcome_alignment(question)

    actual = [event for event in outcomes if event.is_actual_outcome]
    assert len(actual) == 1
    assert actual[0].id == "no"
    assert actual[0].status == EventStatus.OCCURRED
    assert actual[0].occurred_date == resolution
