"""Prompts for hindsight causal analysis using multi-agent system."""

from datetime import datetime, timedelta
from src.domain.models import Question
from .base import BasePromptGenerator, PromptTemplate


class HindsightCausalAnalysisPrompts(BasePromptGenerator[Question]):
    """Prompts for building deep causal graphs with HindsightAgent."""

    # Template for agent prompt
    AGENT_TEMPLATE = PromptTemplate(
        template="""Your task: Build a DEEP causal explanation for this question with hindsight.

NOTE: the question has already been resolved on {resolution_date} with known ground truth.

QUESTION ID: {question_id}
QUESTION: {question_text}
RESOLUTION DATE: {resolution_date}
GROUND TRUTH: {ground_truth}
{target_event_info}

REQUIREMENTS:
- Causal graph depth must be >= {min_graph_depth} levels (multi-hop chains)
- Each causal link must have supporting evidence
- Build from root causes → intermediate factors → immediate causes → outcome

PROCESS:

1. COLLECT EVIDENCE:
   Call evidence_collector to gather relevant articles:
   - Time window: {evidence_window_days} days before resolution ({window_start} to {resolution_date})
   - Need at least {min_evidence_articles} high-quality articles, more is better
   - Collect articles at different dates/times to capture evolving context
   - If insufficient, ask agent to broaden search

2. BUILD DEEP CAUSAL GRAPH:
   Call causal_analyzer with this exact prompt:

   "Build a deep causal graph for question '{question_id}' about: {question_text}

   Make sure you provide the related article IDs from evidence_collector.

   {causal_graph_instructions}

   REMEMBER: Every causal_reasoner call must have question_id='{question_id}'"

3. EVALUATE & ITERATE:
   - Call graph_inspector to check current depth
   - If max_depth < {min_graph_depth}: Tell causal_analyzer to go deeper
   - Target: {min_evidence_articles}+ events, {min_graph_depth}+ levels

4. FINAL VALIDATION:
   - Verify each causal link has evidence support (confidence >= {confidence_threshold})
   - Check temporal validity (causes before effects)
   - Confirm chains explain the ground truth outcome

SUCCESS CRITERIA:
✓ Evidence: {min_evidence_articles}+ relevant articles collected
✓ Depth: Causal chains with {min_graph_depth}+ levels
✓ Events: 5+ events created
✓ Links: Multiple causal chains to target
✓ Quality: Score > 0.7

Begin the analysis!""",
        required_vars=[
            "question_id",
            "question_text",
            "resolution_date",
            "ground_truth",
            "target_event_info",
            "causal_graph_instructions",
            "min_graph_depth",
            "evidence_window_days",
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

        Args:
            question: Question to analyze
            min_graph_depth: Minimum causal chain depth required (default: 3)
            evidence_window_days: Days before resolution to collect evidence (default: 365)
            min_evidence_articles: Minimum evidence articles needed (default: 5)
            confidence_threshold: Minimum confidence for causal links (default: 0.6)
            **kwargs: Additional context (not used)

        Returns:
            Formatted agent prompt string
        """
        # Format resolution date
        resolution_date_str = self.format_datetime(question.resolution_date)
        window_start = self.format_datetime(question.resolution_date - timedelta(days=evidence_window_days))
        # Generate target event instructions based on whether target_event_id exists
        if question.target_event_id:
            target_event_info = f"TARGET EVENT ID: {question.target_event_id} (USE THIS as the final target for all causal chains)"
            causal_graph_instructions = f"""Steps:
   1. The target event is ALREADY CREATED: {question.target_event_id}
   2. Identify 3-4 immediate causes (level 1) that lead to the target event
   3. For EACH immediate cause, identify what caused IT (level 2)
   4. For top 2 level-2 causes, go even deeper (level 3)
   5. Use causal_reasoner with target_event_id="{question.target_event_id}" for final links
   6. Use graph_inspector to check depth
   7. If depth < {min_graph_depth}, create more intermediate events
   
   IMPORTANT: All causal chains MUST eventually lead to target_event_id="{question.target_event_id}"!
   Build: Root → Intermediate → Immediate → TARGET({question.target_event_id})"""
        else:
            target_event_info = "TARGET EVENT: Not yet created (you must create it first)"
            causal_graph_instructions = f"""Steps:
   1. Create target event (the outcome from ground truth) using event_identifier
   2. Save the returned event ID - THIS is your target_event_id
   3. Identify 3-4 immediate causes (level 1) that lead to the target event
   4. For EACH immediate cause, identify what caused IT (level 2)
   5. For top 2 level-2 causes, go even deeper (level 3)
   6. Use causal_reasoner with the target_event_id for final links
   7. Use graph_inspector to check depth
   8. If depth < {min_graph_depth}, create more intermediate events
   
   IMPORTANT: All causal chains MUST eventually lead to your created target event!
   Build: Root → Intermediate → Immediate → TARGET"""

        # Build the prompt
        return self.AGENT_TEMPLATE.format(
            question_id=question.id,
            question_text=question.question_text,
            resolution_date=resolution_date_str,
            window_start=window_start,
            ground_truth=str(question.ground_truth),
            target_event_info=target_event_info,
            causal_graph_instructions=causal_graph_instructions,
            min_graph_depth=min_graph_depth,
            evidence_window_days=evidence_window_days,
            min_evidence_articles=min_evidence_articles,
            confidence_threshold=confidence_threshold,
        )
