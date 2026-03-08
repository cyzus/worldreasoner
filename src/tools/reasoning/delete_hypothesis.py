"""Tool to delete a causal hypothesis from the graph."""

from smolagents import Tool
from src.domain.models import CausalHypothesis
from src.tools.base.base import ToolResponseMixin
from src.utils.logging import logger


class DeleteHypothesisTool(Tool, ToolResponseMixin):
    """Tool to delete an incorrectly created causal relationship."""

    name = "delete_hypothesis"
    description = """Delete a causal link between two events from the graph.
    
    Use this if you made a mistake linking two events (e.g., connected backwards, 
    wrong relationship type, or cycle) and need to prune the edge to try again.
    """

    inputs = {
        "source_event_id": {"type": "string", "description": "ID of the source event"},
        "target_event_id": {"type": "string", "description": "ID of the target event"},
    }
    output_type = "string"

    def __init__(self, db_path: str = None):
        """Initialize the tool."""
        super().__init__()
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

    def forward(self, source_event_id: str, target_event_id: str) -> str:
        """Delete a causal hypothesis.

        Returns:
            JSON confirmation string
        """
        if not self.db:
            return self.error_response(
                "Database is not initialized.", error="db_not_initialized"
            )

        # Find and delete associated hypothesis
        hypotheses = self.db.get_many(CausalHypothesis)
        deleted = False
        hyp_id = None
        for hyp in hypotheses:
            if (
                hyp.source_event_id == source_event_id
                and hyp.target_event_id == target_event_id
            ):
                hyp_id = hyp.id
                self.db.delete(CausalHypothesis, hyp.id)
                deleted = True
                break

        if not deleted:
            return self.error_response(
                f"No hypothesis found linking '{source_event_id}' to '{target_event_id}'.",
                error="hypothesis_not_found",
            )

        logger.debug(f"Deleted hypothesis {hyp_id}.")

        return self.json_response(
            {
                "status": "deleted",
                "source_event_id": source_event_id,
                "target_event_id": target_event_id,
                "hypothesis_id": hyp_id,
            }
        )
