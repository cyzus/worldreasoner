"""Graph inspection for forecasting - queries forecast DB.

This tool allows the forecasting agent to inspect the causal graph
it has built during its reasoning process.
"""

from src.tools.base.database_mixin import DatabaseAwareTool
from typing import Dict, List, Set
from collections import defaultdict

from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis
from src.utils.logging import logger
from src.analysis.graph_visualization import GraphVisualizer
from src.tools.inspectors.formatting import (
    format_inspector_header,
    format_section_header,
)


class ForecastGraphInspectorTool(DatabaseAwareTool):
    """Inspect causal graph built during forecasting.

    This tool helps you understand the quality and structure of the
    causal reasoning graph you've built so far.
    """

    name = "inspect_forecast_graph"
    description = """Visualize and analyze your forecast's causal reasoning graph.

    Use this tool to see a visual representation of your causal explanation:
    - Text-based tree showing causal chains (Root → Intermediate → Target)
    - Event details with descriptions
    - Causal chain depths and paths
    - Evidence support for each hypothesis
    - Quality metrics and recommendations

    If max_depth < 2, your graph is TOO SHALLOW - you need to:
    1. Pick the most important immediate causes
    2. Ask "What caused THIS?" for each
    3. Create intermediate events
    4. Link them with causal chains: Root → Intermediate → Target

    No arguments required - uses the current session.

    Returns:
        str: Multi-section text with visual graph, causal chains, and statistics
    """

    inputs = {}
    output_type = "string"

    def __init__(
        self, forecast_db_path: str = "worldreasoner.db", session_id: str = None
    ):
        """Initialize the forecast graph inspector.

        Args:
            forecast_db_path: Path to forecast database
            session_id: Session ID for tracking this forecast session
        """
        super().__init__(
            db_path=forecast_db_path, ensure_tables=[ForecastEvent, ForecastHypothesis]
        )
        # Use self.db as forecast_db for consistency
        self.forecast_db = self.db
        self.session_id = session_id

    def forward(self) -> str:
        """Visualize and analyze the forecast graph for the current session.

        Returns:
            Multi-section text with visual graph representation and statistics
        """
        try:
            # Query forecast DB for events and hypotheses in this session
            events = self.forecast_db.get_many(
                ForecastEvent, filters={"session_id": self.session_id}
            )
            hypotheses = self.forecast_db.get_many(
                ForecastHypothesis, filters={"session_id": self.session_id}
            )

            if not events and not hypotheses:
                return self._format_empty_graph()

            # Build event dictionary
            events_dict = {e.id: e for e in events}

            # Build graph adjacency list (target -> sources)
            graph = defaultdict(list)
            hypothesis_map = {}  # (source, target) -> hypothesis
            for h in hypotheses:
                graph[h.target_event_id].append(h.source_event_id)
                hypothesis_map[(h.source_event_id, h.target_event_id)] = h

            # Calculate graph metrics
            graph_stats = self._analyze_graph_structure(events, hypotheses, graph)

            # Generate visualization
            output = self._format_graph_visualization(
                events_dict, graph, hypothesis_map, graph_stats
            )

            return output

        except Exception as e:
            logger.error(f"Error inspecting forecast graph: {e}")
            return f"ERROR: Failed to inspect forecast graph: {e}"

    def _analyze_graph_structure(
        self,
        events: List[ForecastEvent],
        hypotheses: List[ForecastHypothesis],
        graph: Dict[str, List[str]],
    ) -> Dict:
        """Analyze the graph structure and compute metrics.

        Args:
            events: List of forecast events
            hypotheses: List of forecast hypotheses
            graph: Adjacency list (target -> sources)

        Returns:
            Dictionary with graph statistics
        """
        event_ids = {e.id for e in events}

        # Find all leaf nodes (events with no incoming edges = root causes)
        all_targets = set(graph.keys())
        all_sources = set()
        for sources in graph.values():
            all_sources.update(sources)
        leaf_nodes = all_sources - all_targets

        # Calculate depths from target events (endpoints of causal chains)
        # Target events are those that are effects but not causes of other events
        target_events = all_targets - all_sources if all_targets else event_ids

        max_depth = 0
        for event_id in target_events:
            depth = self._find_max_depth_from_node(graph, event_id, set())
            max_depth = max(max_depth, depth)

        # Calculate average metrics
        avg_confidence = (
            sum(h.confidence for h in hypotheses) / len(hypotheses)
            if hypotheses
            else 0.0
        )
        avg_strength = (
            sum(h.strength for h in hypotheses) / len(hypotheses) if hypotheses else 0.0
        )

        # Quality combines depth, confidence, and evidence support
        depth_score = min(max_depth / 3.0, 1.0) if max_depth > 0 else 0.0
        evidence_score = (
            sum(1 for h in hypotheses if h.evidence_article_ids) / len(hypotheses)
            if hypotheses
            else 0.0
        )

        quality_score = (
            depth_score * 0.4
            + avg_confidence * 0.3
            + avg_strength * 0.2
            + evidence_score * 0.1
        )

        return {
            "session_id": self.session_id,
            "events": len(events),
            "hypotheses": len(hypotheses),
            "max_depth": max_depth,
            "leaf_events": len(leaf_nodes),
            "avg_confidence": round(avg_confidence, 2),
            "avg_strength": round(avg_strength, 2),
            "with_evidence": sum(1 for h in hypotheses if h.evidence_article_ids),
            "quality_score": round(quality_score, 2),
            "status": "analyzed",
        }

    def _find_max_depth_from_node(
        self, graph: Dict[str, List[str]], node: str, visited: Set[str]
    ) -> int:
        """Find maximum depth from a node using DFS."""
        return GraphVisualizer.find_max_depth_from_node(graph, node, visited)

    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics."""
        return GraphVisualizer.get_recommendation(
            stats["max_depth"], stats["quality_score"]
        )

    def _format_empty_graph(self) -> str:
        """Format output for empty graph."""
        header = format_inspector_header("FORECAST CAUSAL GRAPH INSPECTOR")
        return f"""{header}
Session ID: {self.session_id}

STATUS: Empty Graph
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No causal relationships have been created yet.

RECOMMENDATION:
→ Start by creating a target event (the outcome you're forecasting)
→ Identify 2-3 immediate causes using evidence articles
→ For each cause, ask "What caused THIS?" to build deeper chains
"""

    def _format_graph_visualization(
        self,
        events: Dict[str, ForecastEvent],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, ForecastHypothesis],
        stats: Dict,
    ) -> str:
        """Format the graph as a visual text representation.

        Args:
            events: Event ID to ForecastEvent object mapping
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping
            stats: Graph statistics

        Returns:
            Formatted multi-section text
        """
        sections = []

        # Header
        sections.append(format_inspector_header("FORECAST CAUSAL GRAPH INSPECTOR"))

        # Session info
        sections.append(f"Session ID: {self.session_id}")
        sections.append("")

        # Visual graph section
        sections.extend(format_section_header("CAUSAL GRAPH STRUCTURE"))

        # Find potential target events (effects with no outgoing edges)
        all_sources = set()
        for sources in graph.values():
            all_sources.update(sources)
        all_targets = set(graph.keys())
        potential_targets = all_targets - all_sources

        if potential_targets:
            # Build tree from each target event
            for target_id in list(potential_targets)[:3]:  # Show up to 3 targets
                if target_id in events:
                    sections.append(
                        f"Target: {self._truncate(events[target_id].title, 50)}"
                    )
                    sections.append("")
                    tree_lines = self._build_causal_tree(
                        target_id, events, graph, hypothesis_map, set()
                    )
                    sections.extend(tree_lines)
                    sections.append("")
        else:
            # Show all disconnected components
            sections.append("⚠ No clear target identified. Showing all causal links:")
            sections.append("")
            for target_id, source_ids in list(graph.items())[:10]:  # Limit output
                target_event = events.get(target_id)
                target_desc = self._truncate(
                    target_event.title if target_event else target_id, 50
                )
                sections.append(f"  ▸ {target_desc}")
                for source_id in source_ids:
                    source_event = events.get(source_id)
                    source_desc = self._truncate(
                        source_event.title if source_event else source_id, 45
                    )
                    hyp = hypothesis_map.get((source_id, target_id))
                    conf = f"[conf: {hyp.confidence:.1f}]" if hyp else ""
                    sections.append(f"    └─→ {source_desc} {conf}")
                sections.append("")

        # Causal chains section
        sections.extend(format_section_header("CAUSAL CHAINS (Root → Target)"))

        if potential_targets:
            all_chains = []
            for target_id in potential_targets:
                chains = self._find_all_causal_chains(
                    target_id, events, graph, hypothesis_map
                )
                all_chains.extend(chains)

            if all_chains:
                all_chains.sort(key=lambda c: len(c), reverse=True)
                for i, chain in enumerate(all_chains[:5], 1):  # Show top 5 chains
                    sections.append(f"Chain {i} (depth: {len(chain) - 1}):")
                    for j, (event_id, hyp) in enumerate(chain):
                        event = events.get(event_id)
                        desc = self._truncate(event.title if event else event_id, 55)
                        indent = "  " * j

                        if j == 0:
                            sections.append(f"  {indent}🌱 {desc}")
                        elif j == len(chain) - 1:
                            sections.append(f"  {indent}🎯 {desc}")
                        else:
                            sections.append(f"  {indent}⚡ {desc}")

                        if hyp and j < len(chain) - 1:
                            evidence_str = (
                                f"[{len(hyp.evidence_article_ids)} articles]"
                                if hyp.evidence_article_ids
                                else "[no evidence]"
                            )
                            sections.append(
                                f"  {indent}   └─ conf: {hyp.confidence:.1f}, strength: {hyp.strength:.1f} {evidence_str}"
                            )
                    sections.append("")
            else:
                sections.append("  No complete causal chains found.")
                sections.append("")
        else:
            sections.append("  No target events identified yet.")
            sections.append("")

        # Statistics section
        sections.extend(format_section_header("GRAPH STATISTICS"))
        sections.append(f"  Events:           {stats['events']}")
        sections.append(f"  Hypotheses:       {stats['hypotheses']}")
        sections.append(f"  Max Depth:        {stats['max_depth']} levels")
        sections.append(f"  Leaf Events:      {stats['leaf_events']} (root causes)")
        sections.append(f"  Avg Confidence:   {stats['avg_confidence']:.2f}")
        sections.append(f"  Avg Strength:     {stats['avg_strength']:.2f}")
        sections.append(
            f"  With Evidence:    {stats['with_evidence']}/{stats['hypotheses']}"
        )
        sections.append(f"  Quality Score:    {stats['quality_score']:.2f}")
        sections.append("")

        # Recommendation
        recommendation = self._get_recommendation(stats)
        sections.extend(format_section_header("RECOMMENDATION"))
        sections.append(f"  {recommendation}")
        sections.append("")

        return "\n".join(sections)

    def _build_causal_tree(
        self,
        event_id: str,
        events: Dict[str, ForecastEvent],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, ForecastHypothesis],
        visited: Set[str],
        prefix: str = "",
        is_last: bool = True,
    ) -> List[str]:
        """Build ASCII tree representation of causal graph."""
        return GraphVisualizer.build_causal_tree(
            event_id,
            events,
            graph,
            hypothesis_map,
            visited,
            get_event_title=lambda e: e.title if e else "",
            prefix=prefix,
            is_last=is_last,
        )

    def _find_all_causal_chains(
        self,
        target_id: str,
        events: Dict[str, ForecastEvent],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, ForecastHypothesis],
    ) -> List[List[tuple]]:
        """Find all causal chains from root causes to target."""
        return GraphVisualizer.find_all_causal_chains(
            target_id, events, graph, hypothesis_map
        )

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text to max length with ellipsis."""
        return GraphVisualizer.truncate(text, max_len)
