"""SQLite-backed graph service implementation.

This implementation loads graph data from the WorldReasoner SQLite database
and converts it to the standardized graph format. It's optimized for graphs
with <10k nodes and provides in-memory caching for performance.
"""

from typing import List, Optional, Dict, Any, Set
from datetime import datetime
from collections import deque

from src.core.database import GenericDatabase
from src.domain.models import Event, CausalHypothesis
from src.domain.models.article import Article
from src.domain.models.event_outcome_impact import EventOutcomeImpact
from src.utils.logging import logger
from .interface import (
    GraphService,
    GraphQuery,
    GraphNode,
    GraphEdge,
    GraphData,
)


class SQLiteGraphService(GraphService):
    """SQLite-backed implementation of GraphService.

    This implementation:
    1. Loads Events and Articles from SQLite
    2. Converts to standardized graph format
    3. Supports filtering and traversal
    4. Uses in-memory caching for performance
    5. Can be swapped for graph DB in the future
    """

    def __init__(self, db_path: str = "worldreasoner.db"):
        """Initialize SQLite graph service.

        Args:
            db_path: Path to SQLite database
        """
        self.db = GenericDatabase(db_path)
        self._subscribers: List[callable] = []
        self._hypotheses_cache: Optional[List[CausalHypothesis]] = None

    async def get_graph(self, query: Optional[GraphQuery] = None) -> GraphData:
        """Retrieve graph data from SQLite.

        This method:
        1. Loads Events from database
        2. Optionally filters by query parameters
        3. Converts to GraphNode and GraphEdge format
        4. Returns standardized GraphData

        Args:
            query: Optional query to filter/constrain the graph

        Returns:
            GraphData with nodes and edges
        """
        query = query or GraphQuery()

        # Load events from database
        events = self._load_events(query)

        # If center node specified, do neighborhood search
        if query.center_node_id:
            events = self._filter_by_neighborhood(
                events, query.center_node_id, query.max_depth or 1
            )

        # Apply node limits
        if query.max_nodes:
            events = events[: query.max_nodes]

        # Convert to graph format
        nodes = self._events_to_nodes(events)
        edges = self._get_causal_edges([e.id for e in events], query)

        # Optionally include outcome impact edges
        if query.include_outcomes:
            impact_edges = await self.get_impact_edges(
                min_confidence=query.min_edge_weight
            )
            # Filter to only include impacts where both nodes exist in graph
            event_ids_set = {e.id for e in events}
            impact_edges = [
                edge
                for edge in impact_edges
                if edge.source_id in event_ids_set and edge.target_id in event_ids_set
            ]
            edges.extend(impact_edges)

        # Apply edge limits
        if query.max_edges and len(edges) > query.max_edges:
            edges = edges[: query.max_edges]

        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata={
                "total_events": len(events),
                "total_links": len(edges),
                "generated_at": datetime.now().isoformat(),
            },
        )

    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a single event node by ID.

        Args:
            node_id: Event ID

        Returns:
            GraphNode if found, None otherwise
        """
        event = self.db.get(Event, node_id)
        if not event:
            return None

        return self._event_to_node(event)

    async def get_neighborhood(
        self, node_id: str, max_depth: int = 1, direction: str = "both"
    ) -> GraphData:
        """Get the neighborhood around an event node.

        Uses BFS to traverse causal links.

        Args:
            node_id: Center event ID
            max_depth: Maximum traversal depth
            direction: "incoming", "outgoing", or "both"

        Returns:
            GraphData containing neighborhood
        """
        # Load all events for traversal
        all_events = self.db.get_many(Event, filters={})
        event_map = {e.id: e for e in all_events}

        # BFS to find neighborhood
        neighborhood_ids = self._bfs_neighborhood(
            node_id, event_map, max_depth, direction
        )

        # Get events in neighborhood
        neighborhood_events = [
            event_map[eid] for eid in neighborhood_ids if eid in event_map
        ]

        # Convert to graph format
        nodes = self._events_to_nodes(neighborhood_events)
        edges = self._events_to_edges(neighborhood_events)

        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata={
                "center_node_id": node_id,
                "max_depth": max_depth,
                "direction": direction,
            },
        )

    async def find_paths(
        self, source_id: str, target_id: str, max_depth: int = 5
    ) -> List[List[str]]:
        """Find causal paths between two events.

        Uses BFS to find shortest paths first.

        Args:
            source_id: Starting event ID
            target_id: Ending event ID
            max_depth: Maximum path length

        Returns:
            List of paths (each path is a list of event IDs)
        """
        # Load all events
        all_events = self.db.get_many(Event, filters={})
        event_map = {e.id: e for e in all_events}

        if source_id not in event_map or target_id not in event_map:
            return []

        # BFS for paths
        paths = []
        queue = deque([(source_id, [source_id])])
        visited_paths = set()

        while queue:
            current_id, path = queue.popleft()

            # Check depth limit
            if len(path) > max_depth:
                continue

            # Found target
            if current_id == target_id:
                paths.append(path)
                continue

            # Get current event
            current_event = event_map.get(current_id)
            if not current_event:
                continue

            # Explore outgoing links using causal hypotheses
            outgoing_hyps = self._get_outgoing_hypotheses(current_id)
            for hypothesis in outgoing_hyps:
                next_id = hypothesis.target_event_id

                # Avoid revisiting in this path
                if next_id in path:
                    continue

                # Track path to avoid duplicates
                path_key = tuple(path + [next_id])
                if path_key in visited_paths:
                    continue

                visited_paths.add(path_key)
                queue.append((next_id, path + [next_id]))

        return paths

    async def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics from database.

        Returns:
            Dictionary with graph statistics
        """
        events = self.db.get_many(Event, filters={})
        hypotheses = self._get_hypotheses()

        try:
            self.db.create_table(Article)
            total_articles = len(self.db.get_many(Article))
        except Exception:
            total_articles = 0

        # Count hypotheses by type
        edge_type_counts = {}
        for h in hypotheses:
            relation = (
                h.relation_type.value
                if hasattr(h.relation_type, "value")
                else str(h.relation_type)
            )
            edge_type_counts[relation] = edge_type_counts.get(relation, 0) + 1

        # Count nodes by domain
        node_types = {}
        for e in events:
            domain = e.domain or "unknown"
            node_types[domain] = node_types.get(domain, 0) + 1

        # Count hypotheses by discovery count
        single_discovery = sum(
            1 for h in hypotheses if len(h.discovered_by_question_ids) == 1
        )
        multi_discovery = sum(
            1 for h in hypotheses if len(h.discovered_by_question_ids) > 1
        )

        return {
            "total_nodes": len(events),
            "total_edges": len(hypotheses),
            "total_articles": total_articles,
            "node_type_counts": node_types,
            "edge_type_counts": edge_type_counts,
            "average_out_degree": len(hypotheses) / len(events) if events else 0,
            "single_discovery_edges": single_discovery,
            "multi_discovery_edges": multi_discovery,
        }

    async def get_outcome_events(self, question_id: str) -> List[GraphNode]:
        """Get outcome events for a specific question.

        Args:
            question_id: Question ID to get outcomes for

        Returns:
            List of GraphNodes representing outcome events
        """
        # Query events where is_outcome=True and extracted_for_question_id matches
        all_events = self.db.get_many(Event, filters={})
        outcome_events = [
            e
            for e in all_events
            if e.is_outcome and e.extracted_for_question_id == question_id
        ]

        return self._events_to_nodes(outcome_events)

    async def get_impact_edges(
        self,
        outcome_event_id: Optional[str] = None,
        event_id: Optional[str] = None,
        min_confidence: Optional[float] = None,
        impact_direction: Optional[str] = None,
    ) -> List[GraphEdge]:
        """Get impact edges with optional filtering.

        Args:
            outcome_event_id: Filter impacts to this outcome event
            event_id: Filter impacts from this event
            min_confidence: Minimum confidence threshold
            impact_direction: Filter by impact direction (positive, negative, etc.)

        Returns:
            List of GraphEdges representing impact relationships
        """
        # Fetch all event outcome impacts
        all_impacts = self.db.get_many(EventOutcomeImpact, filters={})

        # Apply filters
        filtered_impacts = []
        for impact in all_impacts:
            # Filter by outcome event
            if outcome_event_id and impact.outcome_event_id != outcome_event_id:
                continue

            # Filter by source event
            if event_id and impact.event_id != event_id:
                continue

            # Filter by confidence
            if min_confidence is not None and impact.confidence < min_confidence:
                continue

            # Filter by direction
            if impact_direction:
                current_direction = (
                    impact.impact_direction.value
                    if hasattr(impact.impact_direction, "value")
                    else str(impact.impact_direction)
                )
                if current_direction != impact_direction:
                    continue

            filtered_impacts.append(impact)

        # Convert impacts to graph edges
        edges = []
        for impact in filtered_impacts:
            direction_val = (
                impact.impact_direction.value
                if hasattr(impact.impact_direction, "value")
                else str(impact.impact_direction)
            )
            edge_type = f"impact_{direction_val}"

            edges.append(
                GraphEdge(
                    source_id=impact.event_id,
                    target_id=impact.outcome_event_id,
                    edge_type=edge_type,
                    properties={
                        "impact_direction": impact.impact_direction.value,
                        "impact_magnitude": impact.impact_magnitude,
                        "confidence": impact.confidence,
                        "reasoning": impact.reasoning,
                        "evidence_article_ids": impact.evidence_article_ids,
                        "evidence_count": len(impact.evidence_article_ids),
                        "causal_chain_hypothesis_ids": impact.causal_chain_hypothesis_ids,
                        "discovered_by_question_ids": impact.discovered_by_question_ids,
                        "identified_by": impact.identified_by,
                        "first_identified_at": impact.first_identified_at.isoformat()
                        if impact.first_identified_at
                        else None,
                        "last_confirmed_at": impact.last_confirmed_at.isoformat()
                        if impact.last_confirmed_at
                        else None,
                    },
                    weight=impact.impact_magnitude,
                    label=f"{direction_val} impact",
                )
            )

        return edges

    async def subscribe_to_updates(self, callback) -> None:
        """Subscribe to graph updates.

        Note: SQLite backend doesn't support real-time updates.
        This is a placeholder for future graph DB implementations.

        Args:
            callback: Async function called when graph changes
        """
        self._subscribers.append(callback)
        logger.debug(f"Added subscriber (total: {len(self._subscribers)})")

    async def close(self) -> None:
        """Clean up resources."""
        self._subscribers.clear()

    # Private helper methods

    def _load_events(self, query: GraphQuery) -> List[Event]:
        """Load events from database with optional filtering.

        Args:
            query: Query parameters

        Returns:
            List of filtered events
        """
        filters = {}

        # Load all events
        events = self.db.get_many(Event, filters=filters)

        # Apply temporal filtering
        if query.start_date or query.end_date:
            events = [
                e
                for e in events
                if self._in_time_range(e, query.start_date, query.end_date)
            ]

        # Apply node ID filtering
        if query.node_ids is not None:
            node_id_set = set(query.node_ids)
            events = [e for e in events if e.id in node_id_set]

        # Apply node type filtering (by domain)
        if query.node_types is not None:
            events = [e for e in events if e.domain in query.node_types]

        if query.exclude_node_types is not None:
            events = [e for e in events if e.domain not in query.exclude_node_types]

        return events

    def _filter_by_neighborhood(
        self, events: List[Event], center_id: str, max_depth: int
    ) -> List[Event]:
        """Filter events to only those in neighborhood of center node.

        Args:
            events: All events
            center_id: Center node ID
            max_depth: Maximum depth

        Returns:
            Filtered events in neighborhood
        """
        event_map = {e.id: e for e in events}
        neighborhood_ids = self._bfs_neighborhood(
            center_id, event_map, max_depth, "both"
        )

        return [e for e in events if e.id in neighborhood_ids]

    def _bfs_neighborhood(
        self, start_id: str, event_map: Dict[str, Event], max_depth: int, direction: str
    ) -> Set[str]:
        """BFS to find neighborhood nodes.

        Args:
            start_id: Starting node ID
            event_map: Map of event ID to Event
            max_depth: Maximum depth
            direction: "incoming", "outgoing", or "both"

        Returns:
            Set of event IDs in neighborhood
        """
        visited = {start_id}
        queue = deque([(start_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            current_event = event_map.get(current_id)
            if not current_event:
                continue

            # Outgoing edges (this event causes others)
            if direction in ("outgoing", "both"):
                outgoing_hyps = self._get_outgoing_hypotheses(current_id)
                for hypothesis in outgoing_hyps:
                    target_id = hypothesis.target_event_id
                    if target_id not in visited and target_id in event_map:
                        visited.add(target_id)
                        queue.append((target_id, depth + 1))

            # Incoming edges (this event is caused by others)
            if direction in ("incoming", "both"):
                incoming_hyps = self._get_incoming_hypotheses(current_id)
                for hypothesis in incoming_hyps:
                    source_id = hypothesis.source_event_id
                    if source_id not in visited and source_id in event_map:
                        visited.add(source_id)
                        queue.append((source_id, depth + 1))

        return visited

    def _events_to_nodes(self, events: List[Event]) -> List[GraphNode]:
        """Convert events to graph nodes.

        Args:
            events: List of events

        Returns:
            List of graph nodes
        """
        return [self._event_to_node(e) for e in events]

    def _event_to_node(self, event: Event) -> GraphNode:
        """Convert single event to graph node.

        Args:
            event: Event to convert

        Returns:
            GraphNode
        """
        return GraphNode(
            id=event.id,
            label=event.title,
            node_type="event",
            properties={
                "domain": event.domain or "unknown",
                "description": event.description,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
                "predicted_date": event.predicted_date.isoformat()
                if event.predicted_date
                else None,
                "event_type": event.event_type.value if event.event_type else None,
                "status": event.status.value if event.status else None,
                "importance": getattr(event, "importance", 1.0),
                "is_outcome": getattr(event, "is_outcome", False),
                "outcome_scenario": getattr(event, "outcome_scenario", None),
                "is_actual_outcome": getattr(event, "is_actual_outcome", False),
                "extracted_for_question_id": getattr(
                    event, "extracted_for_question_id", None
                ),
                "article_ids": getattr(event, "article_ids", []),
                "source_article_id": getattr(event, "source_article_id", None),
                "review_status": getattr(event.review_status, "value", str(event.review_status)) if getattr(event, "review_status", None) else "pending",
                "review_note": getattr(event, "review_note", None),
            },
            size=getattr(event, "importance", 1.0),
            color=self._domain_to_color(event.domain),
        )

    def _get_causal_edges(
        self, event_ids: List[str], query: Optional[GraphQuery] = None
    ) -> List[GraphEdge]:
        """Get causal edges from causal_hypotheses table.

        This reads from the causal_hypotheses table which is the source of truth
        for all causal relationships. Each hypothesis contains:
        - The causal link (source -> target)
        - Evidence metadata (confidence, strength, reasoning)
        - Supporting articles (evidence_article_ids)
        - Validation status

        Args:
            event_ids: List of event IDs to include in the graph
            query: Optional query for edge filtering

        Returns:
            List of graph edges
        """
        edges = []
        event_ids_set = set(event_ids)

        # Fetch all causal hypotheses from database
        hypotheses = self.db.get_many(CausalHypothesis, filters={})

        for hypothesis in hypotheses:
            # Only include edges where both nodes are in the graph
            if hypothesis.source_event_id not in event_ids_set:
                continue
            if hypothesis.target_event_id not in event_ids_set:
                continue

            # Apply edge type filtering
            if query and query.edge_types is not None:
                if hypothesis.relation_type not in query.edge_types:
                    continue

            # Apply weight filtering
            if query and query.min_edge_weight:
                if hypothesis.strength < query.min_edge_weight:
                    continue

            # Create edge from hypothesis
            edges.append(
                GraphEdge(
                    source_id=hypothesis.source_event_id,
                    target_id=hypothesis.target_event_id,
                    edge_type=hypothesis.relation_type,
                    properties={
                        "strength": hypothesis.strength,
                        "confidence": hypothesis.confidence,
                        "reasoning": hypothesis.reasoning,
                        "evidence_article_ids": hypothesis.evidence_article_ids,
                        "evidence_count": len(hypothesis.evidence_article_ids),
                        "discovered_by_question_ids": hypothesis.discovered_by_question_ids,
                        "discovery_count": len(hypothesis.discovered_by_question_ids),
                        "identified_by": hypothesis.identified_by,
                        "first_identified_at": hypothesis.first_identified_at.isoformat()
                        if hypothesis.first_identified_at
                        else None,
                        "last_confirmed_at": hypothesis.last_confirmed_at.isoformat()
                        if hypothesis.last_confirmed_at
                        else None,
                    },
                    weight=hypothesis.strength,
                    label=hypothesis.relation_type,
                )
            )

        return edges

    def _get_hypotheses(self) -> List[CausalHypothesis]:
        """Get all causal hypotheses with caching.

        Returns:
            List of all causal hypotheses
        """
        if self._hypotheses_cache is None:
            self._hypotheses_cache = self.db.get_many(CausalHypothesis, filters={})
        return self._hypotheses_cache

    def _get_outgoing_hypotheses(self, event_id: str) -> List[CausalHypothesis]:
        """Get causal hypotheses where event is the source.

        Args:
            event_id: Source event ID

        Returns:
            List of hypotheses where this event is the cause
        """
        all_hypotheses = self._get_hypotheses()
        return [h for h in all_hypotheses if h.source_event_id == event_id]

    def _get_incoming_hypotheses(self, event_id: str) -> List[CausalHypothesis]:
        """Get causal hypotheses where event is the target.

        Args:
            event_id: Target event ID

        Returns:
            List of hypotheses where this event is the effect
        """
        all_hypotheses = self._get_hypotheses()
        return [h for h in all_hypotheses if h.target_event_id == event_id]

    def _in_time_range(
        self, event: Event, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> bool:
        """Check if event is in time range.

        Args:
            event: Event to check
            start_date: Start of range
            end_date: End of range

        Returns:
            True if in range
        """
        event_date = event.occurred_date or event.predicted_date
        if not event_date:
            return True

        if start_date and event_date < start_date:
            return False

        if end_date and event_date > end_date:
            return False

        return True

    def _domain_to_color(self, domain: Optional[str]) -> str:
        """Map domain to color for visualization.

        Args:
            domain: Event domain

        Returns:
            Color string
        """
        color_map = {
            "politics": "#ef4444",  # Red
            "economics": "#3b82f6",  # Blue
            "technology": "#8b5cf6",  # Purple
            "science": "#06b6d4",  # Cyan
            "climate": "#10b981",  # Green
            "health": "#f59e0b",  # Amber
            "finance": "#3b82f6",  # Blue
            "tech": "#8b5cf6",  # Purple
        }
        return color_map.get(domain or "unknown", "#6366f1")  # Indigo default
