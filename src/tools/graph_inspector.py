"""Graph inspector tool - analyze causal graph structure and depth."""

import json
from typing import Optional, Dict, List, Set
from collections import defaultdict

from smolagents import Tool
from src.domain.models import CausalHypothesis, Event
from src.core.database import GenericDatabase
from src.utils.graph_visualization import GraphVisualizer
from src.utils.event_analysis import (
    filter_events_by_time_window,
    analyze_event_timeline,
    identify_event_gaps,
    calculate_event_temporal_quality,
    get_event_temporal_recommendation
)
from src.utils.date_utils import ensure_timezone_aware
from src.utils.formatting_utils import (
    format_inspector_header,
    format_section_header,
    format_time_window,
    format_coverage_range,
    render_monthly_bar_chart,
    format_timeline_gaps,
    format_metric_line
)


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
    - Temporal coverage analysis (event timeline distribution)
    - Causal chain depths and paths
    - Evidence support for each hypothesis
    - Quality metrics and recommendations

    If max_depth < 2, your graph is TOO SHALLOW - you need to:
    1. Pick the most important immediate causes
    2. Ask "What caused THIS?" for each
    3. Create intermediate events using event_identifier
    4. Link them with causal_reasoner: Root → Intermediate → Target

    Returns:
        str: Multi-section text with visual graph, temporal coverage, causal chains, and statistics
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

        # Build graph structure and statistics using shared utility
        from src.utils.graph_analysis import analyze_graph_structure

        target_event_id = question.target_event_id if question else None
        graph_stats = analyze_graph_structure(question_hypotheses, target_event_id)
        graph_stats['question_id'] = self.question_id  # Add question_id for context
        
        # Get all unique event IDs in hypotheses
        event_ids = set()
        for hyp in question_hypotheses:
            event_ids.add(hyp.source_event_id)
            event_ids.add(hyp.target_event_id)

        # Fetch event details
        events = {eid: self.db.get(Event, eid) for eid in event_ids}

        # Analyze temporal coverage of events
        event_list = [e for e in events.values() if e is not None]
        temporal_data = None
        temporal_quality = None
        temporal_gaps = []

        if question and event_list:
            # Filter events by time window
            filtered_events = filter_events_by_time_window(
                event_list,
                question.resolution_date,
                question.estimated_start_time
            )

            # Analyze event timeline
            temporal_data = analyze_event_timeline(
                filtered_events,
                question.resolution_date,
                coverage_start=question.estimated_start_time
            )

            # Identify temporal gaps
            temporal_gaps = identify_event_gaps(temporal_data)

            # Calculate temporal quality
            temporal_quality = calculate_event_temporal_quality(
                filtered_events,
                temporal_data,
                temporal_gaps,
                coverage_start=question.estimated_start_time
            )
        
        # Find orphan events (related to question but not in any hypothesis)
        orphan_event_ids = set()
        if question:
            # Check target event
            if question.target_event_id and question.target_event_id not in event_ids:
                orphan_event_ids.add(question.target_event_id)
            # Check related events
            for rel_id in (question.related_event_ids or []):
                if rel_id not in event_ids:
                    orphan_event_ids.add(rel_id)
        
        # Fetch orphan event details
        orphan_events = {eid: self.db.get(Event, eid) for eid in orphan_event_ids}
        
        # Build adjacency list for visualization
        graph = defaultdict(list)
        hypothesis_map = {}  # (source, target) -> hypothesis
        for hyp in question_hypotheses:
            graph[hyp.target_event_id].append(hyp.source_event_id)
            hypothesis_map[(hyp.source_event_id, hyp.target_event_id)] = hyp
        
        # Generate visualization
        output = self._format_graph_visualization(
            question, events, graph, hypothesis_map, graph_stats, orphan_events,
            temporal_data, temporal_quality, temporal_gaps
        )

        return output


    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics."""
        return GraphVisualizer.get_recommendation(stats["max_depth"], stats["quality_score"])

    def _format_empty_graph(self) -> str:
        """Format output for empty graph."""
        header = format_inspector_header("CAUSAL GRAPH INSPECTOR")
        return f"""{header}
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
        stats: Dict,
        orphan_events: Dict[str, Event],
        temporal_data: Optional[Dict] = None,
        temporal_quality: Optional[Dict] = None,
        temporal_gaps: Optional[List[Dict]] = None
    ) -> str:
        """Format the graph as a visual text representation.

        Args:
            question: Question object
            events: Event ID to Event object mapping
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping
            stats: Graph statistics
            orphan_events: Orphan event ID to Event object mapping

        Returns:
            Formatted multi-section text
        """
        sections = []

        # Header
        sections.append(format_inspector_header("CAUSAL GRAPH INSPECTOR"))

        # Question info
        if question:
            sections.append(f"Question: {question.question_text[:80]}...")
            sections.append(f"Question ID: {self.question_id}")
            sections.append("")

        # Visual graph section
        sections.extend(format_section_header("CAUSAL GRAPH STRUCTURE"))
        
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
        
        # Temporal coverage section
        if temporal_data and temporal_data.get("has_dates"):
            sections.extend(format_section_header("EVENT TEMPORAL COVERAGE"))

            # Time window display
            sections.extend(format_time_window(
                question.resolution_date,
                question.estimated_start_time
            ))

            # Coverage range
            earliest = temporal_data.get('earliest')
            latest = temporal_data.get('latest')
            if earliest and latest:
                sections.extend(format_coverage_range(
                    earliest,
                    latest,
                    question.resolution_date,
                    question.estimated_start_time,
                    temporal_data['span_days'],
                    item_type="Event"
                ))

            sections.append("")

            # Monthly bar chart
            sections.extend(render_monthly_bar_chart(
                temporal_data.get('monthly', {}),
                item_type="Events"
            ))

            # Temporal gaps (compact format)
            if temporal_gaps:
                sections.extend(format_timeline_gaps(
                    temporal_gaps,
                    min_gap_label=">30 days",
                    max_display=3,
                    compact=True
                ))

            # Temporal quality metrics
            if temporal_quality:
                sections.append(format_metric_line("Temporal Quality", temporal_quality['temporal_score']))
                sections.append(format_metric_line("Coverage Score", temporal_quality['coverage_score']))
                sections.append(format_metric_line("Distribution", temporal_quality['distribution_score']))
                if temporal_quality['gap_severity'] > 0:
                    sections.append(format_metric_line("Gap Severity", temporal_quality['gap_severity'], " (penalty)"))
                sections.append("")
        elif temporal_data is not None:
            sections.extend(format_section_header("EVENT TEMPORAL COVERAGE"))
            sections.append("  ⚠ No event dates available - cannot assess temporal coverage")
            sections.append("")

        # Orphan events section
        if orphan_events:
            sections.extend(format_section_header("⚠ ORPHAN EVENTS (Related but Disconnected)"))
            sections.append(f"Found {len(orphan_events)} event(s) related to this question but")
            sections.append("not connected via causal hypotheses:")
            sections.append("")
            for event_id, event in orphan_events.items():
                if event:
                    desc = self._truncate(event.description, 55)
                    sections.append(f"  🔴 {desc}")
                    sections.append(f"     ID: {event_id}")
                    if event.occurred_date:
                        sections.append(f"     Date: {event.occurred_date}")
                else:
                    sections.append(f"  🔴 {event_id} (event not found in database)")
                sections.append("")
            sections.append("RECOMMENDATION:")
            sections.append("  → Consider creating causal hypotheses linking these events")
            sections.append("  → Use causal_reasoner tool to establish relationships")
            sections.append("  → These events may provide missing context or root causes")
        
        # Causal chains section
        sections.extend(format_section_header("CAUSAL CHAINS (Root → Target)"))
        
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
        sections.extend(format_section_header("GRAPH STATISTICS"))
        sections.append(f"  Events:           {stats['event_count']}")
        sections.append(f"  Hypotheses:       {stats['hypothesis_count']}")
        sections.append(f"  Max Depth:        {stats['max_depth']} levels")
        sections.append(f"  Depth Score:      {stats['depth_score']:.1f}")
        sections.append(f"  Leaf Events:      {stats['leaf_events']} (root causes)")
        sections.append(f"  Avg Confidence:   {stats['confidence_score']:.2f}")
        sections.append(f"  Avg Strength:     {stats['strength_score']:.2f}")
        sections.append(f"  With Evidence:    {stats['with_evidence']}/{stats['hypothesis_count']}")
        sections.append(f"  Quality Score:    {stats['quality_score']:.2f}")
        if orphan_events:
            sections.append(f"  Orphan Events:    {len(orphan_events)} ⚠")
        if temporal_quality:
            sections.append(f"  Temporal Score:   {temporal_quality['temporal_score']:.2f}")
        sections.append("")

        # Recommendations
        sections.extend(format_section_header("RECOMMENDATION"))

        # Graph structure recommendation
        graph_recommendation = self._get_recommendation(stats)
        sections.append(f"  Graph: {graph_recommendation}")

        # Temporal coverage recommendation
        if temporal_data and temporal_quality:
            temporal_recommendation = get_event_temporal_recommendation(
                temporal_quality,
                temporal_gaps or [],
                temporal_data,
                question.estimated_start_time if question else None
            )
            sections.append(f"  Temporal: {temporal_recommendation}")

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

