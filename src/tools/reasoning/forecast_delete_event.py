"""Tool to delete a forecast event and its associated hypotheses."""

from smolagents import Tool
from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis
from src.core.database import GenericDatabase
from src.utils.logging import logger


class ForecastDeleteEventTool(Tool):
    name = "delete_forecast_event"
    description = """Delete a forecast event and all its causal links from the graph.

    Use this to correct mistakes — e.g. duplicated events, wrong date, misidentified event.
    All hypotheses that reference the event (as source or target) are also deleted.
    """

    inputs = {
        "event_id": {"type": "string", "description": "ID of the forecast event to delete"}
    }
    output_type = "string"

    def __init__(self, forecast_db_path: str = "worldreasoner.db", session_id: str = None):
        super().__init__()
        self.forecast_db = GenericDatabase(forecast_db_path)
        self.session_id = session_id

    def forward(self, event_id: str) -> str:
        events = self.forecast_db.get_many(ForecastEvent, filters={"id": event_id})
        if not events:
            return f'{{"status": "error", "error": "Event {event_id!r} not found"}}'

        event = events[0]
        if self.session_id and event.session_id != self.session_id:
            return f'{{"status": "error", "error": "Event {event_id!r} does not belong to this session"}}'

        hypotheses = self.forecast_db.get_many(ForecastHypothesis, filters={"session_id": self.session_id})
        deleted_hyps = 0
        for hyp in hypotheses:
            if hyp.source_event_id == event_id or hyp.target_event_id == event_id:
                self.forecast_db.delete(ForecastHypothesis, hyp.id)
                deleted_hyps += 1

        self.forecast_db.delete(ForecastEvent, event_id)
        logger.info(f"Deleted forecast event {event_id} and {deleted_hyps} hypotheses")

        return f'{{"status": "deleted", "event_id": "{event_id}", "hypotheses_deleted": {deleted_hyps}}}'
