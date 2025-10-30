"""SQLite-backed graph service implementation.

This implementation loads graph data from the WorldReasoner SQLite database
and converts it to the standardized graph format. It's optimized for graphs
with <10k nodes and provides in-memory caching for performance.
"""

from typing import List, Optional, Dict, Any, Set
from datetime import datetime
from collections import deque

from src.core.database import GenericDatabase
from src.domain.models import Event, Article
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
                events,
                query.center_node_id,
                query.max_depth or 1
            )

        # Apply node limits
        if query.max_nodes:
            events = events[:query.max_nodes]

        # Convert to graph format
        nodes = self._events_to_nodes(events)
        edges = self._events_to_edges(events, query)

        # Apply edge limits
        if query.max_edges and len(edges) > query.max_edges:
            edges = edges[:query.max_edges]

        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata={
                "total_events": len(events),
                "total_links": len(edges),
                "generated_at": datetime.now().isoformat(),
            }
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
        self,
        node_id: str,
        max_depth: int = 1,
        direction: str = "both"
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
            node_id,
            event_map,
            max_depth,
            direction
        )

        # Get events in neighborhood
        neighborhood_events = [
            event_map[eid] for eid in neighborhood_ids
            if eid in event_map
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
            }
        )

    async def find_paths(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5
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

            # Explore outgoing links
            for link in current_event.causes:
                next_id = link.target_event_id

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

        total_links = sum(len(e.causes) for e in events)
        node_types = {}
        for e in events:
            domain = e.domain or "unknown"
            node_types[domain] = node_types.get(domain, 0) + 1

        return {
            "total_nodes": len(events),
            "total_edges": total_links,
            "node_type_counts": node_types,
            "edge_type_counts": {"causal": total_links},
            "average_out_degree": total_links / len(events) if events else 0,
        }

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
                e for e in events
                if self._in_time_range(e, query.start_date, query.end_date)
            ]

        # Apply node ID filtering
        if query.node_ids:
            node_id_set = set(query.node_ids)
            events = [e for e in events if e.id in node_id_set]

        # Apply node type filtering (by domain)
        if query.node_types:
            events = [e for e in events if e.domain in query.node_types]

        if query.exclude_node_types:
            events = [e for e in events if e.domain not in query.exclude_node_types]

        return events

    def _filter_by_neighborhood(
        self,
        events: List[Event],
        center_id: str,
        max_depth: int
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
            center_id,
            event_map,
            max_depth,
            "both"
        )

        return [e for e in events if e.id in neighborhood_ids]

    def _bfs_neighborhood(
        self,
        start_id: str,
        event_map: Dict[str, Event],
        max_depth: int,
        direction: str
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

            # Outgoing edges
            if direction in ("outgoing", "both"):
                for link in current_event.causes:
                    target_id = link.target_event_id
                    if target_id not in visited and target_id in event_map:
                        visited.add(target_id)
                        queue.append((target_id, depth + 1))

            # Incoming edges
            if direction in ("incoming", "both"):
                for source_id in current_event.caused_by_ids:
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
            node_type=event.domain or "unknown",
            properties={
                "description": event.description,
                "occurred_date": event.occurred_date.isoformat() if event.occurred_date else None,
                "predicted_date": event.predicted_date.isoformat() if event.predicted_date else None,
                "event_type": event.event_type.value if event.event_type else None,
                "status": event.status.value if event.status else None,
                "importance": getattr(event, 'importance', 1.0),
                "num_causes": len(event.causes),
                "num_caused_by": len(event.caused_by_ids),
            },
            size=getattr(event, 'importance', 1.0),
            color=self._domain_to_color(event.domain),
        )

    def _events_to_edges(
        self,
        events: List[Event],
        query: Optional[GraphQuery] = None
    ) -> List[GraphEdge]:
        """Convert event causal links to graph edges.

        Args:
            events: List of events
            query: Optional query for edge filtering

        Returns:
            List of graph edges
        """
        edges = []
        event_ids = {e.id for e in events}

        for event in events:
            for link in event.causes:
                # Only include edges where both nodes are in the graph
                if link.target_event_id not in event_ids:
                    continue

                # Apply edge type filtering
                if query and query.edge_types:
                    if link.relation_type not in query.edge_types:
                        continue

                # Apply weight filtering
                if query and query.min_edge_weight:
                    if link.strength < query.min_edge_weight:
                        continue

                edges.append(GraphEdge(
                    source_id=event.id,
                    target_id=link.target_event_id,
                    edge_type=link.relation_type,
                    properties={
                        "strength": link.strength,
                        "confidence": link.confidence,
                        "reasoning": link.reasoning,
                        "evidence_count": len(link.evidence_article_ids),
                    },
                    weight=link.strength,
                    label=link.relation_type,
                ))

        return edges

    def _in_time_range(
        self,
        event: Event,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
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
            "politics": "#ef4444",      # Red
            "economics": "#3b82f6",     # Blue
            "technology": "#8b5cf6",    # Purple
            "science": "#06b6d4",       # Cyan
            "climate": "#10b981",       # Green
            "health": "#f59e0b",        # Amber
            "finance": "#3b82f6",       # Blue
            "tech": "#8b5cf6",          # Purple
        }
        return color_map.get(domain or "unknown", "#6366f1")  # Indigo default
