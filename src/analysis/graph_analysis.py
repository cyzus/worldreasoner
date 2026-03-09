"""Shared utilities for causal graph quality analysis.

This module provides utilities for analyzing causal graph quality,
including depth calculation, quality metrics, and graph structure analysis.
"""

from typing import List, Dict, Any, Optional
from collections import defaultdict

from src.domain.models import CausalHypothesis
from src.analysis.graph_visualization import GraphVisualizer
from src.config.pipeline import SATISFACTION_DEFAULTS


def build_graph_from_hypotheses(
    hypotheses: List[CausalHypothesis],
) -> tuple[Dict[str, List[str]], set]:
    """Build adjacency list graph structure from causal hypotheses.

    Args:
        hypotheses: List of causal hypotheses

    Returns:
        Tuple of (graph, event_ids) where:
        - graph: Dict mapping target_event_id -> list of source_event_ids
        - event_ids: Set of all unique event IDs
    """
    graph = defaultdict(list)
    event_ids = set()

    for hyp in hypotheses:
        event_ids.add(hyp.source_event_id)
        event_ids.add(hyp.target_event_id)
        graph[hyp.target_event_id].append(hyp.source_event_id)

    return graph, event_ids


def calculate_graph_quality(
    hypotheses: List[CausalHypothesis],
    target_event_id: str = None,
    min_depth_for_full_score: int = SATISFACTION_DEFAULTS.min_graph_depth,
) -> Dict[str, Any]:
    """Calculate comprehensive quality metrics for a causal graph.

    This function computes:
    - Maximum depth (longest causal chain)
    - Average depth across all chains
    - Quality score (0-1) based on depth, confidence, strength, and evidence

    Args:
        hypotheses: List of causal hypotheses forming the graph
        target_event_id: Optional target event ID to calculate depth from
        min_depth_for_full_score: Minimum depth to achieve full depth score (default: 3)

    Returns:
        Dictionary with quality metrics:
        - max_depth: Maximum causal chain depth (number of levels)
        - avg_depth: Average depth across all chains
        - quality_score: Overall quality (0-1)
        - depth_score: Depth component (0-1)
        - confidence_score: Average confidence (0-1)
        - strength_score: Average strength (0-1)
        - evidence_score: Proportion with evidence (0-1)
        - event_count: Number of unique events
        - hypothesis_count: Number of hypotheses
    """
    if not hypotheses:
        return {
            "max_depth": 0,
            "avg_depth": 0.0,
            "quality_score": 0.0,
            "depth_score": 0.0,
            "confidence_score": 0.0,
            "strength_score": 0.0,
            "evidence_score": 0.0,
            "event_count": 0,
            "hypothesis_count": 0,
        }

    # Build graph structure
    graph, event_ids = build_graph_from_hypotheses(hypotheses)

    # Calculate max depth
    max_depth = 0
    avg_depth = 0.0
    path_depths: List[int] = []
    if target_event_id and target_event_id in event_ids:
        # Calculate depth from target using GraphVisualizer utility
        max_depth = GraphVisualizer.find_max_depth_from_node(
            graph, target_event_id, set()
        )

        # Calculate average depth across all causal chains from target
        def dfs_collect_depths(node: str, depth: int, visiting: set):
            # Prevent cycles in the current path
            if node in visiting:
                # Treat cycle as a terminal for averaging purposes
                path_depths.append(depth)
                return
            visiting.add(node)

            sources = graph.get(node, [])
            if not sources:
                # Leaf (root cause) reached
                path_depths.append(depth)
            else:
                for src in sources:
                    dfs_collect_depths(src, depth + 1, visiting)
            visiting.remove(node)

        dfs_collect_depths(target_event_id, 0, set())
        if path_depths:
            avg_depth = sum(path_depths) / len(path_depths)

    # Calculate component scores
    avg_confidence = sum(h.confidence for h in hypotheses) / len(hypotheses)
    avg_strength = sum(h.strength for h in hypotheses) / len(hypotheses)
    depth_score = min(max_depth / min_depth_for_full_score, 1.0)
    evidence_score = sum(1 for h in hypotheses if h.evidence_article_ids) / len(
        hypotheses
    )

    # Overall quality (weighted average)
    quality_score = (
        depth_score * 0.4
        + avg_confidence * 0.3
        + avg_strength * 0.2
        + evidence_score * 0.1
    )

    return {
        "max_depth": max_depth,
        "avg_depth": round(avg_depth, 2),
        "quality_score": round(quality_score, 2),
        "depth_score": round(depth_score, 2),
        "confidence_score": round(avg_confidence, 2),
        "strength_score": round(avg_strength, 2),
        "evidence_score": round(evidence_score, 2),
        "event_count": len(event_ids),
        "hypothesis_count": len(hypotheses),
    }


def analyze_graph_structure(
    hypotheses: List[CausalHypothesis], target_event_id: str = None
) -> Dict[str, Any]:
    """Analyze causal graph structure and compute detailed metrics.

    This is a more comprehensive analysis function that includes
    all metrics from calculate_graph_quality plus additional structural info.

    Args:
        hypotheses: List of causal hypotheses
        target_event_id: Optional target event ID

    Returns:
        Dictionary with comprehensive graph analysis including:
        - All metrics from calculate_graph_quality
        - leaf_events: Number of root cause events
        - with_evidence: Number of hypotheses with evidence
        - Additional structural metrics
    """
    quality_metrics = calculate_graph_quality(hypotheses, target_event_id)

    # Build graph for additional analysis
    graph, event_ids = build_graph_from_hypotheses(hypotheses)

    # Find leaf nodes (root causes)
    all_targets = set(graph.keys())
    all_sources = set()
    for sources in graph.values():
        all_sources.update(sources)
    leaf_nodes = all_sources - all_targets

    # Count hypotheses with evidence
    with_evidence = sum(1 for h in hypotheses if h.evidence_article_ids)

    return {
        **quality_metrics,
        "leaf_events": len(leaf_nodes),
        "with_evidence": with_evidence,
        "status": "analyzed",
    }


def infer_target_event_id(hypotheses: List[CausalHypothesis]) -> Optional[str]:
    """Infer the target event ID (sink node) from a list of hypotheses.

    The target event in a causal graph is the effect (sink), and roots are causes.
    So we look for events that are targets in hypotheses but never sources.

    Args:
        hypotheses: List of causal hypotheses

    Returns:
        Inferred target event ID, or None if ambiguous/circular/empty
    """
    if not hypotheses:
        return None

    all_targets = set(h.target_event_id for h in hypotheses)
    all_sources = set(h.source_event_id for h in hypotheses)

    # Candidates are targets that are never sources
    candidates = list(all_targets - all_sources)

    if candidates:
        # Pick the first candidate (usually there should only be one sink)
        return candidates[0]

    # If no sink found (e.g. cycles), we might want to return None or fallback
    # For now, return None and let caller decide fallback strategy
    return None


def resolve_target_event_id(
    question: Optional["Question"],
    db: Any,
    hypotheses: Optional[List[CausalHypothesis]] = None,
) -> Optional[str]:
    """Resolve the target event ID (outcome) for a question.

    Standardized logic that prioritizes:
    1. outcome_event_ids (checking for actual outcome)
    2. legacy target_event_id
    3. inferred from graph structure

    Args:
        question: The Question object (optional)
        db: Database interface (must have .get(Event, id) method)
        hypotheses: Optional list of hypotheses for inference fallback

    Returns:
        Target event ID or None
    """
    from src.domain.models import Event

    target_event_id = None

    if question:
        # Priority 1: Check outcome_event_ids (new standard)
        if question.outcome_event_ids:
            # Try to find actual outcome specifically
            actual_outcomes = [
                eid
                for eid in question.outcome_event_ids
                if (evt := db.get(Event, eid)) and evt.is_actual_outcome
            ]
            if actual_outcomes:
                target_event_id = actual_outcomes[0]
            elif question.outcome_event_ids:
                target_event_id = question.outcome_event_ids[0]

        # Priority 2: Legacy target_event_id
        if not target_event_id and question.target_event_id:
            target_event_id = question.target_event_id

    # Priority 3: Infer from graph
    if not target_event_id and hypotheses:
        target_event_id = infer_target_event_id(hypotheses)

    return target_event_id
