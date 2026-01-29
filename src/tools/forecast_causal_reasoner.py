"""Causal reasoning for forecasting - saves to forecast DB.

This tool creates causal links during forecasting and saves them as
ForecastHypothesis instances in the forecast database.
"""

import json

from smolagents import Tool
from src.domain.models.forecast_graph import ForecastHypothesis
from src.domain.models.event import CausalRelationType
from src.core.database import GenericDatabase
from src.utils.logging import logger
from src.utils.id_generator import generate_forecast_hypothesis_id
from src.utils.enums import enum_to_list


class ForecastCausalReasonerTool(Tool):
    """Create causal links during forecasting, save to forecast DB.

    This tool allows the forecasting agent to build causal graphs by
    identifying relationships between events and recording them.
    """

    name = "create_forecast_causal_link"
    description = """Create causal link for forecast reasoning (saved to forecast DB).

    Use this tool to record causal relationships you identify between events
    during your forecast reasoning.

    IMPORTANT: For multi-hop graphs, create SEPARATE links for each step:
    - If A→B→C, call this tool twice: once for A→B, once for B→C
    - Build causal graphs by connecting intermediate events

    Args:
        source_event_id (str): ID of the event that causes the target
        target_event_id (str): ID of the event that is caused
        relation_type (str): Type of causation (causes|enables|prevents|correlates_with|conditional)
        strength (float): Strength of causal effect (0.0-1.0)
        confidence (float): Your confidence in this link (0.0-1.0)
        reasoning (str): Detailed explanation of the causal mechanism
        evidence_article_ids (str, optional): Comma-separated article IDs supporting this claim

    Returns:
        str: JSON confirmation with hypothesis ID
    """

    inputs = {
        "source_event_id": {"type": "string", "description": "Event ID of the cause"},
        "target_event_id": {"type": "string", "description": "Event ID of the effect"},
        "relation_type": {
            "type": "string",
            "description": f"Type of causation - one of: {', '.join(enum_to_list(CausalRelationType))}",
            "enum": enum_to_list(CausalRelationType),
        },
        "strength": {
            "type": "number",
            "description": "Causal strength 0.0-1.0 (how strong the effect)",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence 0.0-1.0 (how sure you are)",
        },
        "reasoning": {
            "type": "string",
            "description": "Detailed explanation of the causal mechanism",
        },
        "evidence_article_ids": {
            "type": "string",
            "description": "Comma-separated article IDs supporting this claim",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(
        self, forecast_db_path: str = "worldreasoner.db", session_id: str = None
    ):
        """Initialize the forecast causal reasoner.

        Args:
            forecast_db_path: Path to forecast database
            session_id: Session ID for tracking this forecast session
        """
        super().__init__()

        # Initialize database using simplified pattern

        self.forecast_db = GenericDatabase(forecast_db_path)

        self.session_id = session_id

    def forward(
        self,
        source_event_id: str,
        target_event_id: str,
        relation_type: str,
        strength: float,
        confidence: float,
        reasoning: str,
        evidence_article_ids: str = "",
    ) -> str:
        """Create causal link and save to forecast database.

        Args:
            source_event_id: Event that causes the outcome
            target_event_id: Event that is caused
            relation_type: Type of causal relationship
            strength: Causal strength (0-1)
            confidence: Confidence in this link (0-1)
            reasoning: Explanation of mechanism
            evidence_article_ids: Comma-separated article IDs

        Returns:
            JSON confirmation with hypothesis ID
        """
        try:
            # Validate relation type
            try:
                relation_enum = CausalRelationType(relation_type.lower())
            except ValueError:
                return json.dumps(
                    {
                        "error": f"Invalid relation_type: {relation_type}. "
                        f"Use: causes, enables, prevents, correlates_with, conditional"
                    }
                )

            # Validate ranges
            if not (0.0 <= strength <= 1.0):
                return json.dumps({"error": "strength must be 0.0-1.0"})
            if not (0.0 <= confidence <= 1.0):
                return json.dumps({"error": "confidence must be 0.0-1.0"})

            # Parse article IDs
            article_ids = [
                aid.strip() for aid in evidence_article_ids.split(",") if aid.strip()
            ]

            # Create and save ForecastHypothesis
            hyp_id = generate_forecast_hypothesis_id()
            hypothesis = ForecastHypothesis(
                id=hyp_id,
                forecast_id=None,
                session_id=self.session_id,
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                relation_type=relation_enum,
                strength=strength,
                confidence=confidence,
                reasoning=reasoning,
                evidence_article_ids=article_ids,
            )

            self.forecast_db.save(ForecastHypothesis, hypothesis)
            logger.info(f"Saved forecast hypothesis: {hyp_id}")

            return json.dumps(
                {
                    "status": "created",
                    "hypothesis_id": hyp_id,
                    "relation": f"{source_event_id} {relation_enum.value} {target_event_id}",
                    "strength": strength,
                    "confidence": confidence,
                },
                indent=2,
            )

        except Exception as e:
            logger.error(f"Error creating forecast causal link: {e}")
            return json.dumps({"error": str(e)})
