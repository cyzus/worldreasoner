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
Specialist agent for building deep causal graphs and analyzing outcome impacts.

Guidelines:
- Call get_question_articles to get article IDs
- Call get_question_events to see existing events and OUTCOME events (use actual_outcome_event_id for final links)
- If outcomes are provided, use EventDetailsTool to understand them
- Create outcome event(s) (outcome from ground truth) using event_identifier with is_outcome=True if not provided
- Create events with source_article_ids (remember to check the tool output like event ids to see status)
- Identify relationships between events 
- ⚠️ DATE ACCURACY: When extracting 'occurred_date', check the article year.

CRITICAL - CONNECTING TO OUTCOME:
- After building intermediate event chains, you MUST use causal_reasoner to create the FINAL LINK
- The final link connects your last intermediate event(s) to the OUTCOME EVENT
- Example: If you have "Negative Reviews" → "Critics Snub", you need one more link: "Critics Snub" → [OUTCOME EVENT]
- Without this final link, the graph will show Max Depth: 0 and appear disconnected!
- Use the outcome_event_id matching the ground truth (e.g., "Yes" or "No" scenario)

OUTCOME IMPACT ANALYSIS:
- For each significant event, assess its impact on BOTH outcomes (Yes/No or all MCQ options)
- Use event_identifier with outcome_impacts parameter to record impacts:
  - direction: "positive" (increases likelihood) or "negative" (decreases likelihood)
  - magnitude: 0.0-1.0 (0.5=moderate, 0.7+=strong, 1.0=decisive)
  - confidence: 0.0-1.0 (your certainty in this assessment)
  - reasoning: Explain WHY and HOW this event impacts the outcome
- Consider: An event making one outcome more likely often makes the opposite less likely
- Focus on events with magnitude >= 0.5 (significant impacts)

FINAL VERIFICATION:
- Use graph_inspector to check the quality, depth, and outcome impacts
- If Max Depth is 0, you have NOT connected to the outcome - go back and add the final link!
"""

MANAGER_AGENT_DESCRIPTION = """Your task: Make a comprehensive event analysis for this question with hindsight.

NOTE: the question has already been resolved on {resolution_date} with known ground truth.

QUESTION: {question_text}
RESOLUTION DATE: {resolution_date}
GROUND TRUTH (the KNOWN outcome): {ground_truth}

AVAILABLE OUTCOME EVENTS (pre-created for this question):
{outcome_events_info}

When recording outcome impacts for events, use the outcome_event_ids listed above.

PROCESS:

1. COLLECT EVIDENCE:
   Call evidence_collector to gather relevant articles:
   - collect and store relevant evidence to db using article_collector
   - Time window: {window_start} to {resolution_date} ({actual_window_days} days)
   - Target: {min_evidence_articles}+ high-quality articles across different dates
   - Use article_inspector to verify coverage; if insufficient, broaden search

MANAGER AGENT: Inspect the evidence/article collection yourself. If insufficient, repeat step 1.

NOTE - if evidence collection constantly fails, there's no way you can build a event graph. You should keep trying until you get enough evidence.

2. BUILD DEEP EVENT GRAPH WITH OUTCOME IMPACTS:
   Call causal_analyzer to build deep event relationship graph:
   - Target: {min_evidence_articles}+ events, {min_graph_depth}+ depth levels
   - For each significant event, analyze its impact on outcome likelihood
   - Record both positive and negative impacts (symmetric analysis)
   - Draw relationship between events using causal_reasoner
   - Use graph_inspector to verify quality, depth, and outcome impacts

MANAGER AGENT: Inspect the event graph yourself. If insufficient, repeat step 2.

3. EVALUATE & ITERATE step 1 or 2 based on your own assessment."""


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
            **kwargs: Additional context (not used)

        Returns:
            Formatted agent prompt string
        """
        # Calculate evidence window with fallback logic
        from src.utils.article_analysis import get_evidence_window

        window_start, window_end = get_evidence_window(
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

        # Build the prompt
        return self.AGENT_TEMPLATE.format(
            question_text=question.question_text,
            resolution_date=resolution_date_str,
            window_start=window_start_str,
            actual_window_days=actual_window_days,
            ground_truth=str(question.ground_truth),
            outcome_events_info=outcome_events_info,
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
