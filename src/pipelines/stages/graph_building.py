"""Causal graph building stage - converts hypotheses to permanent links."""

from typing import List, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.pipelines.base import PipelineStage
from src.domain.models import Event, CausalHypothesis, CausalLink
from src.core.database import GenericDatabase
from src.utils.logging import logger


class CausalGraphConfig(BaseModel):
    """Configuration for causal graph building."""

    allow_cycles: bool = Field(
        default=False,
        description="Whether to allow causal cycles"
    )
    max_links_per_event: int = Field(
        default=10,
        description="Prevent graph bloat"
    )
    validate_temporal_ordering: bool = Field(
        default=True,
        description="Ensure cause precedes effect"
    )


class CausalGraphBuildingStage(PipelineStage[CausalHypothesis, Event]):
    """Builds causal graph by adding validated links to events.

    This stage:
    1. Loads existing events from database
    2. Converts CausalHypothesis objects to CausalLink objects
    3. Adds links to source event's `causes` list
    4. Updates target event's `caused_by_ids` list
    5. Validates temporal ordering and prevents cycles
    6. Recomputes event importance scores

    Returns only the modified events that need to be persisted.
    """

    def __init__(
        self,
        config: CausalGraphConfig,
        db_path: str = "worldreasoner.db"
    ):
        """Initialize causal graph building stage.

        Args:
            config: Graph building configuration
            db_path: Path to database
        """
        super().__init__(name="CausalGraphBuilding", config=config)
        self.db = GenericDatabase(db_path)

    async def process(self, inputs: List[CausalHypothesis]) -> List[Event]:
        """Convert hypotheses to causal links in event graph.

        Args:
            inputs: List of validated causal hypotheses

        Returns:
            List of events that were modified (need to be re-saved)
        """
        logger.info(f"Building causal graph from {len(inputs)} hypotheses")

        modified_events: Dict[str, Event] = {}  # event_id -> Event
        link_stats = {
            'added': 0,
            'duplicate': 0,
            'invalid_events': 0,
            'temporal_violation': 0,
            'max_links_exceeded': 0,
            'cycle_prevented': 0,
        }

        for idx, hypothesis in enumerate(inputs, 1):
            logger.debug(
                f"[{idx}/{len(inputs)}] Processing hypothesis {hypothesis.id}: "
                f"{hypothesis.source_event_id} -> {hypothesis.target_event_id}"
            )

            # Add link to graph
            result = self._add_causal_link(hypothesis, modified_events)

            # Update stats
            if result in link_stats:
                link_stats[result] += 1

        # Recompute importance scores for modified events
        for event in modified_events.values():
            event.compute_importance()

        # Mark hypotheses as validated
        for hypothesis in inputs:
            if self._hypothesis_was_added(hypothesis, modified_events):
                hypothesis.mark_validated(notes="Added to causal graph")

        # Log statistics
        logger.info(
            f"Graph building complete: "
            f"added={link_stats['added']}, "
            f"duplicate={link_stats['duplicate']}, "
            f"invalid={link_stats['invalid_events']}, "
            f"temporal={link_stats['temporal_violation']}, "
            f"max_links={link_stats['max_links_exceeded']}, "
            f"cycles={link_stats['cycle_prevented']}"
        )

        return list(modified_events.values())

    def _add_causal_link(
        self,
        hypothesis: CausalHypothesis,
        modified_events: Dict[str, Event]
    ) -> str:
        """Add a causal link to the graph.

        Args:
            hypothesis: Hypothesis to add
            modified_events: Dict of modified events (updated in-place)

        Returns:
            Status string: 'added', 'duplicate', 'invalid_events', etc.
        """
        # Load source and target events (from cache or database)
        source_event = self._get_event(hypothesis.source_event_id, modified_events)
        target_event = self._get_event(hypothesis.target_event_id, modified_events)

        if not source_event:
            logger.warning(f"Source event not found: {hypothesis.source_event_id}")
            return 'invalid_events'

        if not target_event:
            logger.warning(f"Target event not found: {hypothesis.target_event_id}")
            return 'invalid_events'

        # Check if link already exists
        if self._link_exists(source_event, hypothesis.target_event_id):
            logger.debug(
                f"Link already exists: {source_event.id} -> {target_event.id}"
            )
            return 'duplicate'

        # Validate temporal ordering
        if self.config.validate_temporal_ordering:
            if not self._validate_temporal_order(source_event, target_event):
                logger.warning(
                    f"Temporal violation: {source_event.id} ({source_event.occurred_date}) "
                    f"-> {target_event.id} ({target_event.occurred_date})"
                )
                return 'temporal_violation'

        # Check max links limit
        if len(source_event.causes) >= self.config.max_links_per_event:
            logger.warning(
                f"Max links exceeded for {source_event.id} "
                f"({len(source_event.causes)}/{self.config.max_links_per_event})"
            )
            return 'max_links_exceeded'

        # Check for cycles (if not allowed)
        if not self.config.allow_cycles:
            if self._creates_cycle(source_event.id, target_event.id, modified_events):
                logger.warning(
                    f"Cycle prevented: {source_event.id} -> {target_event.id}"
                )
                return 'cycle_prevented'

        # Create causal link
        link = CausalLink(
            source_event_id=hypothesis.source_event_id,
            target_event_id=hypothesis.target_event_id,
            relation_type=hypothesis.relation_type,
            strength=hypothesis.strength,
            confidence=hypothesis.confidence,
            reasoning=hypothesis.reasoning,
            evidence_article_ids=hypothesis.evidence_article_ids
        )

        # Add link to source event
        source_event.causes.append(link)
        modified_events[source_event.id] = source_event

        # Add to target event's incoming links
        if source_event.id not in target_event.caused_by_ids:
            target_event.caused_by_ids.append(source_event.id)
            modified_events[target_event.id] = target_event

        # Update event timestamps
        source_event.updated_at = datetime.now(timezone.utc)
        target_event.updated_at = datetime.now(timezone.utc)

        logger.debug(f"Added link: {source_event.id} -> {target_event.id}")
        return 'added'

    def _get_event(
        self,
        event_id: str,
        modified_events: Dict[str, Event]
    ) -> Optional[Event]:
        """Get event from cache or database.

        Args:
            event_id: Event ID to retrieve
            modified_events: Cache of modified events

        Returns:
            Event object or None if not found
        """
        # Check cache first
        if event_id in modified_events:
            return modified_events[event_id]

        # Load from database
        event = self.db.get(Event, event_id)
        return event

    def _link_exists(self, source_event: Event, target_event_id: str) -> bool:
        """Check if a causal link already exists.

        Args:
            source_event: Source event
            target_event_id: Target event ID

        Returns:
            True if link exists
        """
        return any(
            link.target_event_id == target_event_id
            for link in source_event.causes
        )

    def _validate_temporal_order(
        self,
        source_event: Event,
        target_event: Event
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

    def _creates_cycle(
        self,
        source_id: str,
        target_id: str,
        modified_events: Dict[str, Event]
    ) -> bool:
        """Check if adding this link would create a cycle.

        Uses depth-first search to check if target_id can reach source_id.

        Args:
            source_id: Source event ID
            target_id: Target event ID
            modified_events: Cache of modified events

        Returns:
            True if adding this link would create a cycle
        """
        # If target can reach source, adding source->target creates a cycle
        return self._can_reach(target_id, source_id, modified_events, visited=set())

    def _can_reach(
        self,
        from_id: str,
        to_id: str,
        modified_events: Dict[str, Event],
        visited: set
    ) -> bool:
        """Check if from_id can reach to_id via existing links.

        Args:
            from_id: Starting event ID
            to_id: Target event ID
            modified_events: Cache of modified events
            visited: Set of visited event IDs (for cycle detection)

        Returns:
            True if path exists
        """
        if from_id == to_id:
            return True

        if from_id in visited:
            return False

        visited.add(from_id)

        # Get from event
        from_event = self._get_event(from_id, modified_events)
        if not from_event:
            return False

        # Check each outgoing link
        for link in from_event.causes:
            if self._can_reach(link.target_event_id, to_id, modified_events, visited):
                return True

        return False

    def _hypothesis_was_added(
        self,
        hypothesis: CausalHypothesis,
        modified_events: Dict[str, Event]
    ) -> bool:
        """Check if a hypothesis was successfully added to the graph.

        Args:
            hypothesis: Hypothesis to check
            modified_events: Modified events

        Returns:
            True if hypothesis was added
        """
        source_event = modified_events.get(hypothesis.source_event_id)
        if not source_event:
            return False

        return any(
            link.target_event_id == hypothesis.target_event_id
            and link.relation_type == hypothesis.relation_type
            for link in source_event.causes
        )
