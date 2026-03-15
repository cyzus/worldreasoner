"""Causal reasoner tool - LLM proposes causal explanations with hindsight."""

from datetime import datetime, timezone
import uuid
from typing import Optional

from smolagents import Tool
from src.domain.models import CausalHypothesis, CausalRelationType, Event
from src.core.collectors import ResultCollector
from src.utils.enums import enum_to_list
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.base import ToolResponseMixin
from src.tools.base.output_models import HypothesisOutput


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
    description = """Identify relationship between events in order to create the event graph.

    Returns:
        str: JSON confirmation with relationship ID
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
            "description": (
                "Causal strength 0.0-1.0 (how strong the effect is). "
                "Use higher values for major drivers or near-decisive triggers, "
                "and lower values for weak contributing factors."
            ),
        },
        "confidence": {
            "type": "number",
            "description": (
                "Confidence 0.0-1.0 (how sure you are this edge is real and correctly specified). "
                "Confidence should reflect evidence quality, temporal fit, and mechanism clarity."
            ),
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
    output_type = "object"
    output_schema = pydantic_to_output_schema(HypothesisOutput)

    def __init__(
        self,
        collector: Optional[ResultCollector[CausalHypothesis]] = None,
        db_path: str = None,
        question_id: Optional[str] = None,
        alias_registry=None,
        staging: bool = False,
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
        self.alias_registry = alias_registry
        self.staging = staging

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
    ) -> HypothesisOutput:
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

        # Keep original alias input strings
        source_alias_input = source_event_id
        target_alias_input = target_event_id

        # Resolve aliases via AliasRegistry
        if getattr(self, "alias_registry", None):
            source_event_id = (
                self.alias_registry.resolve(source_event_id) or source_event_id
            )
            target_event_id = (
                self.alias_registry.resolve(target_event_id) or target_event_id
            )

        if self.db is not None:
            source_event = self.db.get(Event, source_event_id)
            if not source_event:
                return HypothesisOutput(
                    status="error",
                    hypothesis_id="error",
                    relation=f"{source_event_id} causes {target_event_id}",
                    strength=0.0,
                    confidence=0.0,
                    error=f"source_event_id '{source_event_id}' not found. Create it first with event_identifier.",
                )

            target_event = self.db.get(Event, target_event_id)
            if not target_event:
                return HypothesisOutput(
                    status="error",
                    hypothesis_id="error",
                    relation=f"{source_event_id} causes {target_event_id}",
                    strength=0.0,
                    confidence=0.0,
                    error=(
                        f"Target event '{target_event_id}' was not found. "
                        "Create the event first with event_identifier."
                    ),
                )

        # Validate and parse relation type
        try:
            relation = CausalRelationType(relation_type.lower())
        except ValueError:
            return HypothesisOutput(
                status="error",
                hypothesis_id="error",
                relation=f"{source_event_id} causes {target_event_id}",
                strength=0.0,
                confidence=0.0,
                error=f"Invalid relation_type '{relation_type}'. Valid: {[r.value for r in CausalRelationType]}",
            )

        # Parse evidence article IDs (resolve aliases like A1:BBCSanctions to real IDs)
        evidence_ids = []
        if evidence_article_ids:
            if getattr(self, "alias_registry", None):
                evidence_article_ids = self.alias_registry.resolve_article_ids(
                    evidence_article_ids
                )
            evidence_ids = [
                aid.strip() for aid in evidence_article_ids.split(",") if aid.strip()
            ]

        # Clamp strength and confidence to [0, 1]
        strength = max(0.0, min(1.0, float(strength)))
        confidence = max(0.0, min(1.0, float(confidence)))

        # Validate chronology - source must occur before target
        if not self._validate_chronology(source_event_id, target_event_id):
            source_date = self._get_event_occurred_date(source_event_id)
            target_date = self._get_event_occurred_date(target_event_id)
            return HypothesisOutput(
                status="error",
                hypothesis_id="error",
                relation=f"{source_event_id} causes {target_event_id}",
                strength=0.0,
                confidence=0.0,
                error=(
                    "Invalid chronology: cause must happen before effect "
                    f"(source={source_date}, target={target_date})."
                ),
            )

        # Validate DAG
        if not self._validate_dag(source_event_id, target_event_id):
            return HypothesisOutput(
                status="error",
                hypothesis_id="error",
                relation=f"{source_event_id} causes {target_event_id}",
                strength=0.0,
                confidence=0.0,
                error=f"Cycle detected: Adding this relation would create a causal loop. Target event '{target_event_id}' is already an ancestor of source event '{source_event_id}'.",
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

        # Check connectivity to actual outcome
        outcome_connected = False
        if self.db is not None:
            # Re-fetch target_event just in case (already fetched above)
            target_event_obj = self.db.get(Event, target_event_id)
            if target_event_obj and getattr(
                target_event_obj, "is_actual_outcome", False
            ):
                outcome_connected = True

        # Return HypothesisOutput Pydantic model
        return HypothesisOutput(
            status="recorded",
            hypothesis_id=hypothesis_id,
            source_alias=source_alias_input
            if source_alias_input != source_event_id
            else None,
            target_alias=target_alias_input
            if target_alias_input != target_event_id
            else None,
            relation=f"{source_event_id} {relation.value} {target_event_id}",
            strength=strength,
            confidence=confidence,
            outcome_connected=outcome_connected,
        )

    def _generate_hypothesis_id(self, question_id: str) -> HypothesisOutput:
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

    def _get_event_occurred_date(self, event_id: str) -> Optional[datetime]:
        """Get occurred date of an event from database.

        Args:
            event_id: ID of the event

        Returns:
            Occurred date of the event, or None if not found
        """
        if self.db is None:
            return None
        event = self.db.get(Event, event_id)
        return event.occurred_date or event.predicted_date

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

        source_date = self._get_event_occurred_date(source_event_id)
        target_date = self._get_event_occurred_date(target_event_id)

        # Cannot validate without dates - allow the hypothesis (can't disprove)
        if source_date is None or target_date is None:
            return True

        return source_date <= target_date

    def _validate_dag(self, source_event_id: str, target_event_id: str) -> bool:
        """Validate that adding this edge does not create a causal cycle.

        A cycle occurs if the target event is already an ancestor of the source event.
        Returns True if the DAG is valid (no cycle), False if a cycle is detected.
        """
        if self.db is None:
            return True  # Cannot validate without DB

        # Get all hypotheses to traverse the graph
        all_hypotheses = self.db.get_many(CausalHypothesis)

        # Build adjacency list for reverse graph (child -> parents)
        # We want to traverse upwards from source to see if we reach target
        parents = {}
        for h in all_hypotheses:
            if h.target_event_id not in parents:
                parents[h.target_event_id] = []
            parents[h.target_event_id].append(h.source_event_id)

        # BFS or DFS upwards from source_event_id
        visited = set()
        queue = [source_event_id]

        while queue:
            current = queue.pop(0)
            if current == target_event_id:
                return False  # Target is an ancestor of Source -> Cycle!

            if current not in visited:
                visited.add(current)
                if current in parents:
                    queue.extend(parents[current])

        return True
