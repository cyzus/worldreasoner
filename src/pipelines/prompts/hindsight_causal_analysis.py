"""Prompts for hindsight causal analysis using multi-agent system."""

from src.domain.models import Question
from .base import BasePromptGenerator, PromptTemplate


EVIDENCE_AGENT_DESCRIPTION = """
Specialist agent for collecting evidence articles.

Guidelines:
- Be multifaceted - look for causes supporting ground truth AND alternative outcome paths
- Work backwards from resolution date
- Prioritize high-quality sources and diverse perspectives
- Fetch article content and capture correct published dates (all BEFORE resolution date)
- Use article_collector to save articles (target: {min_evidence_articles}+ articles)
- Before submission, use article_inspector to check timeline coverage
- Fill any gaps by collecting more articles from those periods
"""

GRAPH_AGENT_DESCRIPTION = """
Specialist agent for building deep event graphs and analyzing outcome impacts.

Guidelines:
- Call get_question_articles to get article IDs
- Call get_question_events to see existing events and OUTCOME events (look for is_actual_outcome=True in the list)
- When you use event_identifier, its response will now include actual_outcome_event_id. Use this ID for your final causal links.
- If outcomes are provided, use EventDetailsTool to understand them
- Create outcome event(s) (outcome from ground truth) using event_identifier with is_outcome=True if not provided
- Create events with source_article_ids (remember to check the tool output like event ids to see status)
- Identify relationships between events 

⚠️ DATE ACCURACY (CRITICAL):
- NEVER guess or infer event dates. Extract the EXACT date from the article text.
- Look for explicit date mentions in the article (e.g., "on January 15", "last Tuesday", "March 2024").
- The occurred_date MUST be derived from what the article says, NOT from the article's published_date.
- If the article doesn't mention a specific date for the event, use the article's published_date as a conservative estimate and note uncertainty.
- Check the YEAR carefully - articles from 2025 should not produce events dated 2024 unless the article explicitly references a past event.
- After creating each event, CHECK THE TOOL OUTPUT for warnings. If you see DATE ACCURACY WARNINGs, re-examine the source article and correct the date.

EVENT VERIFICATION:
- Each event MUST be directly supported by at least one source article.
- Do NOT create events that are your own inferences or extrapolations - only events explicitly described in articles.
- If an article discusses a general trend without a specific event, DO NOT fabricate a discrete event from it.
- Re-read the relevant article passage before setting the occurred_date.

CRITICAL - CONNECTING TO OUTCOME:
- After building intermediate event chains, you MUST use causal_reasoner to create the FINAL LINK
- The final link connects your last intermediate event(s) to the OUTCOME EVENT
- Example: If you have "Negative Reviews" → "Critics Snub", you need one more link: "Critics Snub" → [OUTCOME EVENT]
- Without this final link, the graph will show Max Depth: 0 and appear disconnected!
- Use the outcome_event_id matching the ground truth (e.g., "Yes" or "No" scenario)

OUTCOME IMPACT ANALYSIS:
- For each significant event, assess its impact on BOTH outcomes (Yes/No or all MCQ options)
- Use the record_outcome_impact tool to record impacts (do NOT use the deprecated outcome_impacts parameter on event_identifier):
  - Call record_outcome_impact for EACH outcome the event impacts
  - direction: "positive" (increases likelihood) or "negative" (decreases likelihood)
  - magnitude: 0.0-1.0 (0.5=moderate, 0.7+=strong, 1.0=decisive)
  - confidence: 0.0-1.0 (your certainty in this assessment)
  - reasoning: Explain WHY and HOW this event impacts the outcome
- Consider: An event making one outcome more likely often makes the opposite less likely
- Focus on events with magnitude >= 0.5 (significant impacts)

FINAL VERIFICATION:
- Use graph_inspector to check the quality, depth, and outcome impacts
- If Max Depth is 0, you have NOT connected to the outcome - go back and add the final link!
- If you made a mistake (created an event with wrong dates or created a circular link), use delete_event or delete_hypothesis to prune the bad data.
"""

MANAGER_AGENT_DESCRIPTION = """Your task: Make a comprehensive event analysis for this question with hindsight.

NOTE: the question has already been resolved on {resolution_date} with known ground truth.

QUESTION: {question_text}
RESOLUTION DATE: {resolution_date}
GROUND TRUTH (the KNOWN outcome): {ground_truth}

AVAILABLE OUTCOME EVENTS (pre-created for this question):
{outcome_events_info}
{market_turning_points_section}
When recording outcome impacts for events, use the outcome_event_ids listed above.

PROCESS:

1. COLLECT EVIDENCE:
   Call evidence_collector to gather relevant articles:
   - collect and store relevant evidence to db using article_collector
   - Time window: {window_start} to {resolution_date} ({actual_window_days} days)
   - Target: {min_evidence_articles}+ high-quality articles across different dates
   - Use article_inspector to verify coverage; if insufficient, broaden search
   {turning_points_evidence_hint}
MANAGER AGENT: Inspect the evidence/article collection yourself. If insufficient, repeat step 1.

NOTE - if evidence collection constantly fails, there's no way you can build a event graph. You should keep trying until you get enough evidence.

2. WRITE CAUSAL EXPLANATION:
   With hindsight (ground truth: {ground_truth}), write a detailed NL explanation
   of HOW the outcome came about based on your collected evidence. 
   Follow the explanation format exactly:
   - For each significant event: "Event Title occurred on YYYY-MM-DD [art_id]. Description..."
   - Explicit causal language between events (e.g. "This caused/triggered [Next Event]")
   - Outcome clearly identified: "This resulted in [OutcomeEventTitle], which is the actual outcome."
   - Impact on each possible outcome: "Impact on Option A: positive - because..."
   
   Call save_explanation to store it. The GraphBuilderAgent will read this explanation later
   to build the structured graph.
"""


class HindsightCausalAnalysisPrompts(BasePromptGenerator[Question]):
    """Prompts for building deep causal graphs with HindsightAgent."""

    # Template for agent prompt
    AGENT_TEMPLATE = PromptTemplate(
        template=MANAGER_AGENT_DESCRIPTION,
        required_vars=[
            "question_text",
            "resolution_date",
            "window_start",
            "actual_window_days",
            "ground_truth",
            "outcome_events_info",
            "market_turning_points_section",
            "turning_points_evidence_hint",
            "min_graph_depth",
            "min_evidence_articles",
            "confidence_threshold",
        ],
    )

    def format_item(self, item: Question, idx: int, **context) -> str:
        """Format a single question for the prompt.

        Args:
            item: Question to format
            idx: Index of the question (not used for this prompt)
            **context: Additional context (not used)

        Returns:
            Formatted question string
        """
        return f"{idx}. {item.question_text}"

    def get_instruction(self, **kwargs) -> str:
        """Generate instruction for HindsightAgent (required by base class).

        This is an alias for get_agent_prompt() to satisfy the abstract base class.

        Args:
            **kwargs: All arguments passed to get_agent_prompt()

        Returns:
            Formatted agent prompt string
        """
        return self.get_agent_prompt(**kwargs)

    def get_agent_prompt(
        self,
        question: Question,
        min_evidence_articles: int,
        evidence_window_days: int,
        min_graph_depth: int,
        confidence_threshold: float,
        outcome_events: list = None,
        turning_points: list = None,
        lead_changes: list = None,
        **kwargs,
    ) -> str:
        """Generate prompt for HindsightAgent to build deep causal graph.

        Uses two-tier evidence window approach:
        1. If question has estimated_start_time: use [estimated_start_time, resolution_date]
        2. Fallback: use [resolution_date - evidence_window_days, resolution_date]

        Args:
            question: Question to analyze
            min_graph_depth: Minimum causal chain depth required
            evidence_window_days: Days before resolution to collect evidence if no estimated_start_time
            min_evidence_articles: Minimum evidence articles needed
            confidence_threshold: Minimum confidence for causal links
            outcome_events: List of pre-created outcome Event objects
            turning_points: Optional list of detected market turning points from price analysis
            lead_changes: Optional list of detected lead changes (when market crossed 50%)
            **kwargs: Additional context (not used)

        Returns:
            Formatted agent prompt string
        """
        # Calculate evidence window with fallback logic
        from src.services.temporal_filter_service import TemporalFilterService

        window_start, window_end = TemporalFilterService.get_evidence_window(
            question.resolution_date,
            question.estimated_start_time,
            fallback_window_days=evidence_window_days,
        )

        # Format dates for prompt
        resolution_date_str = self.format_datetime(question.resolution_date)
        window_start_str = self.format_datetime(window_start)

        # Calculate actual window size in days
        actual_window_days = (window_end - window_start).days

        # Format outcome events for prompt injection
        outcome_events_info = self._format_outcome_events(outcome_events)

        # Format market analysis section (turning points + lead changes)
        market_turning_points_section = self._format_turning_points_section(
            turning_points, lead_changes
        )
        turning_points_evidence_hint = self._format_turning_points_hint(
            turning_points, lead_changes
        )

        # Build the prompt
        return self.AGENT_TEMPLATE.format(
            question_text=question.question_text,
            resolution_date=resolution_date_str,
            window_start=window_start_str,
            actual_window_days=actual_window_days,
            ground_truth=str(question.ground_truth),
            outcome_events_info=outcome_events_info,
            market_turning_points_section=market_turning_points_section,
            turning_points_evidence_hint=turning_points_evidence_hint,
            min_graph_depth=min_graph_depth,
            min_evidence_articles=min_evidence_articles,
            confidence_threshold=confidence_threshold,
        )

    def _format_outcome_events(self, outcome_events: list) -> str:
        """Format outcome events for prompt injection.

        Args:
            outcome_events: List of Event objects with is_outcome=True

        Returns:
            Formatted string listing outcomes with IDs and titles
        """
        if not outcome_events:
            return "No pre-created outcomes available."

        lines = []
        for event in outcome_events:
            scenario = ""
            if event.outcome_scenario:
                scenario = f" ({event.outcome_scenario.value})"
            is_actual_outcome = ""
            if event.is_actual_outcome:
                is_actual_outcome = " [TARGET GROUND TRUTH]"
            lines.append(f"- {event.id}: {event.title}{scenario}{is_actual_outcome}")

        return "\n".join(lines)

    def _format_turning_points_section(
        self, turning_points: list, lead_changes: list = None
    ) -> str:
        """Format market turning points and lead changes as a prompt section.

        Args:
            turning_points: List of turning point dicts from price analysis
            lead_changes: List of lead change dicts (when market crosses 50%)

        Returns:
            Formatted section string or empty string if no data
        """
        lines = []

        # Format lead changes first (most significant market events)
        if lead_changes:
            from datetime import datetime

            lines.append("\nLEAD CHANGES (when market prediction flipped):")
            lines.append(
                "These are moments when the favored outcome changed. CRITICAL events to investigate:"
            )

            for lc in lead_changes:
                lc_time = datetime.fromtimestamp(lc["timestamp"])
                direction = lc["direction"]
                price_pct = lc["price"] * 100
                prev_pct = lc["previous_price"] * 100

                if direction == "above":
                    desc = f"'Yes' became favored (crossed above 50%: {prev_pct:.1f}% -> {price_pct:.1f}%)"
                else:
                    desc = f"'No' became favored (crossed below 50%: {prev_pct:.1f}% -> {price_pct:.1f}%)"

                time_info = ""
                if lc.get("time_in_previous_state_hours"):
                    time_info = f" [was in previous state for {lc['time_in_previous_state_hours']:.1f}h]"

                lines.append(
                    f"- {lc_time.strftime('%Y-%m-%d %H:%M')}: {desc}{time_info}"
                )

        # Format turning points
        if turning_points:
            from datetime import datetime

            if lines:
                lines.append("")  # Add spacing

            lines.append("TURNING POINTS (significant price reversals):")
            lines.append(
                "These are moments when market sentiment shifted significantly:"
            )

            for tp in turning_points[:5]:  # Top 5 most significant
                tp_time = datetime.fromtimestamp(tp["timestamp"])
                tp_type = tp["type"].upper()

                if tp["type"] == "peak":
                    direction_desc = f"rose {tp['change_before']:.1f}pp then fell {abs(tp['change_after']):.1f}pp"
                else:
                    direction_desc = f"dropped {abs(tp['change_before']):.1f}pp then recovered {tp['change_after']:.1f}pp"

                lines.append(
                    f"- {tp_type} on {tp_time.strftime('%Y-%m-%d %H:%M')}: "
                    f"price {direction_desc} (significance: {tp['significance']:.1f})"
                )

        if not lines:
            return ""

        return "\n".join(lines)

    def _format_turning_points_hint(
        self, turning_points: list, lead_changes: list = None
    ) -> str:
        """Format evidence collection hint based on turning points and lead changes.

        Args:
            turning_points: List of turning point dicts from price analysis
            lead_changes: List of lead change dicts

        Returns:
            Hint string for evidence collection or empty string
        """
        from datetime import datetime

        # Collect all significant dates, prioritizing lead changes
        priority_dates = []
        critical_dates = []

        # Lead changes are CRITICAL - the market prediction actually flipped
        if lead_changes:
            for lc in lead_changes:
                lc_time = datetime.fromtimestamp(lc["timestamp"])
                date_str = lc_time.strftime("%Y-%m-%d")
                if date_str not in critical_dates:
                    critical_dates.append(date_str)

        # Turning points are important but less critical
        if turning_points:
            for tp in turning_points[:5]:
                tp_time = datetime.fromtimestamp(tp["timestamp"])
                date_str = tp_time.strftime("%Y-%m-%d")
                if date_str not in priority_dates and date_str not in critical_dates:
                    priority_dates.append(date_str)

        if not critical_dates and not priority_dates:
            return ""

        lines = []
        if critical_dates:
            lines.append(
                f"\n   CRITICAL DATES (lead changes - market prediction flipped): {', '.join(critical_dates)}"
            )
            lines.append(
                "   These are the MOST IMPORTANT dates - find what news caused the market to flip its prediction."
            )

        if priority_dates:
            lines.append(
                f"\n   PRIORITY DATES (from turning points): {', '.join(priority_dates)}"
            )
            lines.append(
                "   Search for news around these dates - they mark significant sentiment shifts."
            )

        return "\n".join(lines)
