"""Tool to record the impact of an event on a specific possible outcome."""

from datetime import datetime, timezone
import uuid
from typing import Optional

from smolagents import Tool
from src.domain.models import Event
from src.domain.models.event_outcome_impact import EventOutcomeImpact, ImpactDirection
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.base import ToolResponseMixin
from src.tools.base.output_models import OutcomeImpactOutput
from src.utils.logging import logger


class RecordOutcomeImpactTool(Tool, ToolResponseMixin):
    """Tool to record how a specific event affects the likelihood of a given outcome.

    This replaces the JSON string in event_identifier with a native typed tool.
    """

    name = "record_outcome_impact"
    description = """Record how a specific event impacts the likelihood of a given outcome scenario.
    
    Use this to link a verified event to one of the possible outcomes of the question, 
    stating whether it makes the outcome more or less likely.
    """

    inputs = {
        "event_id": {"type": "string", "description": "ID of the event"},
        "outcome_event_id": {
            "type": "string",
            "description": "ID of the outcome event",
        },
        "direction": {
            "type": "string",
            "description": "positive (makes outcome more likely), negative (less likely), or neutral",
            "enum": ["positive", "negative", "neutral"],
        },
        "magnitude": {
            "type": "number",
            "description": "How strong is this impact? (0.0 to 1.0)",
        },
        "confidence": {
            "type": "number",
            "description": "How confident are you in this assessment? (0.0 to 1.0)",
        },
        "reasoning": {
            "type": "string",
            "description": "Explanation of why the event impacts the outcome this way",
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(OutcomeImpactOutput)

    def __init__(self, db_path: str = None, question_id: Optional[str] = None):
        """Initialize the tool."""
        super().__init__()
        self.question_id = question_id

        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

        if self.db:
            self.db.create_table(EventOutcomeImpact)
            self.db.create_table(Event)

    def forward(
        self,
        event_id: str,
        outcome_event_id: str,
        direction: str,
        magnitude: float,
        confidence: float,
        reasoning: str,
    ) -> OutcomeImpactOutput:
        """Record an outcome impact.

        Returns:
            JSON confirmation with impact ID
        """
        if not self.db:
            return OutcomeImpactOutput(
                status="error", impact_id="error", error="Database is not initialized."
            )

        # Validate events exist
        event = self.db.get(Event, event_id)
        if not event:
            return OutcomeImpactOutput(
                status="error",
                impact_id="error",
                error=f"event_id '{event_id}' not found. Create it first with event_identifier.",
            )

        outcome = self.db.get(Event, outcome_event_id)
        if not outcome:
            return OutcomeImpactOutput(
                status="error",
                impact_id="error",
                error=f"outcome_event_id '{outcome_event_id}' not found.",
            )

        # Parse direction
        try:
            dir_enum = ImpactDirection(direction.lower())
        except ValueError:
            return OutcomeImpactOutput(
                status="error",
                impact_id="error",
                error=f"Invalid direction '{direction}'. Must be positive, negative, or neutral.",
            )

        # Clamp values
        magnitude = max(0.0, min(1.0, float(magnitude)))
        confidence = max(0.0, min(1.0, float(confidence)))

        # Create impact record
        impact_id = f"imp_{uuid.uuid4().hex[:8]}"
        current_time = datetime.now(timezone.utc)

        # question_id is required
        qid = self.question_id or "unknown_question"

        impact = EventOutcomeImpact(
            id=impact_id,
            event_id=event_id,
            outcome_event_id=outcome_event_id,
            question_id=qid,
            impact_direction=dir_enum,
            impact_magnitude=magnitude,
            confidence=confidence,
            reasoning=reasoning,
            discovered_by_question_ids=[qid] if self.question_id else [],
            identified_by="record_outcome_impact_tool",
            first_identified_at=current_time,
            last_confirmed_at=current_time,
        )

        self.db.save(EventOutcomeImpact, impact)
        logger.debug(f"Recorded outcome impact {impact_id}")

        return OutcomeImpactOutput(status="recorded", impact_id=impact_id)
