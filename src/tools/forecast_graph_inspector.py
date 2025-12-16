"""Graph inspection for forecasting - queries forecast DB.

This tool allows the forecasting agent to inspect the causal graph
it has built during its reasoning process.
"""

from smolagents import Tool
import json
from collections import defaultdict

from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis
from src.core.database import GenericDatabase
from src.utils.logging import logger


class ForecastGraphInspectorTool(Tool):
    """Inspect causal graph built during forecasting.

    This tool helps you understand the quality and structure of the
    causal reasoning graph you've built so far.
    """

    name = "inspect_forecast_graph"
    description = """Inspect forecast's causal reasoning graph (depth, quality).

    Use this tool to check the causal graph you've built during forecasting.
    It shows statistics about events, causal links, graph depth, and provides
    feedback on the quality of your reasoning.

    No arguments required - uses the current session.

    Returns:
        str: JSON with graph statistics and quality assessment
    """

    inputs = {}
    output_type = "string"

    def __init__(self, forecast_db_path: str = "worldreasoner.db", session_id: str = None):
        """Initialize the forecast graph inspector.

        Args:
            forecast_db_path: Path to forecast database
            session_id: Session ID for tracking this forecast session
        """
        super().__init__()
        self.forecast_db = GenericDatabase(forecast_db_path)
        self.session_id = session_id

    def forward(self) -> str:
        """Inspect the forecast graph for the current session.

        Returns:
            JSON string with graph statistics and quality feedback
        """
        try:
            # Query forecast DB for events and hypotheses in this session
            events = self.forecast_db.get_many(ForecastEvent, filters={'session_id': self.session_id})
            hypotheses = self.forecast_db.get_many(ForecastHypothesis, filters={'session_id': self.session_id})

            events_dict = [self._event_to_dict(e) for e in events]
            hyps_dict = [self._hypothesis_to_dict(h) for h in hypotheses]

            # Build graph adjacency list
            graph = defaultdict(list)
            for h in hyps_dict:
                graph[h['source_event_id']].append(h['target_event_id'])

            # Calculate graph metrics
            max_depth = self._calc_depth(graph, {e['id'] for e in events_dict})

            # Find root causes and leaf effects
            sources = {h['source_event_id'] for h in hyps_dict}
            targets = {h['target_event_id'] for h in hyps_dict}
            root_causes = sources - targets
            leaf_effects = targets - sources

            # Prepare result
            result = {
                "summary": {
                    "num_events": len(events_dict),
                    "num_causal_links": len(hyps_dict),
                    "max_depth": max_depth,
                    "num_root_causes": len(root_causes),
                    "num_leaf_effects": len(leaf_effects)
                },
                "quality": self._assess_quality(len(events_dict), len(hyps_dict), max_depth),
                "events": [{"id": e['id'], "title": e['title']} for e in events_dict],
                "causal_links": [
                    f"{h['source_event_id']} -> {h['target_event_id']} ({h['relation_type']})"
                    for h in hyps_dict
                ]
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error inspecting forecast graph: {e}")
            return json.dumps({"error": str(e)})

    def _calc_depth(self, graph: dict, event_ids: set) -> int:
        """Calculate maximum depth of the causal graph.

        Args:
            graph: Adjacency list representation
            event_ids: Set of all event IDs

        Returns:
            Maximum depth of the graph
        """
        max_depth = 0
        visited = set()

        def dfs(node: str, depth: int):
            nonlocal max_depth
            max_depth = max(max_depth, depth)
            visited.add(node)
            for target in graph.get(node, []):
                if target not in visited:
                    dfs(target, depth + 1)
            visited.remove(node)

        for eid in event_ids:
            if eid not in visited:
                dfs(eid, 1)

        return max_depth

    def _assess_quality(self, num_events: int, num_links: int, depth: int) -> dict:
        """Assess quality of the causal graph.

        Args:
            num_events: Number of events
            num_links: Number of causal links
            depth: Maximum graph depth

        Returns:
            Quality assessment with score and feedback
        """
        feedback = []

        # Event coverage
        if num_events < 3:
            feedback.append("Few events - explore more causes")
        elif num_events >= 5:
            feedback.append("Good event coverage")

        # Reasoning depth
        if depth < 2:
            feedback.append("Shallow reasoning - dig deeper")
        elif depth >= 3:
            feedback.append("Deep causal reasoning")

        # Connectivity
        if num_links == 0:
            feedback.append("No causal links yet")
        elif num_links >= num_events:
            feedback.append("Good connectivity")

        # Calculate score
        good_feedback = len([f for f in feedback if "Good" in f or "Deep" in f])
        score = "good" if good_feedback >= 2 else "needs_improvement"

        return {
            "score": score,
            "feedback": feedback
        }

    def _event_to_dict(self, event: ForecastEvent) -> dict:
        """Convert ForecastEvent to dictionary.

        Args:
            event: ForecastEvent instance

        Returns:
            Dictionary representation
        """
        return {
            "id": event.id,
            "title": event.title,
            "domain": event.domain.value if hasattr(event.domain, 'value') else event.domain,
            "occurred_date": event.occurred_date.isoformat() if event.occurred_date else None
        }

    def _hypothesis_to_dict(self, hypothesis: ForecastHypothesis) -> dict:
        """Convert ForecastHypothesis to dictionary.

        Args:
            hypothesis: ForecastHypothesis instance

        Returns:
            Dictionary representation
        """
        return {
            "id": hypothesis.id,
            "source_event_id": hypothesis.source_event_id,
            "target_event_id": hypothesis.target_event_id,
            "relation_type": hypothesis.relation_type.value if hasattr(hypothesis.relation_type, 'value') else hypothesis.relation_type,
            "strength": hypothesis.strength,
            "confidence": hypothesis.confidence
        }
