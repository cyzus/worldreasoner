"""Graph inspector tool - analyze causal graph structure and depth."""

import json
from typing import Optional, Dict, List, Set
from collections import defaultdict

from smolagents import Tool
from src.domain.models import CausalHypothesis, Event
from src.core.database import GenericDatabase


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
    description = """Analyze the causal graph structure for a question.

    Use this tool to check if you've built a deep enough causal explanation:
    - How many levels of causation? (1 = shallow, 3+ = deep)
    - How many events and causal links?
    - Quality score of the explanation

    If max_depth < 2, your graph is TOO SHALLOW - you need to:
    1. Pick the most important immediate causes
    2. Ask "What caused THIS?" for each
    3. Create intermediate events using event_identifier
    4. Link them with causal_reasoner: Root → Intermediate → Target

    Args:
        question_id (str): ID of the question to analyze

    Returns:
        str: JSON with graph statistics including depth, events, links, quality score
    """

    inputs = {
        "question_id": {
            "type": "string",
            "description": "Question ID to analyze the causal graph for"
        }
    }
    output_type = "string"  # JSON string

    def __init__(self, db_path: str = "worldreasoner.db"):
        """Initialize the graph inspector.

        Args:
            db_path: Path to database
        """
        super().__init__()
        self.db = GenericDatabase(db_path)

    def forward(self, question_id: str) -> str:
        """Analyze graph structure for a question.

        Args:
            question_id: Question to analyze

        Returns:
            JSON string with graph statistics
        """
        # Get all hypotheses related to this question
        all_hypotheses = self.db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses
            if question_id in h.discovered_by_question_ids
        ]

        if not question_hypotheses:
            return json.dumps({
                "question_id": question_id,
                "events": 0,
                "hypotheses": 0,
                "max_depth": 0,
                "avg_depth": 0.0,
                "quality_score": 0.0,
                "status": "empty",
                "recommendation": "Start by creating a target event, then identify immediate causes."
            }, indent=2)

        # Build graph structure
        graph_stats = self._analyze_graph_structure(question_hypotheses, question_id)

        # Add recommendations
        graph_stats["recommendation"] = self._get_recommendation(graph_stats)

        return json.dumps(graph_stats, indent=2)

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
        """Find length of path from start to target using BFS.

        Args:
            graph: Adjacency list (target -> sources)
            start: Starting node
            target: Target node
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

        # Check if start points to target
        if start in graph:
            if target in graph[start]:
                return 1

            # Recursively search through sources
            max_path = 0
            for source in graph[start]:
                path_len = self._find_path_length(graph, source, target, visited.copy())
                if path_len > 0:
                    max_path = max(max_path, 1 + path_len)
            return max_path

        # Search in reverse - if target points to start
        for node, sources in graph.items():
            if node == start:
                continue
            if start in sources:
                path_len = self._find_path_length(graph, node, target, visited.copy())
                if path_len > 0:
                    return 1 + path_len

        return 0

    def _find_max_depth_from_node(
        self,
        graph: Dict[str, List[str]],
        node: str,
        visited: Set[str]
    ) -> int:
        """Find maximum depth from a node using DFS.

        Args:
            graph: Adjacency list
            node: Starting node
            visited: Visited nodes

        Returns:
            Maximum depth from this node
        """
        if node in visited or node not in graph:
            return 0

        visited.add(node)
        max_child_depth = 0

        for source in graph[node]:
            depth = self._find_max_depth_from_node(graph, source, visited.copy())
            max_child_depth = max(max_child_depth, depth)

        return 1 + max_child_depth

    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics.

        Args:
            stats: Graph statistics

        Returns:
            Recommendation string
        """
        max_depth = stats["max_depth"]
        quality = stats["quality_score"]

        if max_depth == 0:
            return "No causal graph yet. Start by identifying the target event and immediate causes."
        elif max_depth == 1:
            return "Graph is SHALLOW (1 level). You need deeper chains! For each immediate cause, ask 'What caused THIS?' and create intermediate events."
        elif max_depth == 2:
            return "Graph has some depth (2 levels). Consider going deeper on the most important causal chains."
        elif quality < 0.6:
            return "Graph depth is good, but quality is low. Add more evidence citations and improve confidence scores."
        else:
            return "Graph looks good! Deep causal chains with good quality."
