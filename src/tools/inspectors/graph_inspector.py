"""Graph inspector tool - analyze causal graph structure and depth."""

from typing import Optional, Dict, List, Set
from collections import defaultdict

from src.tools.base.database_mixin import DatabaseAwareTool
from src.domain.models import CausalHypothesis, Event
from src.analysis.graph_visualization import GraphVisualizer
from src.services.temporal_filter_service import TemporalFilterService
from src.analysis.event_analysis import (
    analyze_event_timeline,
    identify_event_gaps,
    calculate_event_temporal_quality,
    get_event_temporal_recommendation,
)
from src.tools.inspectors.formatting import (
    InspectorReportBuilder,
    format_inspector_header,
)


class GraphInspectorTool(DatabaseAwareTool):
    """Inspect causal graph structure to evaluate depth and quality.

    Computes a quality score (0–1) weighted: depth 40%, confidence 30%,
    strength 20%, evidence 10%. Depth saturates at min_required_depth (default 3).
    Also analyses temporal distribution of events within the evidence window.

    See docs/inspectors.md for full scoring criteria and thresholds.
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

    If max_depth < min_required_depth (see EvidenceSatisfactionConfig.min_graph_depth), your graph is TOO SHALLOW - you need to:
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
        from src.analysis.graph_analysis import (
            analyze_graph_structure,
            resolve_target_event_id,
        )

        target_event_id = resolve_target_event_id(
            question, self.db, question_hypotheses
        )

        graph_stats = analyze_graph_structure(question_hypotheses, target_event_id)
        graph_stats["question_id"] = self.question_id  # Add question_id for context

        # Get all unique event IDs in hypotheses
        event_ids = set()
        for hyp in question_hypotheses:
            event_ids.add(hyp.source_event_id)
            event_ids.add(hyp.target_event_id)

        # Fetch event details
        events = {eid: self.db.get(Event, eid) for eid in event_ids}

        # Ensure target event is in the events list (even if orphan)
        if target_event_id and target_event_id not in events:
            events[target_event_id] = self.db.get(Event, target_event_id)

        # Analyze temporal coverage of events
        event_list = [e for e in events.values() if e is not None]
        temporal_data = None
        temporal_quality = None
        temporal_gaps = []

        if question and event_list:
            # Filter events by time window
            window_start, window_end = TemporalFilterService.get_evidence_window(
                question.resolution_date, question.estimated_start_time
            )
            filtered_events = TemporalFilterService.filter_by_window(
                event_list, window_start, window_end, date_field="occurred_date"
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
            # Check outcome events
            for oid in question.outcome_event_ids or []:
                if oid not in event_ids:
                    orphan_event_ids.add(oid)
            # Check legacy target event
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
            target_event_id,
        )

        return output

    def _get_recommendation(self, stats: Dict) -> str:
        """Generate recommendation based on graph statistics."""
        from src.services.question_monitor_service import QuestionMonitorService

        monitor = QuestionMonitorService(self.db)
        return GraphVisualizer.get_recommendation(
            stats["max_depth"],
            stats["quality_score"],
            min_depth=monitor.config.min_graph_depth,
            min_quality=monitor.config.min_confidence,
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
            Dict with impact analysis and coverage info, or None if no
            non-outcome events exist yet.
        """
        from src.domain.models.event_outcome_impact import (
            EventOutcomeImpact,
            ImpactDirection,
        )

        # Find all non-outcome events for this question to compute coverage
        all_events = self.db.get_many(Event)
        question_events = [
            e
            for e in all_events
            if getattr(e, "extracted_for_question_id", None) == self.question_id
            and not getattr(e, "is_outcome", False)
        ]

        impacts = self.db.get_many(
            EventOutcomeImpact, filters={"question_id": self.question_id}
        )

        # Events that have at least one impact recorded
        events_with_impacts = {imp.event_id for imp in impacts}

        # Events missing impacts
        events_missing_impacts = [
            e for e in question_events if e.id not in events_with_impacts
        ]

        if not impacts and not question_events:
            return None

        # Group by outcome event
        by_outcome = {}
        for impact in impacts:
            outcome_id = impact.outcome_event_id
            outcome_event = self.db.get(Event, outcome_id)
            if not outcome_event:
                continue  # Ignore impacts where the outcome event cannot be retrieved

            if outcome_id not in by_outcome:
                by_outcome[outcome_id] = {
                    "outcome_title": outcome_event.title,
                    "outcome_scenario": outcome_event.outcome_scenario.value
                    if outcome_event.outcome_scenario
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

        total_non_outcome = len(question_events)
        covered = len(events_with_impacts & {e.id for e in question_events})

        return {
            "impact_count": len(impacts),
            "outcomes_analyzed": len(by_outcome),
            "by_outcome": by_outcome,
            "coverage": {
                "total_non_outcome_events": total_non_outcome,
                "events_with_impacts": covered,
                "events_missing_impacts": [
                    {"id": e.id, "title": e.title}
                    for e in events_missing_impacts
                ],
            },
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
        target_event_id: Optional[str] = None,
    ) -> str:
        """Format the graph as a visual text representation."""
        builder = InspectorReportBuilder("RELATIONAL GRAPH INSPECTOR")

        # Question info
        if question:
            builder.add_kv("Question", f"{question.question_text[:80]}...")
            builder.add_kv("Question ID", self.question_id)
            builder.add_line()

        # Visual graph section
        builder.add_section_header("RELATIONAL GRAPH STRUCTURE")

        # Determine target if not passed
        if not target_event_id and question:
            from src.analysis.graph_analysis import resolve_target_event_id

            target_event_id = resolve_target_event_id(question, self.db)

        if target_event_id and target_event_id in events:
            tree_lines = self._build_causal_tree(
                target_event_id, events, graph, hypothesis_map, set()
            )
            for line in tree_lines:
                builder.add_line(line)
        else:
            builder.add_line(
                "⚠ No target event specified. Showing all relational links:"
            )
            builder.add_line()
            for target_id, source_ids in graph.items():
                target_event = events.get(target_id)
                target_desc = self._truncate(
                    target_event.description if target_event else target_id, 50
                )
                builder.add_line(f"▸ {target_desc}", indent=2)
                for source_id in source_ids:
                    source_event = events.get(source_id)
                    source_desc = self._truncate(
                        source_event.description if source_event else source_id, 45
                    )
                    hyp = hypothesis_map.get((source_id, target_id))
                    conf = f"[conf: {hyp.confidence:.1f}]" if hyp else ""
                    builder.add_line(f"└─→ {source_desc} {conf}", indent=4)
                builder.add_line()

        # Temporal coverage section
        if temporal_data and temporal_data.get("has_dates"):
            builder.add_section_header("EVENT TEMPORAL COVERAGE")

            builder.add_time_window(
                question.resolution_date, question.estimated_start_time, indent=0
            )

            # Coverage range
            earliest = temporal_data.get("earliest")
            latest = temporal_data.get("latest")
            if earliest and latest:
                builder.add_coverage_range(
                    earliest,
                    latest,
                    question.resolution_date,
                    question.estimated_start_time,
                    item_type="Event",
                )
                builder.add_line()

            # Monthly bar chart
            builder.add_monthly_bar_chart(
                temporal_data.get("monthly", {}), item_type="Events"
            )

            # Temporal gaps
            if temporal_gaps:
                builder.add_timeline_gaps(
                    temporal_gaps, min_gap_label=">30 days", max_display=3, compact=True
                )

            # Metrics
            if temporal_quality:
                metrics = {
                    "Temporal Quality": temporal_quality["temporal_score"],
                    "Coverage Score": temporal_quality["coverage_score"],
                    "Distribution": temporal_quality["distribution_score"],
                }
                if temporal_quality["gap_severity"] > 0:
                    metrics["Gap Severity"] = temporal_quality["gap_severity"]
                builder.add_metrics(metrics)
                builder.add_line()

        elif temporal_data is not None:
            builder.add_line(
                "⚠ No event dates available - cannot assess temporal coverage", indent=2
            )
            builder.add_line()

        # Outcome impact section
        if outcome_impacts:
            builder.add_section_header("OUTCOME IMPACT ANALYSIS")
            builder.add_kv("Total Impacts", outcome_impacts["impact_count"], indent=2)
            builder.add_kv(
                "Outcomes Analyzed", outcome_impacts["outcomes_analyzed"], indent=2
            )

            # Impact coverage
            coverage = outcome_impacts.get("coverage", {})
            total_events = coverage.get("total_non_outcome_events", 0)
            covered_events = coverage.get("events_with_impacts", 0)
            missing = coverage.get("events_missing_impacts", [])

            if total_events > 0:
                pct = (covered_events / total_events) * 100
                builder.add_kv(
                    "Impact Coverage",
                    f"{covered_events}/{total_events} events ({pct:.0f}%)",
                    indent=2,
                )
            builder.add_line()

            if missing:
                builder.add_line(
                    f"!! MISSING IMPACTS: {len(missing)} event(s) have no outcome impact recorded:",
                    indent=2,
                )
                for item in missing[:10]:
                    title_short = self._truncate(item["title"], 50)
                    builder.add_line(f"- {title_short} ({item['id']})", indent=4)
                if len(missing) > 10:
                    builder.add_line(f"  ... and {len(missing) - 10} more", indent=4)
                builder.add_line(
                    "-> Call record_outcome_impact for each missing event.",
                    indent=4,
                )
                builder.add_line()

            for outcome_id, outcome_data in outcome_impacts["by_outcome"].items():
                outcome_title = outcome_data["outcome_title"]
                scenario = outcome_data["outcome_scenario"]
                scenario_label = f" ({scenario})" if scenario else ""

                builder.add_line(f"Outcome: {outcome_title}{scenario_label}", indent=2)
                builder.add_line("─" * 60, indent=2)

                # Positive impacts
                if outcome_data["positive_impacts"]:
                    builder.add_line(
                        f"✓ POSITIVE impacts ({len(outcome_data['positive_impacts'])}):",
                        indent=4,
                    )
                    for imp in sorted(
                        outcome_data["positive_impacts"],
                        key=lambda x: x["magnitude"],
                        reverse=True,
                    )[:3]:
                        title_short = self._truncate(imp["event_title"], 45)
                        builder.add_line(f"• {title_short}", indent=6)
                        builder.add_line(
                            f"mag: {imp['magnitude']:.2f}, conf: {imp['confidence']:.2f}",
                            indent=8,
                        )

                # Negative impacts
                if outcome_data["negative_impacts"]:
                    builder.add_line(
                        f"✗ NEGATIVE impacts ({len(outcome_data['negative_impacts'])}):",
                        indent=4,
                    )
                    for imp in sorted(
                        outcome_data["negative_impacts"],
                        key=lambda x: x["magnitude"],
                        reverse=True,
                    )[:3]:
                        title_short = self._truncate(imp["event_title"], 45)
                        builder.add_line(f"• {title_short}", indent=6)
                        builder.add_line(
                            f"mag: {imp['magnitude']:.2f}, conf: {imp['confidence']:.2f}",
                            indent=8,
                        )

                builder.add_line()

        # Orphan events section
        if orphan_events:
            builder.add_section_header("⚠ ORPHAN EVENTS (Related but Disconnected)")
            builder.add_line(
                f"Found {len(orphan_events)} event(s) related to this question but not connected via relational hypotheses:"
            )
            builder.add_line()

            for event_id, event in orphan_events.items():
                if event:
                    desc = self._truncate(event.title, 55)

                    if getattr(event, "is_outcome", False):
                        if getattr(event, "is_actual_outcome", False):
                            builder.add_line(f"🔴 {desc} [ACTUAL OUTCOME]", indent=2)
                            builder.add_line(f"ID: {event_id}", indent=5)
                            builder.add_line(
                                f"→ Fix: call causal_reasoner with target_event_id='{event_id}' to connect your last intermediate event to this outcome.",
                                indent=5,
                            )
                        else:
                            builder.add_line(
                                f"🔴 {desc} [non-ground-truth outcome]", indent=2
                            )
                            builder.add_line(f"ID: {event_id}", indent=5)
                            builder.add_line(
                                "→ No connection needed (not the actual outcome).",
                                indent=5,
                            )
                    else:
                        builder.add_line(f"🔴 {desc}", indent=2)
                        builder.add_line(f"ID: {event_id}", indent=5)
                        builder.add_line(
                            "→ Fix: consider if this event belongs in the graph. If so, call causal_reasoner to connect it.",
                            indent=5,
                        )
                else:
                    builder.add_line(f"🔴 {event_id} (event not found)", indent=2)
                builder.add_line()

        # Causal chains section
        builder.add_section_header("RELATIONAL CHAINS (Root → Target)")
        if target_event_id:
            chains = self._find_all_causal_chains(
                target_event_id, events, graph, hypothesis_map
            )
            if chains:
                for i, chain in enumerate(chains[:5], 1):
                    builder.add_line(f"Chain {i} (depth: {len(chain) - 1}):")
                    for j, (event_id, hyp) in enumerate(chain):
                        event = events.get(event_id)
                        desc = self._truncate(
                            event.description if event else event_id, 55
                        )
                        _ = "  " * j

                        if j == 0:
                            icon = "🌱"
                        elif j == len(chain) - 1:
                            icon = "🎯"
                        else:
                            icon = "⚡"

                        builder.add_line(f"{icon} {desc}", indent=2 + (j * 2))

                        if hyp and j < len(chain) - 1:
                            evidence_str = (
                                f"[{len(hyp.evidence_article_ids)} articles]"
                                if hyp.evidence_article_ids
                                else "[no evidence]"
                            )
                            builder.add_line(
                                f"└─ conf: {hyp.confidence:.1f}, strength: {hyp.strength:.1f} {evidence_str}",
                                indent=5 + (j * 2),
                            )
                    builder.add_line()
            else:
                builder.add_line("No complete relational chains found.", indent=2)
                builder.add_line()

        # Statistics section
        builder.add_section_header("GRAPH STATISTICS")
        stats_map = {
            "Events": stats["event_count"],
            "Hypotheses": stats["hypothesis_count"],
            "Max Depth": f"{stats['max_depth']} levels",
            "Depth Score": stats["depth_score"],
            "Quality Score": stats["quality_score"],
        }
        builder.add_metrics(stats_map)
        if orphan_events:
            builder.add_kv("Orphan Events", f"{len(orphan_events)} ⚠", indent=2)
        builder.add_line()

        # Recommendations
        from src.services.question_monitor_service import QuestionMonitorService

        monitor = QuestionMonitorService(self.db)
        missing_reqs = monitor.evaluate_graph_requirements(
            stats["max_depth"], stats["event_count"]
        )

        builder.add_section_header("RECOMMENDATION")
        graph_recommendation = self._get_recommendation(stats)
        builder.add_kv("Graph", graph_recommendation, indent=2)

        if any("events" in r for r in missing_reqs):
            needed = monitor.config.min_graph_events - stats["event_count"]
            builder.add_kv(
                "Events",
                f"Only {stats['event_count']}/{monitor.config.min_graph_events} events. "
                f"Identify {needed} more intermediate events to reach the minimum.",
                indent=2,
            )

        if temporal_data and temporal_quality:
            temporal_recommendation = get_event_temporal_recommendation(
                temporal_quality,
                temporal_gaps or [],
                temporal_data,
                question.estimated_start_time if question else None,
            )
            builder.add_kv("Temporal", temporal_recommendation, indent=2)

        if outcome_impacts:
            coverage = outcome_impacts.get("coverage", {})
            total = coverage.get("total_non_outcome_events", 0)
            covered = coverage.get("events_with_impacts", 0)
            if total > 0:
                pct = covered / total
                if pct < 1.0:
                    missing_count = total - covered
                    impact_rec = (
                        f"Impact coverage {covered}/{total} ({pct:.0%}). "
                        f"Call record_outcome_impact for the {missing_count} missing event(s)."
                    )
                    builder.add_kv("Impact", impact_rec, indent=2)

        builder.add_line()

        return builder.build()

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
