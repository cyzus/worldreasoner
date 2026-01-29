"""Causal reasoner tool - LLM proposes causal explanations with hindsight."""

from datetime import datetime, timezone
import uuid
from typing import Optional

from smolagents import Tool
from src.domain.models import CausalHypothesis, CausalRelationType, Event
from src.core.collectors import ResultCollector
from src.utils.enums import enum_to_list
from src.tools.base import ToolResponseMixin


class CausalReasonerTool(Tool, ToolResponseMixin):
    """Tool for LLM to propose causal explanations with hindsight.

    This tool allows the agent to:
    1. Analyze evidence with the benefit of hindsight
    2. Identify causal relationships between events
    3. Propose structured hypotheses with confidence scores
    4. Cite evidence articles supporting each claim

    The LLM should first analyze the evidence articles and the outcome,
    then use this tool to record each identified causal relationship.
    """

    name = "causal_reasoner"
    description = """Create a causal link in the graph between two events.

    CRITICAL FOR DEEP GRAPHS: Build multi-level causal chains, not just direct links!

    PROCESS FOR DEEP CAUSAL GRAPHS:
    1. Create intermediate events first using event_identifier
    2. Link them in chains: Root Cause → Intermediate → Immediate → Target
    3. Don't just link everything directly to the target event!

    Example for "Why did stock price crash?":
    - Target: "Stock price fell 25%" (evt_target)
    - Don't just do: "Bad earnings" → Target
    - Instead build chain:
      a) Create: "Whistleblower report filed" (evt_1)
      b) Create: "SEC investigation opened" (evt_2)
      c) Create: "CEO resigned" (evt_3)
      d) Create: "Stock downgraded" (evt_4)
      e) Link: evt_1 → evt_2 → evt_3 → evt_4 → evt_target

    This creates a 5-level causal chain instead of shallow 1-level!

    BEFORE calling this tool:
    - Ensure both source and target events exist (use event_identifier first!)
    - Check graph_inspector to see current depth
    - If depth < 2, you need MORE intermediate events!

    Args:
        source_event_id (str): ID of the event that caused the target
        target_event_id (str): ID of the event that was caused (can be intermediate or final)
        relation_type (str): Type of causation (causes|enables|prevents|correlates|conditional)
        strength (float): Strength of causal effect (0.0-1.0)
        confidence (float): Your confidence in this link (0.0-1.0)
        reasoning (str): Detailed explanation of the causal mechanism
        evidence_article_ids (str): Comma-separated article IDs that support this claim

    Returns:
        str: JSON confirmation with hypothesis ID
    """

    inputs = {
        "source_event_id": {"type": "string", "description": "Event ID of the cause"},
        "target_event_id": {
            "type": "string",
            "description": "Event ID of the effect (can be intermediate or final outcome)",
        },
        "relation_type": {
            "type": "string",
            "description": f"Type of relations: {', '.join(enum_to_list(CausalRelationType))}",
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
    output_type = "string"  # JSON confirmation

    def __init__(
        self,
        collector: Optional[ResultCollector[CausalHypothesis]] = None,
        db_path: str = None,
        question_id: Optional[str] = None,
    ):
        """Initialize the causal reasoner tool.

        Args:
            collector: Optional ResultCollector for storing hypotheses
            db_path: Optional database path for persisting hypotheses
            question_id: Default question ID for provenance (used if not passed in forward())
        """
        super().__init__()
        self.collector = collector
        self.hypotheses = []  # Fallback for backward compatibility
        self._counter = 0  # For generating hypothesis IDs
        self.default_question_id = question_id  # Default context if agent forgets

        # Initialize database using DatabaseAwareTool pattern
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

        # Ensure schema is initialized
        if self.db:
            self.db.create_table(CausalHypothesis)

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
        """Record a causal hypothesis with supporting evidence.

        Args:
            source_event_id: Event that caused the outcome
            target_event_id: Event that was caused
            relation_type: Type of causal relationship
            strength: Causal strength (0-1)
            confidence: Confidence in this link (0-1)
            reasoning: Explanation of mechanism
            evidence_article_ids: Comma-separated article IDs

        Returns:
            JSON confirmation with hypothesis ID
        """
        # Use default question_id if not provided or empty
        question_id = self.default_question_id

        # Validate and parse relation type
        try:
            relation = CausalRelationType(relation_type.lower())
        except ValueError:
            # Default to CAUSES if invalid
            relation = CausalRelationType.CAUSES

        # Parse evidence article IDs
        evidence_ids = []
        if evidence_article_ids:
            evidence_ids = [
                aid.strip() for aid in evidence_article_ids.split(",") if aid.strip()
            ]

        # Clamp strength and confidence to [0, 1]
        strength = max(0.0, min(1.0, float(strength)))
        confidence = max(0.0, min(1.0, float(confidence)))

        # Validate chronology - source must occur before target
        if not self._validate_chronology(source_event_id, target_event_id):
            return self.error_response(
                "Chronology validation failed: source event must occur before target event - also make sure you provide occurred_date for both events",
                status="error",
                source_event_id=source_event_id,
                target_event_id=target_event_id,
            )

        # Generate unique hypothesis ID
        hypothesis_id = self._generate_hypothesis_id(question_id)

        # Create CausalHypothesis object
        current_time = datetime.now(timezone.utc)
        hypothesis = CausalHypothesis(
            id=hypothesis_id,
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation,
            strength=strength,
            confidence=confidence,
            reasoning=reasoning,
            evidence_article_ids=evidence_ids,
            discovered_by_question_ids=[question_id],
            identified_by="evidence_pipeline",
            first_identified_at=current_time,
            last_confirmed_at=current_time,
        )

        # Store hypothesis
        # CRITICAL: Use 'is not None' check (ResultCollector.__bool__ returns False when empty)
        if self.collector is not None:
            self.collector.add(hypothesis)
        else:
            # Fallback for backward compatibility
            self.hypotheses.append(hypothesis)

        # Persist to database if available
        if self.db is not None:
            self.db.save(CausalHypothesis, hypothesis)
            from src.utils.logging import logger

            logger.debug(f"Hypothesis {hypothesis_id} persisted to database")

        # Return confirmation (minimal to save tokens)
        confirmation = {
            "status": "recorded",
            "hypothesis_id": hypothesis_id,
            "relation": f"{source_event_id} {relation.value} {target_event_id}",
            "strength": strength,
            "confidence": confidence,
            "evidence_count": len(evidence_ids),
        }

        return self.json_response(confirmation)

    def _generate_hypothesis_id(self, question_id: str) -> str:
        """Generate unique hypothesis ID.

        Args:
            question_id: Question this hypothesis relates to

        Returns:
            Unique hypothesis ID
        """
        self._counter += 1
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        suffix = uuid.uuid4().hex[:8]
        return f"hyp_{question_id}_{timestamp}_{self._counter:03d}_{suffix}"

    def _validate_chronology(self, source_event_id: str, target_event_id: str) -> bool:
        """Validate that source event occurs before target event.

        Args:
            source_event_id: ID of the source event
            target_event_id: ID of the target event

        Returns:
            True if chronology is valid, False otherwise
        """
        if self.db is None:
            return True  # Cannot validate without DB

        # Fetch events from database
        source_event = self.db.get(Event, source_event_id)
        target_event = self.db.get(Event, target_event_id)

        # Check if events exist
        if source_event is None or target_event is None:
            return False  # Cannot validate if events don't exist

        # Check if dates are present
        if source_event.occurred_date is None or target_event.occurred_date is None:
            return False  # Cannot validate without dates

        # Validate chronological order
        return source_event.occurred_date < target_event.occurred_date
