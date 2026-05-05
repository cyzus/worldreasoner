"""Tool to delete a forecast causal hypothesis."""

from smolagents import Tool
from src.domain.models.forecast_graph import ForecastHypothesis
from src.core.database import GenericDatabase
from src.utils.logging import logger


class ForecastDeleteHypothesisTool(Tool):
    name = "delete_forecast_hypothesis"
    description = """Delete a causal link between two forecast events.

    Use this to correct mistakes — e.g. wrong direction, incorrect relation type,
    or an accidental duplicate link. Specify the source and target event IDs.
    """

    inputs = {
        "source_event_id": {"type": "string", "description": "ID of the source (causing) event"},
        "target_event_id": {"type": "string", "description": "ID of the target (caused) event"},
    }
    output_type = "string"

    def __init__(self, forecast_db_path: str = "worldreasoner.db", session_id: str = None):
        super().__init__()
        self.forecast_db = GenericDatabase(forecast_db_path)
        self.session_id = session_id

    def forward(self, source_event_id: str, target_event_id: str) -> str:
        hypotheses = self.forecast_db.get_many(ForecastHypothesis, filters={"session_id": self.session_id})
        for hyp in hypotheses:
            if hyp.source_event_id == source_event_id and hyp.target_event_id == target_event_id:
                self.forecast_db.delete(ForecastHypothesis, hyp.id)
                logger.info(f"Deleted forecast hypothesis {hyp.id}")
                return f'{{"status": "deleted", "hypothesis_id": "{hyp.id}", "source": "{source_event_id}", "target": "{target_event_id}"}}'

        return f'{{"status": "error", "error": "No hypothesis found linking {source_event_id!r} to {target_event_id!r}"}}'
