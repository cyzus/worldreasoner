"""Tool to delete an event and its associated hypotheses from the graph."""

from smolagents import Tool
from src.domain.models import Event, CausalHypothesis
from src.tools.base.base import ToolResponseMixin
from src.utils.logging import logger


class DeleteEventTool(Tool, ToolResponseMixin):
    """Tool to delete an incorrectly created event."""

    name = "delete_event"
    description = """Delete an event and all its causal links from the graph.
    
    Use this if you made a mistake (e.g., duplicated an event, wrong date) 
    and need to prune it from the graph to try again.
    """

    inputs = {
        "event_id": {"type": "string", "description": "ID of the event to delete"}
    }
    output_type = "string"

    def __init__(self, db_path: str = None):
        """Initialize the tool."""
        super().__init__()
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

    def forward(self, event_id: str) -> str:
        """Delete an event.

        Returns:
            JSON confirmation string
        """
        if not self.db:
            return self.error_response(
                "Database is not initialized.", error="db_not_initialized"
            )

        event = self.db.get(Event, event_id)
        if not event:
            return self.error_response(
                f"Event '{event_id}' not found.", error="event_not_found"
            )

        if getattr(event, "is_outcome", False):
            return self.error_response(
                f"Cannot delete event '{event_id}'. This is an outcome event. Outcome events represent the possible answers to the question and should not be deleted.",
                error="cannot_delete_outcome",
            )

        # Find and delete associated hypotheses
        hypotheses = self.db.get_many(CausalHypothesis)
        deleted_hyps = 0
        for hyp in hypotheses:
            if hyp.source_event_id == event_id or hyp.target_event_id == event_id:
                self.db.delete(CausalHypothesis, hyp.id)
                deleted_hyps += 1

        # Delete event
        self.db.delete(Event, event_id)
        logger.debug(
            f"Deleted event {event_id} and {deleted_hyps} associated hypotheses."
        )

        return self.json_response(
            {
                "status": "deleted",
                "event_id": event_id,
                "associated_hypotheses_deleted": deleted_hyps,
            }
        )
