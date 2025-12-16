"""Graph inspector tool - analyze causal graph structure and depth."""

import json
from typing import Optional, Dict, List, Set
from collections import defaultdict

from smolagents import Tool
from src.domain.models import CausalHypothesis, Event
from src.core.database import GenericDatabase
from src.utils.graph_visualization import GraphVisualizer


class GraphInspectorTool(Tool):
    """Inspect causal graph structure to evaluate depth and quality.

    This tool helps the agent:
    1. Measure causal chain depth (longest path)
    2. Count events and hypotheses
    3. Evaluate graph quality
    4. Identify gaps to fill for deeper explanations

    Use this tool to check if your causal explanation is deep enough,
    then iterate to add more depth if needed.
    """

    name = "graph_inspector"
    description = """Visualize and analyze the causal graph structure for a question.

    Use this tool to see a visual representation of your causal explanation:
    - Text-based tree showing causal chains (Root → Intermediate → Target)
    - Event details with descriptions
    - Causal chain depths and paths
    - Evidence support for each hypothesis
    - Quality metrics and recommendations

    If max_depth < 2, your graph is TOO SHALLOW - you need to:
    1. Pick the most important immediate causes
    2. Ask "What caused THIS?" for each
    3. Create intermediate events using event_identifier
    4. Link them with causal_reasoner: Root → Intermediate → Target

    Returns:
        str: Multi-section text with visual graph, causal chains, and statistics
    """
    inputs = {}
    output_type = "string"

    def __init__(self, question_id, db_path: str = "worldreasoner.db"):
        """Initialize the graph inspector.

        Args:
            db_path: Path to database
        """
        super().__init__()
        self.db = GenericDatabase(db_path)
        self.question_id = question_id

    def forward(self) -> str:
        """Visualize and analyze graph structure for a question.

        Returns:
            Multi-section text with visual graph representation and statistics
        """
        # Get all hypotheses related to this question
        all_hypotheses = self.db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses
            if self.question_id in h.discovered_by_question_ids
        ]

        if not question_hypotheses:
            return self._format_empty_graph()

        # Get the question
        from src.domain.models import Question
        question = self.db.get(Question, self.question_id)
        
        # Build graph structure and statistics
        graph_stats = self._analyze_graph_structure(question_hypotheses, self.question_id)
        
        # Get all unique event IDs
        event_ids = set()
        for hyp in question_hypotheses:
            event_ids.add(hyp.source_event_id)
            event_ids.add(hyp.target_event_id)
        
        # Fetch event details
        events = {eid: self.db.get(Event, eid) for eid in event_ids}
        
        # Build adjacency list for visualization
        graph = defaultdict(list)
        hypothesis_map = {}  # (source, target) -> hypothesis
        for hyp in question_hypotheses:
            graph[hyp.target_event_id].append(hyp.source_event_id)
            hypothesis_map[(hyp.source_event_id, hyp.target_event_id)] = hyp
        
        # Generate visualization
        output = self._format_graph_visualization(
            question, events, graph, hypothesis_map, graph_stats
        )
        
        return output

    def _analyze_graph_structure(
        self,
        hypotheses: List[CausalHypothesis],
        question_id: str
    ) -> Dict:
        """Analyze the graph structure and compute metrics.

        Args:
            hypotheses: List of causal hypotheses
            question_id: Question being analyzed

        Returns:
            Dictionary with graph statistics
        """
        # Extract unique events involved
        event_ids: Set[str] = set()
        for hyp in hypotheses:
            event_ids.add(hyp.source_event_id)
            event_ids.add(hyp.target_event_id)

        # Build adjacency list (target -> sources)
        graph: Dict[str, List[str]] = defaultdict(list)
        for hyp in hypotheses:
            graph[hyp.target_event_id].append(hyp.source_event_id)

        # Get the question to find target event
        from src.domain.models import Question
        question = self.db.get(Question, question_id)
        target_event_id = question.target_event_id if question else None

        # Find all leaf nodes (events with no incoming edges)
        all_targets = set(graph.keys())
        all_sources = set()
        for sources in graph.values():
            all_sources.update(sources)
        leaf_nodes = all_sources - all_targets

        # Calculate depths from all leaf nodes
        max_depth = 0
        total_depth = 0
        depth_count = 0

        if target_event_id:
            # Calculate depth to target event from each leaf
            for leaf in leaf_nodes:
                depth = self._find_path_length(graph, leaf, target_event_id)
                if depth > 0:
                    max_depth = max(max_depth, depth)
                    total_depth += depth
                    depth_count += 1
        else:
            # No target event - just find longest path
            for event_id in event_ids:
                depth = self._find_max_depth_from_node(graph, event_id, set())
                max_depth = max(max_depth, depth)

        avg_depth = total_depth / depth_count if depth_count > 0 else 0.0

        # Calculate quality score
        avg_confidence = sum(h.confidence for h in hypotheses) / len(hypotheses)
        avg_strength = sum(h.strength for h in hypotheses) / len(hypotheses)

        # Quality combines depth, confidence, and evidence support
        depth_score = min(max_depth / 3.0, 1.0)  # Normalize to 0-1 (3+ levels = full score)
        evidence_score = sum(1 for h in hypotheses if h.evidence_article_ids) / len(hypotheses)

        quality_score = (
            depth_score * 0.4 +
            avg_confidence * 0.3 +
            avg_strength * 0.2 +
            evidence_score * 0.1
        )

        return {
            "question_id": question_id,
            "events": len(event_ids),
            "hypotheses": len(hypotheses),
            "max_depth": max_depth,
            "avg_depth": round(avg_depth, 2),
            "leaf_events": len(leaf_nodes),
            "avg_confidence": round(avg_confidence, 2),
            "avg_strength": round(avg_strength, 2),
            "with_evidence": sum(1 for h in hypotheses if h.evidence_article_ids),
            "quality_score": round(quality_score, 2),
            "status": "analyzed"
        }

    def _find_path_length(
        self,
        graph: Dict[str, List[str]],
        start: str,
        target: str,
        visited: Optional[Set[str]] = None
    ) -> int:
        """Find length of causal path from start to target.

        The graph structure is graph[target_event] = [source_events], where
        sources CAUSE the target. To find path length from start to target,
        we need to traverse in the causal direction: start causes X causes target.

        Args:
            graph: Adjacency list (target -> sources)
            start: Starting node (source event)
            target: Target node (final effect)
            visited: Set of visited nodes to prevent cycles

        Returns:
            Path length, or 0 if no path exists
        """
        if visited is None:
            visited = set()

        if start == target:
            return 0

        if start in visited:
            return 0

        visited.add(start)

        # Find all nodes that have 'start' as a source (i.e., events that 'start' causes)
        # Since graph[node] = sources, we need to check if start is in any node's sources
        max_path = 0
        for node, sources in graph.items():
            if start in sources:
                # start causes node, so we can traverse this edge
                if node == target:
                    # Direct causal link to target
                    return 1
                else:
                    # Recursively find path from node to target
                    path_len = self._find_path_length(graph, node, target, visited.copy())
                    if path_len > 0:
                        max_path = max(max_path, 1 + path_len)

        return max_path

    def _find_max_depth_from_node(
        self,
        graph: Dict[str, List[str]],
        node: str,
        visited: Set[str]
    ) -> int:
        """Find maximum depth from a node using DFS."""
        return GraphVisualizer.find_max_depth_from_node(graph, node, visited)

    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics."""
        return GraphVisualizer.get_recommendation(stats["max_depth"], stats["quality_score"])

    def _format_empty_graph(self) -> str:
        """Format output for empty graph."""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║                    CAUSAL GRAPH INSPECTOR                      ║
╚════════════════════════════════════════════════════════════════╝

Question ID: {self.question_id}

STATUS: Empty Graph
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No causal relationships have been created yet.

RECOMMENDATION:
→ Start by creating a target event (the outcome you're explaining)
→ Identify 2-3 immediate causes using evidence articles
→ For each cause, ask "What caused THIS?" to build deeper chains
"""

    def _format_graph_visualization(
        self,
        question,
        events: Dict[str, Event],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, CausalHypothesis],
        stats: Dict
    ) -> str:
        """Format the graph as a visual text representation.

        Args:
            question: Question object
            events: Event ID to Event object mapping
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping
            stats: Graph statistics

        Returns:
            Formatted multi-section text
        """
        sections = []
        
        # Header
        sections.append("""
╔════════════════════════════════════════════════════════════════╗
║                    CAUSAL GRAPH INSPECTOR                      ║
╚════════════════════════════════════════════════════════════════╝
""")
        
        # Question info
        if question:
            sections.append(f"Question: {question.question_text[:80]}...")
            sections.append(f"Question ID: {self.question_id}")
            sections.append("")
        
        # Visual graph section
        sections.append("CAUSAL GRAPH STRUCTURE")
        sections.append("━" * 64)
        sections.append("")
        
        target_event_id = question.target_event_id if question else None
        if target_event_id and target_event_id in events:
            # Build tree from target event
            tree_lines = self._build_causal_tree(
                target_event_id, events, graph, hypothesis_map, set()
            )
            sections.extend(tree_lines)
        else:
            # Show all disconnected components
            sections.append("⚠ No target event specified. Showing all causal links:")
            sections.append("")
            for target_id, source_ids in graph.items():
                target_event = events.get(target_id)
                target_desc = self._truncate(target_event.description if target_event else target_id, 50)
                sections.append(f"  ▸ {target_desc}")
                for source_id in source_ids:
                    source_event = events.get(source_id)
                    source_desc = self._truncate(source_event.description if source_event else source_id, 45)
                    hyp = hypothesis_map.get((source_id, target_id))
                    conf = f"[conf: {hyp.confidence:.1f}]" if hyp else ""
                    sections.append(f"    └─→ {source_desc} {conf}")
                sections.append("")
        
        # Causal chains section
        sections.append("")
        sections.append("CAUSAL CHAINS (Root → Target)")
        sections.append("━" * 64)
        sections.append("")
        
        if target_event_id:
            chains = self._find_all_causal_chains(target_event_id, events, graph, hypothesis_map)
            if chains:
                for i, chain in enumerate(chains[:5], 1):  # Show top 5 chains
                    sections.append(f"Chain {i} (depth: {len(chain)-1}):")
                    for j, (event_id, hyp) in enumerate(chain):
                        event = events.get(event_id)
                        desc = self._truncate(event.description if event else event_id, 55)
                        indent = "  " * j
                        
                        if j == 0:
                            sections.append(f"  {indent}🌱 {desc}")
                        elif j == len(chain) - 1:
                            sections.append(f"  {indent}🎯 {desc}")
                        else:
                            sections.append(f"  {indent}⚡ {desc}")
                        
                        if hyp and j < len(chain) - 1:
                            evidence_str = f"[{len(hyp.evidence_article_ids)} articles]" if hyp.evidence_article_ids else "[no evidence]"
                            sections.append(f"  {indent}   └─ conf: {hyp.confidence:.1f}, strength: {hyp.strength:.1f} {evidence_str}")
                    sections.append("")
            else:
                sections.append("  No complete causal chains found.")
                sections.append("")
        
        # Statistics section
        sections.append("")
        sections.append("GRAPH STATISTICS")
        sections.append("━" * 64)
        sections.append("")
        sections.append(f"  Events:           {stats['events']}")
        sections.append(f"  Hypotheses:       {stats['hypotheses']}")
        sections.append(f"  Max Depth:        {stats['max_depth']} levels")
        sections.append(f"  Avg Depth:        {stats['avg_depth']:.1f} levels")
        sections.append(f"  Leaf Events:      {stats['leaf_events']} (root causes)")
        sections.append(f"  Avg Confidence:   {stats['avg_confidence']:.2f}")
        sections.append(f"  Avg Strength:     {stats['avg_strength']:.2f}")
        sections.append(f"  With Evidence:    {stats['with_evidence']}/{stats['hypotheses']}")
        sections.append(f"  Quality Score:    {stats['quality_score']:.2f}")
        sections.append("")
        
        # Recommendation
        recommendation = self._get_recommendation(stats)
        sections.append("RECOMMENDATION")
        sections.append("━" * 64)
        sections.append(f"  {recommendation}")
        sections.append("")
        
        return "\n".join(sections)

    def _build_causal_tree(
        self,
        event_id: str,
        events: Dict[str, Event],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, CausalHypothesis],
        visited: Set[str],
        prefix: str = "",
        is_last: bool = True
    ) -> List[str]:
        """Build ASCII tree representation of causal graph."""
        return GraphVisualizer.build_causal_tree(
            event_id, events, graph, hypothesis_map, visited,
            get_event_title=lambda e: e.description if e else "",
            prefix=prefix, is_last=is_last
        )

    def _find_all_causal_chains(
        self,
        target_id: str,
        events: Dict[str, Event],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, CausalHypothesis]
    ) -> List[List[tuple]]:
        """Find all causal chains from root causes to target."""
        return GraphVisualizer.find_all_causal_chains(target_id, events, graph, hypothesis_map)

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text to max length with ellipsis."""
        return GraphVisualizer.truncate(text, max_len)

