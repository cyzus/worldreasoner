"""Tool to retrieve events related to a question."""

import json
from typing import Optional
from datetime import datetime, timezone

from src.tools.database_mixin import DatabaseAwareTool
from src.domain.models import Event, Question
from src.utils.logging import logger


class QuestionEventsTool(DatabaseAwareTool):
    """Retrieves all events created for the current question.

    This tool requires no input arguments - it uses the question_id
    provided at initialization to find relevant events.

    Use this tool to see:
    - What events have been created for this question
    - Which events are the OUTCOME events (is_outcome=True)
    - Which outcome is the ACTUAL outcome matching ground truth (is_actual_outcome=True)
    - Event IDs needed for creating causal links with causal_reasoner
    """

    name = "get_question_events"
    description = """Retrieves all events associated with the current question.

    No input required. Returns a JSON object containing:
    - outcome_events: List of outcome events (is_outcome=True) with their IDs and scenarios
    - regular_events: List of regular events with id, title, occurred_date
    - total_events: Count of all events
    - total_outcome_events: Count of outcome events

    Use this to find the outcome_event_id you need when linking events with causal_reasoner.
    """

    inputs = {
        "include_descriptions": {
            "type": "boolean",
            "description": "Include event descriptions in output (default: False to reduce token usage)",
            "default": False,
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, db_path: str = None, question_id: Optional[str] = None):
        """Initialize the tool.

        Args:
            db_path: Path to the database
            question_id: Question ID to get events for (injected at init)
        """
        super().__init__(db_path=db_path, ensure_tables=[Event, Question])
        self.question_id = question_id

    def forward(self, include_descriptions: bool = False) -> str:
        """Get events created for this question.

        Args:
            include_descriptions: Whether to include event descriptions

        Returns:
            JSON string with categorized event list
        """
        if not self.question_id:
            return json.dumps(
                {"error": "No question_id context provided", "events": []}
            )

        if not self.db:
            return json.dumps({"error": "No database connection", "events": []})

        # Get question to find related event IDs
        question = self.db.get(Question, self.question_id)
        if not question:
            return json.dumps(
                {"error": f"Question {self.question_id} not found", "events": []}
            )

        # Collect all event IDs related to this question
        event_ids = set()
        
        # From outcome_event_ids
        if question.outcome_event_ids:
            event_ids.update(question.outcome_event_ids)
        
        # From target_event_id (legacy)
        if question.target_event_id:
            event_ids.add(question.target_event_id)
        
        # From related_event_ids
        if question.related_event_ids:
            event_ids.update(question.related_event_ids)

        # Fetch all events
        events = []
        for event_id in event_ids:
            event = self.db.get(Event, event_id)
            if event:
                events.append(event)

        logger.debug(
            f"Found {len(events)} total events for question {self.question_id}"
        )

        # Categorize events
        outcome_events = []
        regular_events = []

        for event in events:
            event_data = {
                "id": event.id,
                "title": event.title,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
                "predicted_date": event.predicted_date.isoformat()
                if event.predicted_date
                else None,
            }

            if include_descriptions:
                event_data["description"] = event.description[:200] + "..." \
                    if len(event.description) > 200 else event.description

            if event.is_outcome:
                event_data["outcome_scenario"] = event.outcome_scenario.value \
                    if event.outcome_scenario else None
                event_data["is_actual_outcome"] = event.is_actual_outcome
                outcome_events.append(event_data)
            else:
                regular_events.append(event_data)

        # Sort by date
        outcome_events.sort(
            key=lambda e: e.get("occurred_date") or e.get("predicted_date") or "",
            reverse=True
        )
        regular_events.sort(
            key=lambda e: e.get("occurred_date") or e.get("predicted_date") or "",
            reverse=True
        )

        # Highlight the actual outcome for easy identification
        actual_outcome_id = None
        for oe in outcome_events:
            if oe.get("is_actual_outcome"):
                actual_outcome_id = oe["id"]
                break

        return json.dumps(
            {
                "question_id": self.question_id,
                "actual_outcome_event_id": actual_outcome_id,
                "total_outcome_events": len(outcome_events),
                "total_regular_events": len(regular_events),
                "outcome_events": outcome_events,
                "regular_events": regular_events,
                "hint": "Use 'actual_outcome_event_id' as target when creating final causal links."
            },
            indent=2,
        )
