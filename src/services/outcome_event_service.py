"""Service for creating outcome events."""

from typing import List, Optional
import uuid

from src.core.database import GenericDatabase
from src.domain.models.event import Event, OutcomeScenario, EventStatus, EventType
from src.domain.models.question import Question, QuestionType
from src.utils.logging import logger


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
            options = (
                question.options
                or (question.metadata and question.metadata.get("options"))
                or []
            )

            for idx, option in enumerate(options):
                # Check if this option matches ground truth
                is_actual = False
                if question.ground_truth is not None:
                    # Match by exact string or index if integer
                    if isinstance(question.ground_truth, int):
                        is_actual = idx == question.ground_truth
                    else:
                        is_actual = self._normalize_text(
                            question.ground_truth
                        ) == self._normalize_text(option)

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
                    occurred_date=question.resolution_date,
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
                occurred_date=question.resolution_date,
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
        parsed_truth = self._parse_binary_ground_truth(question.ground_truth)
        if parsed_truth is not None:
            is_actual = parsed_truth == is_positive

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
            occurred_date=question.resolution_date,
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

    def ensure_actual_outcome_alignment(self, question: Question) -> List[Event]:
        """Backfill/update outcome flags for existing outcome events.

        This is idempotent and safe to call on every pipeline run.
        It ensures `is_actual_outcome` is consistent with the question ground truth,
        including binary questions where ground_truth may be stored as "Yes"/"No".
        """
        outcome_events = self.get_outcome_events_for_question(question.id)
        if not outcome_events:
            return []

        changed = False

        if question.question_type == QuestionType.BINARY:
            parsed_truth = self._parse_binary_ground_truth(question.ground_truth)
            for event in outcome_events:
                scenario = event.outcome_scenario
                if parsed_truth is None or scenario is None:
                    continue

                should_be_actual = (
                    parsed_truth
                    if scenario == OutcomeScenario.POSITIVE_RESOLUTION
                    else not parsed_truth
                )

                if event.is_actual_outcome != should_be_actual:
                    event.is_actual_outcome = should_be_actual
                    event.status = (
                        EventStatus.OCCURRED
                        if should_be_actual
                        else EventStatus.PREDICTED
                    )
                    event.occurred_date = (
                        question.resolution_date if should_be_actual else None
                    )
                    self.db.save(Event, event)
                    changed = True

        elif (
            question.question_type == QuestionType.MCQ
            and question.ground_truth is not None
        ):
            normalized_truth = self._normalize_text(question.ground_truth)

            for event in outcome_events:
                should_be_actual = False

                if (
                    isinstance(question.ground_truth, int)
                    and event.outcome_option_index is not None
                ):
                    should_be_actual = (
                        event.outcome_option_index == question.ground_truth
                    )
                elif event.outcome_option_index is not None and question.options:
                    if event.outcome_option_index < len(question.options):
                        option = question.options[event.outcome_option_index]
                        should_be_actual = (
                            self._normalize_text(option) == normalized_truth
                        )
                    else:
                        logger.warning(
                            f"Event {event.id} has outcome_option_index={event.outcome_option_index} "
                            f"but question only has {len(question.options)} options"
                        )
                        should_be_actual = False
                else:
                    # Fallback: parse from title "Option N: value"
                    title = event.title or ""
                    option_part = title.split(":", 1)[1] if ":" in title else title
                    should_be_actual = (
                        self._normalize_text(option_part) == normalized_truth
                    )

                if event.is_actual_outcome != should_be_actual:
                    event.is_actual_outcome = should_be_actual
                    event.status = (
                        EventStatus.OCCURRED
                        if should_be_actual
                        else EventStatus.PREDICTED
                    )
                    event.occurred_date = (
                        question.resolution_date if should_be_actual else None
                    )
                    self.db.save(Event, event)
                    changed = True

        elif (
            question.question_type == QuestionType.QUANTITY
            and question.ground_truth is not None
        ):
            for event in outcome_events:
                if event.is_actual_outcome is not True:
                    event.is_actual_outcome = True
                    event.status = EventStatus.OCCURRED
                    event.occurred_date = question.resolution_date
                    self.db.save(Event, event)
                    changed = True

        if changed:
            # Keep question.outcome_event_ids in sync in case legacy data is missing IDs.
            question.outcome_event_ids = [e.id for e in outcome_events]
            self.db.save(Question, question)

        return outcome_events

    @staticmethod
    def _normalize_text(value) -> str:
        """Normalize values like '\"Yes\"' and ' yes ' for stable comparisons."""
        if value is None:
            return ""
        text = str(value).strip()
        text = text.strip('"').strip("'").strip()
        return text.lower()

    def _parse_binary_ground_truth(self, value) -> Optional[bool]:
        """Parse binary ground truth from bool/string/int representations."""
        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False

        normalized = self._normalize_text(value)
        if normalized in {"yes", "true", "y", "1"}:
            return True
        if normalized in {"no", "false", "n", "0"}:
            return False

        return None

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
