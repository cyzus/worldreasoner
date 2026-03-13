"""Shared utilities for graph visualization and analysis."""

from typing import Dict, List, Set, Tuple, Any


class GraphVisualizer:
    """Shared graph visualization utilities for both regular and forecast graphs."""

    @staticmethod
    def truncate(text: str, max_len: int) -> str:
        """Truncate text to max length with ellipsis.

        Args:
            text: Text to truncate
            max_len: Maximum length

        Returns:
            Truncated text
        """
        if not text:
            return ""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    @staticmethod
    def find_max_depth_from_node(
        graph: Dict[str, List[str]], node: str, visited: Set[str]
    ) -> int:
        """Find maximum depth from a node using DFS.

        Args:
            graph: Adjacency list (target -> sources)
            node: Starting node
            visited: Visited nodes

        Returns:
            Maximum depth from this node (number of edges in longest path)
        """
        if node in visited:
            return 0

        # Leaf nodes (root causes with no incoming edges) have depth 0 (no edges)
        if node not in graph:
            return 0

        visited.add(node)
        max_child_depth = 0

        for source in graph[node]:
            depth = GraphVisualizer.find_max_depth_from_node(
                graph, source, visited.copy()
            )
            max_child_depth = max(max_child_depth, depth)

        return 1 + max_child_depth

    @staticmethod
    def build_causal_tree(
        event_id: str,
        events: Dict[str, Any],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, Any],
        visited: Set[str],
        get_event_title: callable,
        prefix: str = "",
        is_last: bool = True,
    ) -> List[str]:
        """Build ASCII tree representation of causal graph.

        Args:
            event_id: Current event ID
            events: Event mapping (ID -> event object)
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping
            visited: Visited nodes
            get_event_title: Function to extract title from event object
            prefix: Current line prefix
            is_last: Whether this is the last child

        Returns:
            List of formatted lines
        """
        if event_id in visited:
            return [f"{prefix}{'└─' if is_last else '├─'} [CYCLE: {event_id[:8]}...]"]

        visited.add(event_id)
        lines = []

        event = events.get(event_id)
        event_desc = GraphVisualizer.truncate(
            get_event_title(event) if event else event_id, 50
        )

        # Current node
        connector = "└─" if is_last else "├─"
        lines.append(f"{prefix}{connector} {event_desc}")

        # Children (sources that cause this event)
        sources = graph.get(event_id, [])
        if sources:
            extension = "  " if is_last else "│ "
            for i, source_id in enumerate(sources):
                is_last_child = i == len(sources) - 1
                hyp = hypothesis_map.get((source_id, event_id))

                # Add hypothesis info
                if hyp:
                    conf_str = f"conf: {hyp.confidence:.1f}"
                    strength_str = f"str: {hyp.strength:.1f}"
                    evidence_count = (
                        len(hyp.evidence_article_ids) if hyp.evidence_article_ids else 0
                    )
                    evidence_str = f"{evidence_count} articles"
                    lines.append(
                        f"{prefix}{extension}  [{conf_str}, {strength_str}, {evidence_str}]"
                    )

                # Recursively build subtree
                child_lines = GraphVisualizer.build_causal_tree(
                    source_id,
                    events,
                    graph,
                    hypothesis_map,
                    visited.copy(),
                    get_event_title,
                    prefix + extension,
                    is_last_child,
                )
                lines.extend(child_lines)

        return lines

    @staticmethod
    def find_all_causal_chains(
        target_id: str,
        events: Dict[str, Any],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, Any],
    ) -> List[List[Tuple[str, Any]]]:
        """Find all causal chains from root causes to target.

        Args:
            target_id: Target event ID
            events: Event mapping
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping

        Returns:
            List of chains, where each chain is [(event_id, hypothesis), ...]
        """
        all_chains = []

        def dfs(current_id: str, path: List[Tuple[str, Any]], visited: Set[str]):
            if current_id in visited:
                return

            visited.add(current_id)
            sources = graph.get(current_id, [])

            if not sources:
                # Reached a root cause - save this chain
                all_chains.append(list(reversed(path)))
            else:
                for source_id in sources:
                    hyp = hypothesis_map.get((source_id, current_id))
                    dfs(source_id, path + [(source_id, hyp)], visited.copy())

        # Start DFS from target
        dfs(target_id, [(target_id, None)], set())

        # Sort by depth (longest first)
        all_chains.sort(key=lambda c: len(c), reverse=True)

        return all_chains

    @staticmethod
    def get_recommendation(
        max_depth: int,
        quality_score: float,
        min_depth: int = 3,
        min_quality: float = 0.6,
    ) -> str:
        """Generate recommendation based on graph statistics.

        Args:
            max_depth: Maximum depth of the graph
            quality_score: Quality score (0-1)
            min_depth: Minimum depth for a satisfactory graph (from EvidenceSatisfactionConfig)
            min_quality: Minimum quality score threshold (from EvidenceSatisfactionConfig)

        Returns:
            Recommendation string
        """
        if max_depth == 0:
            return "No causal graph yet. Start by identifying events and their causal relationships."
        elif max_depth < min_depth - 1:
            return f"Graph is SHALLOW ({max_depth} level). You need deeper chains! For each immediate cause, ask 'What caused THIS?' and create intermediate events."
        elif max_depth < min_depth:
            return f"Graph has some depth ({max_depth} levels). Consider going deeper on the most important causal chains."
        elif quality_score < min_quality:
            return "Graph depth is good, but quality is low. Add more evidence citations and improve confidence scores."
        else:
            return "Graph depth and quality look good. Feel free to finalize or add minor improvements."
