"""Prompts for hindsight causal analysis using multi-agent system."""

from datetime import datetime, timedelta
from src.domain.models import Question
from .base import BasePromptGenerator, PromptTemplate


EVIDENCE_AGENT_DESCRIPTION = \
"""
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

GRAPH_AGENT_DESCRIPTION = \
"""
Specialist agent for building deep causal graphs.

Guidelines:
- Call get_question_articles to get article IDs
- If target_event_id is provided, use EventDetailsTool to understand it
- Create target event (outcome from ground truth) using event_identifier with is_target=True if not provided
- Create events using event_identifier with source_article_ids from step 1
- Use causal_reasoner to identify relationships between events
- All chains must connect to the target event
- Make sure the chronology of events makes sense (earlier events cause later events)
- Use graph_inspector to check the quality and depth of the graph
"""

MANAGER_AGENT_DESCRIPTION = \
"""Your task: Build a DEEP causal explanation for this question with hindsight.

NOTE: the question has already been resolved on {resolution_date} with known ground truth.

QUESTION ID: {question_id}
QUESTION: {question_text}
RESOLUTION DATE: {resolution_date}
GROUND TRUTH (the KNOWN outcome): {ground_truth}
{target_event_info}

PROCESS:

1. COLLECT EVIDENCE:
   Call evidence_collector to gather relevant articles:
   - Time window: {window_start} to {resolution_date} ({actual_window_days} days)
   - Target: {min_evidence_articles}+ high-quality articles across different dates
   - Use article_inspector to verify coverage; if insufficient, broaden search

2. BUILD DEEP EVENT GRAPH:
   Call causal_analyzer to build deep event relationship graph:
   - Target: {min_evidence_articles}+ events, {min_graph_depth}+ depth levels
   - Use graph_inspector to verify quality and depth

3. EVALUATE & ITERATE:


Begin the analysis!"""

class HindsightCausalAnalysisPrompts(BasePromptGenerator[Question]):
    """Prompts for building deep causal graphs with HindsightAgent."""

    # Template for agent prompt
    AGENT_TEMPLATE = PromptTemplate(
        template=MANAGER_AGENT_DESCRIPTION,
        required_vars=[
            "question_id",
            "question_text",
            "resolution_date",
            "window_start",
            "actual_window_days",
            "ground_truth",
            "target_event_info",
            "min_graph_depth",
            "min_evidence_articles",
            "confidence_threshold",
        ]
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
        min_graph_depth: int = 3,
        evidence_window_days: int = 365,
        min_evidence_articles: int = 5,
        confidence_threshold: float = 0.6,
        **kwargs
    ) -> str:
        """Generate prompt for HindsightAgent to build deep causal graph.

        Uses two-tier evidence window approach:
        1. If question has estimated_start_time: use [estimated_start_time, resolution_date]
        2. Fallback: use [resolution_date - evidence_window_days, resolution_date]

        Args:
            question: Question to analyze
            min_graph_depth: Minimum causal chain depth required (default: 3)
            evidence_window_days: Days before resolution to collect evidence if no estimated_start_time (default: 365)
            min_evidence_articles: Minimum evidence articles needed (default: 5)
            confidence_threshold: Minimum confidence for causal links (default: 0.6)
            **kwargs: Additional context (not used)

        Returns:
            Formatted agent prompt string
        """
        # Calculate evidence window with fallback logic
        from src.utils.article_analysis import get_evidence_window

        window_start, window_end = get_evidence_window(
            question.resolution_date,
            question.estimated_start_time,
            fallback_window_days=evidence_window_days
        )

        # Format dates for prompt
        resolution_date_str = self.format_datetime(question.resolution_date)
        window_start_str = self.format_datetime(window_start)

        # Calculate actual window size in days
        actual_window_days = (window_end - window_start).days

        # Generate target event instructions based on whether target_event_id exists

        if question.target_event_id:
            target_event_info = f"TARGET EVENT ID: {question.target_event_id} (USE THIS as the final target for all causal chains)"
        else:
            target_event_info = "TARGET EVENT: Not yet created (you must create it first, ensuring is_target=True)"

        # Build the prompt
        return self.AGENT_TEMPLATE.format(
            question_id=question.id,
            question_text=question.question_text,
            resolution_date=resolution_date_str,
            window_start=window_start_str,
            actual_window_days=actual_window_days,
            ground_truth=str(question.ground_truth),
            target_event_info=target_event_info,
            min_graph_depth=min_graph_depth,
            min_evidence_articles=min_evidence_articles,
            confidence_threshold=confidence_threshold,
        )
