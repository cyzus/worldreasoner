"""Causal graph building stage - validates and saves hypotheses to graph."""

from typing import List
from pydantic import BaseModel, Field

from src.pipelines.base import PipelineStage
from src.domain.models import Event, CausalHypothesis
from src.core.database import GenericDatabase
from src.utils.logging import logger


class CausalGraphConfig(BaseModel):
    """Configuration for causal graph building."""

    allow_cycles: bool = Field(
        default=False, description="Whether to allow causal cycles"
    )
    max_links_per_event: int = Field(default=10, description="Prevent graph bloat")
    validate_temporal_ordering: bool = Field(
        default=True, description="Ensure cause precedes effect"
    )


class CausalGraphBuildingStage(PipelineStage[CausalHypothesis, CausalHypothesis]):
    """Validates and saves causal hypotheses to the graph.

    This stage:
    1. Validates that source and target events exist
    2. Checks for duplicates and merges if found
    3. Validates temporal ordering and prevents cycles
    4. Saves CausalHypothesis objects directly to database

    Returns the saved/updated CausalHypothesis objects.
    """

    def __init__(self, config: CausalGraphConfig, db_path: str = "worldreasoner.db"):
        """Initialize causal graph building stage.

        Args:
            config: Graph building configuration
            db_path: Path to database
        """
        super().__init__(name="CausalGraphBuilding", config=config)
        self.db = GenericDatabase(db_path)

    async def process(self, inputs: List[CausalHypothesis]) -> List[CausalHypothesis]:
        """Validate and save causal hypotheses to graph.

        Args:
            inputs: List of causal hypotheses to add

        Returns:
            List of saved/updated CausalHypothesis objects
        """
        logger.info(f"Building causal graph from {len(inputs)} hypotheses")

        saved_hypotheses: List[CausalHypothesis] = []
        link_stats = {
            "added": 0,
            "merged": 0,
            "invalid_events": 0,
            "temporal_violation": 0,
            "max_links_exceeded": 0,
            "cycle_prevented": 0,
        }

        for idx, hypothesis in enumerate(inputs, 1):
            logger.debug(
                f"[{idx}/{len(inputs)}] Processing hypothesis {hypothesis.id}: "
                f"{hypothesis.source_event_id} -> {hypothesis.target_event_id}"
            )

            # Add hypothesis to graph
            result = self._add_hypothesis(hypothesis, saved_hypotheses)

            # Update stats
            if isinstance(result, str) and result in link_stats:
                link_stats[result] += 1

        # Log statistics
        logger.info(
            f"Graph building complete: "
            f"added={link_stats['added']}, "
            f"merged={link_stats['merged']}, "
            f"invalid={link_stats['invalid_events']}, "
            f"temporal={link_stats['temporal_violation']}, "
            f"max_links={link_stats['max_links_exceeded']}, "
            f"cycles={link_stats['cycle_prevented']}"
        )

        return saved_hypotheses

    def _add_hypothesis(
        self, hypothesis: CausalHypothesis, saved_hypotheses: List[CausalHypothesis]
    ) -> str:
        """Add a hypothesis to the graph or merge with existing.

        Args:
            hypothesis: Hypothesis to add
            saved_hypotheses: List of saved hypotheses (updated in-place)

        Returns:
            Status string: 'added', 'merged', 'invalid_events', etc.
        """
        # Validate source and target events exist
        source_event = self.db.get(Event, hypothesis.source_event_id)
        target_event = self.db.get(Event, hypothesis.target_event_id)

        if not source_event:
            logger.warning(f"Source event not found: {hypothesis.source_event_id}")
            return "invalid_events"

        if not target_event:
            # Debug: List all events in database to help diagnose
            all_events = self.db.get_many(Event, filters={})
            event_ids = [e.id for e in all_events]
            logger.warning(
                f"Target event not found: {hypothesis.target_event_id}\n"
                f"This should not happen. The event should have been created during target event identification.\n"
                f"Check if target_event_identification stage saved the event to the database.\n"
                f"Events in database ({len(all_events)} total): {event_ids[:10]}..."
            )
            return "invalid_events"

        # Check if hypothesis already exists in database
        existing_hypotheses = self.db.get_many(
            CausalHypothesis,
            filters={
                "source_event_id": hypothesis.source_event_id,
                "target_event_id": hypothesis.target_event_id,
            },
        )

        if existing_hypotheses:
            # Merge with existing - add to discovered_by_question_ids
            existing = existing_hypotheses[0]
            if hypothesis.discovered_by_question_ids:
                for qid in hypothesis.discovered_by_question_ids:
                    existing.add_discovery(qid)
            self.db.save(CausalHypothesis, existing)
            saved_hypotheses.append(existing)
            logger.debug(
                f"Merged with existing: {source_event.id} -> {target_event.id}"
            )
            return "merged"

        # Validate temporal ordering
        if self.config.validate_temporal_ordering:
            if not self._validate_temporal_order(source_event, target_event):
                logger.warning(
                    f"Temporal violation: {source_event.id} ({source_event.occurred_date}) "
                    f"-> {target_event.id} ({target_event.occurred_date})"
                )
                return "temporal_violation"

        # Check max links limit
        existing_outgoing = self.db.get_many(
            CausalHypothesis, filters={"source_event_id": hypothesis.source_event_id}
        )
        if len(existing_outgoing) >= self.config.max_links_per_event:
            logger.warning(
                f"Max links exceeded for {source_event.id} "
                f"({len(existing_outgoing)}/{self.config.max_links_per_event})"
            )
            return "max_links_exceeded"

        # Check for cycles (if not allowed)
        if not self.config.allow_cycles:
            if self._creates_cycle(
                hypothesis.source_event_id, hypothesis.target_event_id
            ):
                logger.warning(
                    f"Cycle prevented: {source_event.id} -> {target_event.id}"
                )
                return "cycle_prevented"

        # Save new hypothesis directly to database
        self.db.save(CausalHypothesis, hypothesis)
        saved_hypotheses.append(hypothesis)

        logger.debug(f"Added hypothesis: {source_event.id} -> {target_event.id}")
        return "added"

    def _validate_temporal_order(
        self, source_event: Event, target_event: Event
    ) -> bool:
        """Validate that cause precedes effect temporally.

        Args:
            source_event: Cause event
            target_event: Effect event

        Returns:
            True if temporal order is valid
        """
        # Get dates (prefer occurred_date, fall back to predicted_date)
        source_date = source_event.occurred_date or source_event.predicted_date
        target_date = target_event.occurred_date or target_event.predicted_date

        # If either date is missing, allow the link
        if not source_date or not target_date:
            return True

        # Ensure source precedes target (or is simultaneous)
        return source_date <= target_date

    def _creates_cycle(self, source_id: str, target_id: str) -> bool:
        """Check if adding this link would create a cycle.

        Uses depth-first search to check if target_id can reach source_id.

        Args:
            source_id: Source event ID
            target_id: Target event ID

        Returns:
            True if adding this link would create a cycle
        """
        # If target can reach source, adding source->target creates a cycle
        return self._can_reach(target_id, source_id, visited=set())

    def _can_reach(self, from_id: str, to_id: str, visited: set) -> bool:
        """Check if from_id can reach to_id via existing links.

        Args:
            from_id: Starting event ID
            to_id: Target event ID
            visited: Set of visited event IDs (for cycle detection)

        Returns:
            True if path exists
        """
        if from_id == to_id:
            return True

        if from_id in visited:
            return False

        visited.add(from_id)

        # Get all outgoing hypotheses from database
        outgoing_links = self.db.get_many(
            CausalHypothesis, filters={"source_event_id": from_id}
        )

        # Check each outgoing link
        for link in outgoing_links:
            if self._can_reach(link.target_event_id, to_id, visited):
                return True

        return False
