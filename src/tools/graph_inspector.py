"""Graph inspector tool - analyze causal graph structure and depth."""

from typing import Optional, Dict, List, Set
from collections import defaultdict

from src.tools.database_mixin import DatabaseAwareTool
from src.domain.models import CausalHypothesis, Event
from src.utils.graph_visualization import GraphVisualizer
from src.utils.event_analysis import (
    filter_events_by_time_window,
    analyze_event_timeline,
    identify_event_gaps,
    calculate_event_temporal_quality,
    get_event_temporal_recommendation,
)
from src.utils.formatting_utils import (
    format_inspector_header,
    format_section_header,
    format_time_window,
    format_coverage_range,
    render_monthly_bar_chart,
    format_timeline_gaps,
    format_metric_line,
)


class GraphInspectorTool(DatabaseAwareTool):
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
    description = """Visualize and analyze the relational graph structure for a question.

    Use this tool to see a visual representation of your relational explanation:
    - Text-based tree showing relational chains (Root → Intermediate → Target)
    - Event details with descriptions
    - Temporal coverage analysis (event timeline distribution)
    - Relational chain depths and paths
    - Evidence support for each hypothesis
    - Quality metrics and recommendations

    If max_depth < 2, your graph is TOO SHALLOW - you need to:
    1. Pick the most important immediate causes
    2. Ask "What caused THIS?" for each
    3. Create intermediate events using event_identifier
    4. Link them with causal_reasoner: Root → Intermediate → Target

    Returns:
        str: Multi-section text with visual graph, temporal coverage, relational chains, and statistics
    """
    inputs = {}
    output_type = "string"

    def __init__(self, question_id, db_path: str = "worldreasoner.db"):
        """Initialize the graph inspector.

        Args:
            question_id: Question ID for filtering graph elements
            db_path: Path to database
        """
        super().__init__(db_path=db_path, ensure_tables=[CausalHypothesis, Event])
        self.question_id = question_id

    def forward(self) -> str:
        """Visualize and analyze graph structure for a question.

        Returns:
            Multi-section text with visual graph representation and statistics
        """
        # Get all hypotheses related to this question efficiently
        # queried via discovered_by_question_ids list field being LIKE %qid%
        question_hypotheses = self.db.get_many(
            CausalHypothesis,
            filters={"discovered_by_question_ids__like": f'%"{self.question_id}"%'},
        )

        if not question_hypotheses:
            return self._format_empty_graph()

        # Get the question
        from src.domain.models import Question

        question = self.db.get(Question, self.question_id)

        # Build graph structure and statistics using shared utility
        from src.utils.graph_analysis import (
            analyze_graph_structure,
            infer_target_event_id,
        )

        target_event_id = question.target_event_id if question else None

        # If no target event defined, try to infer it from graph to provide better visualization
        if not target_event_id and question_hypotheses:
            target_event_id = infer_target_event_id(question_hypotheses)

        graph_stats = analyze_graph_structure(question_hypotheses, target_event_id)
        graph_stats["question_id"] = self.question_id  # Add question_id for context

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
                event_list, question.resolution_date, question.estimated_start_time
            )

            # Analyze event timeline
            temporal_data = analyze_event_timeline(
                filtered_events,
                question.resolution_date,
                coverage_start=question.estimated_start_time,
            )

            # Identify temporal gaps
            temporal_gaps = identify_event_gaps(temporal_data)

            # Calculate temporal quality
            temporal_quality = calculate_event_temporal_quality(
                filtered_events,
                temporal_data,
                temporal_gaps,
                coverage_start=question.estimated_start_time,
            )

        # Find orphan events (related to question but not in any hypothesis)
        orphan_event_ids = set()
        if question:
            # Check target event
            if question.target_event_id and question.target_event_id not in event_ids:
                orphan_event_ids.add(question.target_event_id)
            # Check related events
            for rel_id in question.related_event_ids or []:
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

        # Find disconnected subgraphs (components not connected to target)
        disconnected = self._find_disconnected_subgraphs(
            event_ids, graph, target_event_id
        )

        # Get outcome impact summary
        outcome_impacts = self._get_outcome_impact_summary()

        # Generate visualization
        output = self._format_graph_visualization(
            question,
            events,
            graph,
            hypothesis_map,
            graph_stats,
            orphan_events,
            temporal_data,
            temporal_quality,
            temporal_gaps,
            disconnected,
            outcome_impacts,
        )

        return output

    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics."""
        return GraphVisualizer.get_recommendation(
            stats["max_depth"], stats["quality_score"]
        )

    def _format_empty_graph(self) -> str:
        """Format output for empty graph."""
        header = format_inspector_header("RELATIONAL GRAPH INSPECTOR")
        return f"""{header}
Question ID: {self.question_id}

STATUS: Empty Graph
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No relational relationships have been created yet.

RECOMMENDATION:
→ Start by creating a target event (the outcome you're explaining)
→ Identify 2-3 immediate causes using evidence articles
→ For each cause, ask "What caused THIS?" to build deeper chains
"""

    def _get_outcome_impact_summary(self) -> Optional[Dict]:
        """Get summary of event-outcome impacts for this question.

        Returns:
            Dict with impact analysis or None if no impacts found
        """
        from src.domain.models.event_outcome_impact import (
            EventOutcomeImpact,
            ImpactDirection,
        )

        impacts = self.db.get_many(
            EventOutcomeImpact, filters={"question_id": self.question_id}
        )

        if not impacts:
            return None

        # Group by outcome event
        by_outcome = {}
        for impact in impacts:
            outcome_id = impact.outcome_event_id
            if outcome_id not in by_outcome:
                outcome_event = self.db.get(Event, outcome_id)
                by_outcome[outcome_id] = {
                    "outcome_title": outcome_event.title
                    if outcome_event
                    else "Unknown",
                    "outcome_scenario": outcome_event.outcome_scenario.value
                    if outcome_event and outcome_event.outcome_scenario
                    else None,
                    "positive_impacts": [],
                    "negative_impacts": [],
                    "neutral_impacts": [],
                }

            event = self.db.get(Event, impact.event_id)
            impact_info = {
                "event_id": impact.event_id,
                "event_title": event.title if event else "Unknown",
                "event_description": event.description if event else "",
                "magnitude": impact.impact_magnitude,
                "confidence": impact.confidence,
            }

            if impact.impact_direction == ImpactDirection.POSITIVE:
                by_outcome[outcome_id]["positive_impacts"].append(impact_info)
            elif impact.impact_direction == ImpactDirection.NEGATIVE:
                by_outcome[outcome_id]["negative_impacts"].append(impact_info)
            else:
                by_outcome[outcome_id]["neutral_impacts"].append(impact_info)

        return {
            "impact_count": len(impacts),
            "outcomes_analyzed": len(by_outcome),
            "by_outcome": by_outcome,
        }

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
        temporal_gaps: Optional[List[Dict]] = None,
        disconnected: Optional[List[Set[str]]] = None,
        outcome_impacts: Optional[Dict] = None,
    ) -> str:
        """Format the graph as a visual text representation.

        Args:
            question: Question object
            events: Event ID to Event object mapping
            graph: Adjacency list (target -> sources)
            hypothesis_map: (source, target) -> hypothesis mapping
            stats: Graph statistics
            orphan_events: Orphan event ID to Event object mapping
            temporal_data: Temporal coverage data
            temporal_quality: Temporal quality metrics
            temporal_gaps: Temporal gaps in coverage
            disconnected: List of disconnected subgraph event ID sets
            outcome_impacts: Outcome impact analysis summary

        Returns:
            Formatted multi-section text
        """
        sections = []

        # Header
        sections.append(format_inspector_header("RELATIONAL GRAPH INSPECTOR"))

        # Question info
        if question:
            sections.append(f"Question: {question.question_text[:80]}...")
            sections.append(f"Question ID: {self.question_id}")
            sections.append("")

        # Visual graph section
        sections.extend(format_section_header("RELATIONAL GRAPH STRUCTURE"))

        target_event_id = question.target_event_id if question else None
        if target_event_id and target_event_id in events:
            # Build tree from target event
            tree_lines = self._build_causal_tree(
                target_event_id, events, graph, hypothesis_map, set()
            )
            sections.extend(tree_lines)
        else:
            # Show all disconnected components
            sections.append(
                "⚠ No target event specified. Showing all relational links:"
            )
            sections.append("")
            for target_id, source_ids in graph.items():
                target_event = events.get(target_id)
                target_desc = self._truncate(
                    target_event.description if target_event else target_id, 50
                )
                sections.append(f"  ▸ {target_desc}")
                for source_id in source_ids:
                    source_event = events.get(source_id)
                    source_desc = self._truncate(
                        source_event.description if source_event else source_id, 45
                    )
                    hyp = hypothesis_map.get((source_id, target_id))
                    conf = f"[conf: {hyp.confidence:.1f}]" if hyp else ""
                    sections.append(f"    └─→ {source_desc} {conf}")
                sections.append("")

        # Temporal coverage section
        if temporal_data and temporal_data.get("has_dates"):
            sections.extend(format_section_header("EVENT TEMPORAL COVERAGE"))

            # Time window display
            sections.extend(
                format_time_window(
                    question.resolution_date, question.estimated_start_time
                )
            )

            # Coverage range
            earliest = temporal_data.get("earliest")
            latest = temporal_data.get("latest")
            if earliest and latest:
                sections.extend(
                    format_coverage_range(
                        earliest,
                        latest,
                        question.resolution_date,
                        question.estimated_start_time,
                        temporal_data["span_days"],
                        item_type="Event",
                    )
                )

            sections.append("")

            # Monthly bar chart
            sections.extend(
                render_monthly_bar_chart(
                    temporal_data.get("monthly", {}), item_type="Events"
                )
            )

            # Temporal gaps (compact format)
            if temporal_gaps:
                sections.extend(
                    format_timeline_gaps(
                        temporal_gaps,
                        min_gap_label=">30 days",
                        max_display=3,
                        compact=True,
                    )
                )

            # Temporal quality metrics
            if temporal_quality:
                sections.append(
                    format_metric_line(
                        "Temporal Quality", temporal_quality["temporal_score"]
                    )
                )
                sections.append(
                    format_metric_line(
                        "Coverage Score", temporal_quality["coverage_score"]
                    )
                )
                sections.append(
                    format_metric_line(
                        "Distribution", temporal_quality["distribution_score"]
                    )
                )
                if temporal_quality["gap_severity"] > 0:
                    sections.append(
                        format_metric_line(
                            "Gap Severity",
                            temporal_quality["gap_severity"],
                            " (penalty)",
                        )
                    )
                sections.append("")
        elif temporal_data is not None:
            sections.extend(format_section_header("EVENT TEMPORAL COVERAGE"))
            sections.append(
                "  ⚠ No event dates available - cannot assess temporal coverage"
            )
            sections.append("")

        # Outcome impact section
        if outcome_impacts:
            sections.extend(format_section_header("OUTCOME IMPACT ANALYSIS"))
            sections.append(f"  Total Impacts:    {outcome_impacts['impact_count']}")
            sections.append(
                f"  Outcomes Analyzed: {outcome_impacts['outcomes_analyzed']}"
            )
            sections.append("")

            for outcome_id, outcome_data in outcome_impacts["by_outcome"].items():
                outcome_title = outcome_data["outcome_title"]
                scenario = outcome_data["outcome_scenario"]
                scenario_label = f" ({scenario})" if scenario else ""
                sections.append(f"  Outcome: {outcome_title}{scenario_label}")
                sections.append("  " + "─" * 60)

                # Show positive impacts
                if outcome_data["positive_impacts"]:
                    sections.append(
                        f"    ✓ POSITIVE impacts ({len(outcome_data['positive_impacts'])}):"
                    )
                    for imp in sorted(
                        outcome_data["positive_impacts"],
                        key=lambda x: x["magnitude"],
                        reverse=True,
                    )[:3]:
                        title_short = self._truncate(imp["event_title"], 45)
                        sections.append(f"      • {title_short}")
                        sections.append(
                            f"        mag: {imp['magnitude']:.2f}, conf: {imp['confidence']:.2f}"
                        )

                # Show negative impacts
                if outcome_data["negative_impacts"]:
                    sections.append(
                        f"    ✗ NEGATIVE impacts ({len(outcome_data['negative_impacts'])}):"
                    )
                    for imp in sorted(
                        outcome_data["negative_impacts"],
                        key=lambda x: x["magnitude"],
                        reverse=True,
                    )[:3]:
                        title_short = self._truncate(imp["event_title"], 45)
                        sections.append(f"      • {title_short}")
                        sections.append(
                            f"        mag: {imp['magnitude']:.2f}, conf: {imp['confidence']:.2f}"
                        )

                sections.append("")

        # Orphan events section
        if orphan_events:
            sections.extend(
                format_section_header("⚠ ORPHAN EVENTS (Related but Disconnected)")
            )
            sections.append(
                f"Found {len(orphan_events)} event(s) related to this question but"
            )
            sections.append("not connected via relational hypotheses:")
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
            sections.append(
                "  → Consider creating relational hypotheses linking these events"
            )
            sections.append("  → Use causal_reasoner tool to establish relationships")
            sections.append(
                "  → These events may provide missing context or root causes"
            )
            sections.append("")

        # Disconnected subgraphs section
        if disconnected:
            sections.extend(format_section_header("⚠ DISCONNECTED SUBGRAPHS"))
            sections.append(
                f"Found {len(disconnected)} subgraph(s) not connected to the target outcome:"
            )
            sections.append("")
            for i, component in enumerate(disconnected, 1):
                sections.append(f"  Subgraph {i} ({len(component)} events):")
                for event_id in list(component)[:5]:  # Show max 5 events per subgraph
                    event = events.get(event_id)
                    desc = self._truncate(event.description if event else event_id, 50)
                    sections.append(f"    🔸 {desc}")
                if len(component) > 5:
                    sections.append(f"    ... and {len(component) - 5} more")
                sections.append("")
            sections.append("WHY THIS HAPPENS:")
            sections.append(
                "  → These events form causal chains but aren't linked to the target"
            )
            sections.append(
                "  → Missing hypothesis connecting this subgraph to the main graph"
            )
            sections.append("  → May be exploratory chains that need to be integrated")
            sections.append("")
            sections.append("RECOMMENDATION:")
            sections.append(
                "  → Find the event in each subgraph that should link to the target"
            )
            sections.append(
                "  → Use causal_reasoner to create the connecting hypothesis"
            )
            sections.append("")

        # Causal chains section
        sections.extend(format_section_header("RELATIONAL CHAINS (Root → Target)"))

        if target_event_id:
            chains = self._find_all_causal_chains(
                target_event_id, events, graph, hypothesis_map
            )
            if chains:
                for i, chain in enumerate(chains[:5], 1):  # Show top 5 chains
                    sections.append(f"Chain {i} (depth: {len(chain) - 1}):")
                    for j, (event_id, hyp) in enumerate(chain):
                        event = events.get(event_id)
                        desc = self._truncate(
                            event.description if event else event_id, 55
                        )
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
                sections.append("  No complete relational chains found.")
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
        sections.append(
            f"  With Evidence:    {stats['with_evidence']}/{stats['hypothesis_count']}"
        )
        sections.append(f"  Quality Score:    {stats['quality_score']:.2f}")
        if orphan_events:
            sections.append(f"  Orphan Events:    {len(orphan_events)} ⚠")
        if temporal_quality:
            sections.append(
                f"  Temporal Score:   {temporal_quality['temporal_score']:.2f}"
            )
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
                question.estimated_start_time if question else None,
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
        is_last: bool = True,
    ) -> List[str]:
        """Build ASCII tree representation of causal graph."""
        return GraphVisualizer.build_causal_tree(
            event_id,
            events,
            graph,
            hypothesis_map,
            visited,
            get_event_title=lambda e: e.description if e else "",
            prefix=prefix,
            is_last=is_last,
        )

    def _find_all_causal_chains(
        self,
        target_id: str,
        events: Dict[str, Event],
        graph: Dict[str, List[str]],
        hypothesis_map: Dict[tuple, CausalHypothesis],
    ) -> List[List[tuple]]:
        """Find all relational chains from root causes to target."""
        return GraphVisualizer.find_all_causal_chains(
            target_id, events, graph, hypothesis_map
        )

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text to max length with ellipsis."""
        return GraphVisualizer.truncate(text, max_len)

    def _find_disconnected_subgraphs(
        self,
        event_ids: Set[str],
        graph: Dict[str, List[str]],
        target_event_id: Optional[str],
    ) -> List[Set[str]]:
        """Find subgraphs not connected to the target event.

        Uses simple BFS to find connected components, treating the graph
        as undirected (edges go both ways for connectivity purposes).

        Returns:
            List of event ID sets for each disconnected subgraph
        """
        if not target_event_id or not event_ids:
            return []

        # Build undirected adjacency for connectivity check
        undirected = defaultdict(set)
        for target, sources in graph.items():
            for source in sources:
                undirected[target].add(source)
                undirected[source].add(target)

        # BFS from target to find all connected events
        connected = set()
        queue = [target_event_id]
        while queue:
            node = queue.pop(0)
            if node in connected:
                continue
            connected.add(node)
            queue.extend(undirected.get(node, []))

        # Find disconnected events
        disconnected_ids = event_ids - connected
        if not disconnected_ids:
            return []

        # Group disconnected events into their own components
        components = []
        remaining = set(disconnected_ids)
        while remaining:
            # BFS from one disconnected node
            start = next(iter(remaining))
            component = set()
            queue = [start]
            while queue:
                node = queue.pop(0)
                if node in component or node not in remaining:
                    continue
                component.add(node)
                queue.extend(n for n in undirected.get(node, []) if n in remaining)
            components.append(component)
            remaining -= component

        return components
