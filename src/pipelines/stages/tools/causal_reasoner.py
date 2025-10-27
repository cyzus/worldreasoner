"""Causal reasoner tool - LLM proposes causal explanations with hindsight."""

import json
from datetime import datetime, timezone
from typing import Optional

from smolagents import Tool
from src.domain.models import CausalHypothesis, CausalRelationType
from src.pipelines.stages.collectors import ResultCollector


class CausalReasonerTool(Tool):
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
    description = """Propose a causal explanation for an outcome with evidence.

    Use this tool AFTER analyzing evidence to record a causal relationship you identified.
    Call once for EACH causal link you identify (not all at once).

    Args:
        question_id (str): ID of the question being analyzed
        source_event_id (str): ID of the event that caused the outcome
        target_event_id (str): ID of the event that was caused (the outcome)
        relation_type (str): Type of causation (causes|enables|prevents|correlates|conditional)
        strength (float): Strength of causal effect (0.0-1.0)
        confidence (float): Your confidence in this link (0.0-1.0)
        reasoning (str): Detailed explanation of the causal mechanism
        evidence_article_ids (str): Comma-separated article IDs that support this claim

    Returns:
        str: JSON confirmation with hypothesis ID
    """

    inputs = {
        "question_id": {
            "type": "string",
            "description": "Question being analyzed"
        },
        "source_event_id": {
            "type": "string",
            "description": "Event ID of the cause"
        },
        "target_event_id": {
            "type": "string",
            "description": "Event ID of the effect (outcome)"
        },
        "relation_type": {
            "type": "string",
            "description": "Type of causation: causes, enables, prevents, correlates, or conditional"
        },
        "strength": {
            "type": "number",
            "description": "Causal strength 0.0-1.0 (how strong the effect)"
        },
        "confidence": {
            "type": "number",
            "description": "Confidence 0.0-1.0 (how sure you are)"
        },
        "reasoning": {
            "type": "string",
            "description": "Detailed explanation of the causal mechanism"
        },
        "evidence_article_ids": {
            "type": "string",
            "description": "Comma-separated article IDs supporting this claim"
        },
    }
    output_type = "string"  # JSON confirmation

    def __init__(self, collector: Optional[ResultCollector[CausalHypothesis]] = None):
        """Initialize the causal reasoner tool.

        Args:
            collector: Optional ResultCollector for storing hypotheses
        """
        super().__init__()
        self.collector = collector
        self.hypotheses = []  # Fallback for backward compatibility
        self._counter = 0  # For generating hypothesis IDs

    def forward(
        self,
        question_id: str,
        source_event_id: str,
        target_event_id: str,
        relation_type: str,
        strength: float,
        confidence: float,
        reasoning: str,
        evidence_article_ids: str,
    ) -> str:
        """Record a causal hypothesis with supporting evidence.

        Args:
            question_id: Question being analyzed
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
        # Validate and parse relation type
        try:
            relation = CausalRelationType(relation_type.lower())
        except ValueError:
            # Default to CAUSES if invalid
            relation = CausalRelationType.CAUSES

        # Parse evidence article IDs
        evidence_ids = []
        if evidence_article_ids:
            evidence_ids = [aid.strip() for aid in evidence_article_ids.split(',') if aid.strip()]

        # Clamp strength and confidence to [0, 1]
        strength = max(0.0, min(1.0, float(strength)))
        confidence = max(0.0, min(1.0, float(confidence)))

        # Generate unique hypothesis ID
        hypothesis_id = self._generate_hypothesis_id(question_id)

        # Create CausalHypothesis object
        hypothesis = CausalHypothesis(
            id=hypothesis_id,
            question_id=question_id,
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            relation_type=relation,
            strength=strength,
            confidence=confidence,
            reasoning=reasoning,
            evidence_article_ids=evidence_ids,
            identified_by="evidence_pipeline",
            identified_at=datetime.now(timezone.utc),
            validated=False,
        )

        # Store hypothesis
        # CRITICAL: Use 'is not None' check (ResultCollector.__bool__ returns False when empty)
        if self.collector is not None:
            self.collector.add(hypothesis)
        else:
            # Fallback for backward compatibility
            self.hypotheses.append(hypothesis)

        # Return confirmation (minimal to save tokens)
        confirmation = {
            "status": "recorded",
            "hypothesis_id": hypothesis_id,
            "relation": f"{source_event_id} {relation.value} {target_event_id}",
            "strength": strength,
            "confidence": confidence,
            "evidence_count": len(evidence_ids),
        }

        return json.dumps(confirmation, indent=2)

    def _generate_hypothesis_id(self, question_id: str) -> str:
        """Generate unique hypothesis ID.

        Args:
            question_id: Question this hypothesis relates to

        Returns:
            Unique hypothesis ID
        """
        self._counter += 1
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        return f"hyp_{question_id}_{timestamp}_{self._counter:03d}"
