"""Service for creating outcome events."""

from typing import List
import uuid

from src.core.database import GenericDatabase
from src.domain.models.event import Event, OutcomeScenario, EventStatus, EventType
from src.domain.models.question import Question, QuestionType


class OutcomeEventService:
    """Service for creating outcome events (Events with is_outcome=True)."""

    def __init__(self, db: GenericDatabase):
        self.db = db

    def auto_create_outcome_events(self, question: Question) -> List[Event]:
        """Auto-create standard outcome events when a question is created.

        Creates Events with is_outcome=True to represent possible resolutions.
        If question has ground_truth, matches and marks the correct outcome as actual.

        Args:
            question: Question to create outcome events for

        Returns:
            List of created Event objects (with is_outcome=True)
        """
        outcome_events = []

        if question.question_type == QuestionType.BINARY:
            # Create Yes and No outcome events
            outcome_events.append(
                self._create_binary_outcome_event(
                    question,
                    is_positive=True,
                    title=f"Yes - {question.question_text[:50]}",
                    description=f"Positive resolution: {question.question_text}",
                )
            )
            outcome_events.append(
                self._create_binary_outcome_event(
                    question,
                    is_positive=False,
                    title=f"No - {question.question_text[:50]}",
                    description=f"Negative resolution: {question.question_text}",
                )
            )

        elif question.question_type == QuestionType.MCQ:
            # Create one outcome event per option
            # Fallback to metadata options if missing (legacy/ingestion issue)
            options = question.options or (question.metadata and question.metadata.get("options")) or []
            
            for idx, option in enumerate(options):
                # Check if this option matches ground truth
                is_actual = False
                if question.ground_truth is not None:
                    # Match by exact string or index if integer
                    if isinstance(question.ground_truth, int):
                         is_actual = (idx == question.ground_truth)
                    else:
                         is_actual = (str(question.ground_truth) == str(option))

                evt = Event(
                        id=f"evt_{uuid.uuid4().hex[:12]}",
                        title=f"Option {idx + 1}: {option}",
                        description=f"Question resolves to: {option}",
                        domain=question.domain,
                        event_type=EventType.OUTCOME,
                        is_outcome=True,
                        outcome_scenario=OutcomeScenario.MCQ_OPTION,
                        outcome_option_index=idx,
                        status=EventStatus.OCCURRED if is_actual else EventStatus.PREDICTED,
                        is_actual_outcome=is_actual,
                        extracted_for_question_id=question.id,
                    )
                
                # If actual, populate occurred_date
                if is_actual and question.resolution_date:
                    evt.occurred_date = question.resolution_date
                    
                outcome_events.append(evt)

        elif question.question_type == QuestionType.QUANTITY:
            # For quantity questions, create a single outcome event
            is_actual = question.ground_truth is not None
            
            evt = Event(
                    id=f"evt_{uuid.uuid4().hex[:12]}",
                    title=f"Quantity outcome: {question.question_text[:50]}",
                    description=f"Final value for: {question.question_text}",
                    domain=question.domain,
                    event_type=EventType.OUTCOME,
                    is_outcome=True,
                    outcome_scenario=OutcomeScenario.POSITIVE_RESOLUTION,
                    status=EventStatus.OCCURRED if is_actual else EventStatus.PREDICTED,
                    is_actual_outcome=is_actual,
                    extracted_for_question_id=question.id,
                )
             
            # If actual, populate occurred_date
            if is_actual and question.resolution_date:
                evt.occurred_date = question.resolution_date
                
            outcome_events.append(evt)

        # Save to database
        for event in outcome_events:
            self.db.save(Event, event)

        # Update question with outcome event IDs
        question.outcome_event_ids = [e.id for e in outcome_events]
        self.db.save(Question, question)

        return outcome_events

    def _create_binary_outcome_event(
        self, question: Question, is_positive: bool, title: str, description: str
    ) -> Event:
        """Create a binary outcome event (yes/no)."""
        is_actual = False
        if question.ground_truth is not None and isinstance(question.ground_truth, bool):
            is_actual = (question.ground_truth == is_positive)
            
        evt = Event(
            id=f"evt_{uuid.uuid4().hex[:12]}",
            title=title,
            description=description,
            domain=question.domain,
            event_type=EventType.OUTCOME,
            is_outcome=True,
            outcome_scenario=(
                OutcomeScenario.POSITIVE_RESOLUTION
                if is_positive
                else OutcomeScenario.NEGATIVE_RESOLUTION
            ),
            status=EventStatus.OCCURRED if is_actual else EventStatus.PREDICTED,
            is_actual_outcome=is_actual,
            extracted_for_question_id=question.id,
        )
        
        # If actual, populate occurred_date
        if is_actual and question.resolution_date:
            evt.occurred_date = question.resolution_date
            
        return evt

    def get_outcome_events_for_question(self, question_id: str) -> List[Event]:
        """Get all outcome events for a question."""
        return self.db.get_many(
            Event,
            filters={"extracted_for_question_id": question_id, "is_outcome": True},
        )

    def mark_actual_outcome(self, event_id: str, is_actual: bool = True) -> Event:
        """Mark an outcome event as the actual outcome (after resolution)."""
        event = self.db.get(Event, event_id)
        if not event:
            raise ValueError(f"Event {event_id} not found")
        if not event.is_outcome:
            raise ValueError(f"Event {event_id} is not an outcome event")

        event.is_actual_outcome = is_actual
        if is_actual:
            event.status = EventStatus.OCCURRED
            
            # Populate occurred_date from question resolution date
            if event.extracted_for_question_id:
                question = self.db.get(Question, event.extracted_for_question_id)
                if question and question.resolution_date:
                    event.occurred_date = question.resolution_date
        self.db.save(Event, event)
        return event
