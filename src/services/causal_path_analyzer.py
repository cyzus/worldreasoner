"""Causal path analysis service.

Analyzes causal paths from events to target events, tracking chain completion
and event status for forecasting visualization.
"""

from typing import List, Dict, Optional, Set, Tuple, Any
from collections import deque

from src.core.database import GenericDatabase
from src.domain.models import Event, CausalHypothesis
from src.domain.models.event import EventStatus, CausalRelationType
from src.utils.logging import logger


class CausalPathNode:
    """A node in a causal path."""

    def __init__(
        self,
        event_id: str,
        event: Event,
        depth: int,
        edge_from_parent: Optional[CausalHypothesis] = None,
    ):
        self.event_id = event_id
        self.event = event
        self.depth = depth
        self.edge_from_parent = edge_from_parent


class CausalPathAnalysis:
    """Analysis result for a causal path to target event."""

    def __init__(self):
        self.paths: List[List[CausalPathNode]] = []
        self.all_events_in_paths: Set[str] = set()
        self.confirmed_event_ids: Set[str] = set()
        self.predicted_event_ids: Set[str] = set()
        self.target_event_id: Optional[str] = None

    def add_path(self, path: List[CausalPathNode]):
        """Add a path to the analysis."""
        self.paths.append(path)
        for node in path:
            self.all_events_in_paths.add(node.event_id)
            if node.event.status == EventStatus.OCCURRED:
                self.confirmed_event_ids.add(node.event_id)
            else:
                self.predicted_event_ids.add(node.event_id)

    def get_completion_ratio(self) -> float:
        """Get ratio of confirmed events to total events in paths."""
        total = len(self.all_events_in_paths)
        if total == 0:
            return 0.0
        return len(self.confirmed_event_ids) / total

    def get_shortest_path(self) -> Optional[List[CausalPathNode]]:
        """Get shortest path to target."""
        if not self.paths:
            return None
        return min(self.paths, key=len)

    def get_path_statistics(self) -> Dict[str, Any]:
        """Get statistics about paths."""
        if not self.paths:
            return {
                "total_paths": 0,
                "shortest_path_length": 0,
                "longest_path_length": 0,
                "avg_path_length": 0.0,
                "total_events": 0,
                "confirmed_events": 0,
                "predicted_events": 0,
                "completion_ratio": 0.0,
            }

        path_lengths = [len(p) for p in self.paths]

        return {
            "total_paths": len(self.paths),
            "shortest_path_length": min(path_lengths),
            "longest_path_length": max(path_lengths),
            "avg_path_length": sum(path_lengths) / len(path_lengths),
            "total_events": len(self.all_events_in_paths),
            "confirmed_events": len(self.confirmed_event_ids),
            "predicted_events": len(self.predicted_event_ids),
            "completion_ratio": self.get_completion_ratio(),
        }


class CausalPathAnalyzer:
    """Analyzes causal paths from events to target events."""

    def __init__(self, db: GenericDatabase):
        self.db = db
        self._events_cache: Optional[Dict[str, Event]] = None
        self._hypotheses_cache: Optional[List[CausalHypothesis]] = None

    def analyze_paths_to_target(
        self, target_event_id: str, max_depth: int = 5, max_paths: int = 10
    ) -> CausalPathAnalysis:
        """Find and analyze all causal paths leading to the target event.

        Args:
            target_event_id: ID of the target event
            max_depth: Maximum path length to search
            max_paths: Maximum number of paths to return

        Returns:
            CausalPathAnalysis with path information
        """
        # Load data
        events = self._get_events()
        hypotheses = self._get_hypotheses()

        if target_event_id not in events:
            logger.warning(f"Target event {target_event_id} not found")
            return CausalPathAnalysis()

        # Build adjacency list for incoming edges (reverse direction for BFS)
        incoming_edges: Dict[str, List[CausalHypothesis]] = {}
        for hyp in hypotheses:
            if hyp.target_event_id not in incoming_edges:
                incoming_edges[hyp.target_event_id] = []
            incoming_edges[hyp.target_event_id].append(hyp)

        # BFS to find all paths to target (searching backwards from target)
        analysis = CausalPathAnalysis()
        analysis.target_event_id = target_event_id

        # Track unique paths by event sequence to avoid duplicates
        seen_path_signatures: Set[Tuple[str, ...]] = set()

        # Queue: (current_event_id, path_nodes, visited_set)
        queue = deque([(target_event_id, [], set([target_event_id]))])
        found_paths = 0

        while queue and found_paths < max_paths:
            current_id, path, visited = queue.popleft()

            # Check depth limit
            if len(path) >= max_depth:
                continue

            # Get incoming edges (causes of current event)
            incoming = incoming_edges.get(current_id, [])

            # If no incoming edges, this is a root cause - save path
            if not incoming:
                if path:  # Only save non-empty paths
                    # Reverse path since we built it backwards
                    reversed_path = list(reversed(path))

                    # Create signature from event IDs
                    path_signature = tuple([node.event_id for node in reversed_path])

                    # Only add if we haven't seen this exact path sequence before
                    if path_signature not in seen_path_signatures:
                        seen_path_signatures.add(path_signature)
                        analysis.add_path(reversed_path)
                        found_paths += 1
                continue

            # Explore each incoming edge
            # Group hypotheses by source to avoid duplicate exploration
            sources_seen = set()
            for hypothesis in incoming:
                source_id = hypothesis.source_event_id

                # Skip if already visited in this path
                if source_id in visited:
                    continue

                # Skip if source event doesn't exist
                if source_id not in events:
                    continue

                # Skip if we've already queued this source in this iteration
                # (avoids duplicate exploration when multiple hypotheses have same source)
                if source_id in sources_seen:
                    continue
                sources_seen.add(source_id)

                # Create node for source event
                node = CausalPathNode(
                    event_id=source_id,
                    event=events[source_id],
                    depth=len(path),
                    edge_from_parent=hypothesis,
                )

                # Add to path and continue search
                new_path = [node] + path
                new_visited = visited | {source_id}
                queue.append((source_id, new_path, new_visited))

        return analysis

    def get_path_for_events(
        self, event_ids: List[str], target_event_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get path information for specific events relative to target.

        Args:
            event_ids: List of event IDs to analyze
            target_event_id: Target event ID

        Returns:
            Dict mapping event_id to path information
        """
        events = self._get_events()
        hypotheses = self._get_hypotheses()

        # Build adjacency list for outgoing edges
        outgoing_edges: Dict[str, List[CausalHypothesis]] = {}
        for hyp in hypotheses:
            if hyp.source_event_id not in outgoing_edges:
                outgoing_edges[hyp.source_event_id] = []
            outgoing_edges[hyp.source_event_id].append(hyp)

        result = {}

        for event_id in event_ids:
            if event_id not in events:
                continue

            event = events[event_id]

            # Find shortest path from this event to target
            path = self._find_shortest_path(
                event_id, target_event_id, outgoing_edges, events
            )

            # Analyze path direction (does it lead toward target?)
            path_analysis = self._analyze_path_direction(path) if path else None

            result[event_id] = {
                "has_path_to_target": path is not None,
                "path_length": len(path) if path else None,
                "path_analysis": path_analysis,
                "event_status": event.status.value,
                "is_confirmed": event.status == EventStatus.OCCURRED,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
            }

        return result

    def _find_shortest_path(
        self,
        source_id: str,
        target_id: str,
        outgoing_edges: Dict[str, List[CausalHypothesis]],
        events: Dict[str, Event],
        max_depth: int = 10,
    ) -> Optional[List[CausalHypothesis]]:
        """Find shortest path from source to target using BFS."""
        if source_id == target_id:
            return []

        # BFS: (current_id, path_edges)
        queue = deque([(source_id, [])])
        visited = {source_id}

        while queue:
            current_id, path = queue.popleft()

            if len(path) >= max_depth:
                continue

            # Explore outgoing edges
            for hypothesis in outgoing_edges.get(current_id, []):
                next_id = hypothesis.target_event_id

                # Found target
                if next_id == target_id:
                    return path + [hypothesis]

                # Skip if visited or doesn't exist
                if next_id in visited or next_id not in events:
                    continue

                visited.add(next_id)
                queue.append((next_id, path + [hypothesis]))

        return None

    def _analyze_path_direction(self, path: List[CausalHypothesis]) -> Dict[str, Any]:
        """Analyze the direction and strength of a causal path."""
        if not path:
            return {
                "net_direction": "neutral",
                "positive_links": 0,
                "negative_links": 0,
                "neutral_links": 0,
                "combined_strength": 0.0,
                "combined_confidence": 0.0,
            }

        positive_types = {
            CausalRelationType.CAUSES,
            CausalRelationType.ENABLES,
            CausalRelationType.AMPLIFIES,
            CausalRelationType.TRIGGERS,
        }

        negative_types = {CausalRelationType.INHIBITS, CausalRelationType.PREVENTS}

        positive_links = 0
        negative_links = 0
        neutral_links = 0

        combined_strength = 1.0
        combined_confidence = 1.0

        for hypothesis in path:
            # Classify link direction
            if hypothesis.relation_type in positive_types:
                positive_links += 1
            elif hypothesis.relation_type in negative_types:
                negative_links += 1
            else:
                neutral_links += 1

            # Combine strength and confidence
            combined_strength *= hypothesis.strength
            combined_confidence *= hypothesis.confidence

        # Determine net direction
        if negative_links % 2 == 1:
            # Odd number of negative links = net negative
            net_direction = "unfavorable"
        elif positive_links > 0:
            net_direction = "favorable"
        else:
            net_direction = "neutral"

        return {
            "net_direction": net_direction,
            "positive_links": positive_links,
            "negative_links": negative_links,
            "neutral_links": neutral_links,
            "combined_strength": combined_strength,
            "combined_confidence": combined_confidence,
        }

    def _get_events(self) -> Dict[str, Event]:
        """Get all events with caching."""
        if self._events_cache is None:
            events = self.db.get_many(Event, filters={})
            self._events_cache = {e.id: e for e in events}
        return self._events_cache

    def _get_hypotheses(self) -> List[CausalHypothesis]:
        """Get all hypotheses with caching."""
        if self._hypotheses_cache is None:
            self._hypotheses_cache = self.db.get_many(CausalHypothesis, filters={})
        return self._hypotheses_cache

    def clear_cache(self):
        """Clear cached data."""
        self._events_cache = None
        self._hypotheses_cache = None
