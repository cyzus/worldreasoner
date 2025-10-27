"""Prompts for hindsight causal analysis in evidence pipeline."""

from datetime import datetime
from typing import List, Tuple
from src.domain.models import Question, Article
from src.pipelines.prompts.base import ContextualPromptGenerator, PromptTemplate


class HindsightAnalysisPrompts(ContextualPromptGenerator[Tuple[Question, List[Article]]]):
    """Prompts for analyzing evidence with hindsight to identify causal relationships."""

    # Template for formatting evidence articles
    EVIDENCE_ARTICLE_TEMPLATE = PromptTemplate(
        template="""
Evidence Article {idx} (ID: {article_id}):
- Title: {title}
- Source: {source}
- Published: {published_date} (BEFORE outcome on {resolution_date})
- Domain: {domain}
- Summary: {content_preview}
""",
        required_vars=["idx", "article_id", "title", "source", "published_date",
                       "resolution_date", "domain", "content_preview"]
    )

    # Template for hindsight causal analysis instruction
    HINDSIGHT_ANALYSIS_TEMPLATE = PromptTemplate(
        template="""You are analyzing what caused the following outcome with the benefit of HINDSIGHT.

========== QUESTION DETAILS ==========
Question ID: {question_id}
Question: {question_text}
Actual Outcome: {ground_truth}
Resolution Date: {resolution_date}
Target Event: {target_event_id}

========== YOUR TASK ==========
Analyze evidence articles from BEFORE the outcome to identify what caused it.
We have HINDSIGHT (know the outcome), but we're looking at pre-event articles
to identify which factors actually led to this result.

{evidence_articles_text}

========== AVAILABLE EVENT IDS (Use as SOURCE events) ==========
{related_events_text}

IMPORTANT: You MUST use event IDs from the list above as source events.
Do NOT invent new event IDs. If no events from the list are related,
that's OK - you can return zero causal links.

AVAILABLE TOOLS:
1. article_retrieval - Query database for additional articles (before or after outcome)
2. causal_reasoner - Record each causal relationship you identify

========== INSTRUCTIONS ==========
1. IDENTIFY CAUSES: What events/factors directly caused this outcome?
   - Look for explicit causal language in the evidence
   - Consider direct causes vs enabling factors vs correlations

2. FOR EACH CAUSAL LINK:
   - Source event: MUST be an event ID from the list above
   - Target event: {target_event_id} (the outcome itself)
   - Relation type: causes | enables | prevents | correlates | conditional
   - Strength: How strong was the causal effect? (0.0-1.0)
   - Confidence: How sure are you based on evidence? (0.0-1.0)
   - Reasoning: Explain the causal mechanism clearly
   - Evidence: Cite article IDs that support this claim

3. USE THE TOOLS:
   - Use article_retrieval to find more context if needed
   - Use causal_reasoner to record EACH causal link separately

4. QUALITY STANDARDS:
   - Only propose links with confidence >= {min_confidence}
   - Only propose links with strength >= {min_strength}
   - Must cite at least one evidence article
   - Explain the mechanism, don't just assert causation
   - ONLY use event IDs from the provided list as sources

========== IMPORTANT GUIDELINES ==========
- Focus on what ACTUALLY happened (not predictions or speculation)
- Use the hindsight evidence to identify true causal factors
- Distinguish between:
  * Direct causes: A directly caused B
  * Enabling factors: A made B possible
  * Correlations: A and B related but not causal
- Multiple causes are expected - identify all significant ones
- Call causal_reasoner once per causal link
- Do NOT invent event IDs - only use those from the list

Return a summary when finished identifying all causal relationships.""",
        required_vars=[
            "question_id", "question_text", "ground_truth", "resolution_date",
            "target_event_id", "evidence_articles_text", "related_events_text",
            "min_confidence", "min_strength"
        ]
    )

    # Template for evidence collection instruction
    EVIDENCE_COLLECTION_TEMPLATE = PromptTemplate(
        template="""Search for evidence articles that explain what caused the following outcome.

========== OUTCOME DETAILS ==========
Question: {question_text}
Actual Outcome: {ground_truth}
Resolution Date: {resolution_date}
Domain: {domain}
Evidence window: {start_date} to {end_date} (all dates BEFORE the resolution date)

========== YOUR TASK ==========
Collect articles published BEFORE {resolution_date} that discussed:
- Factors and events leading up to the outcome
- Conditions that were present before the outcome
- Trends, developments, and signals that preceded the outcome
- Expert analysis and predictions made before the event

We have HINDSIGHT - we know the outcome that occurred on {resolution_date}.
Now search for articles from BEFORE that date to identify causal factors.

SEARCH STRATEGY:
1. Use web_search to find articles discussing factors before the outcome
2. Search for variations like:
   - "factors affecting [topic]" (before resolution date)
   - "developments in [topic]" (timeframe before outcome)
   - "[topic] trends" (leading up to outcome)
   - "what will influence [topic]" (articles before event)
3. Prioritize articles discussing causal factors and trends
4. Collect at least {min_articles} high-quality articles
5. Use article_collector tool to store each article

FOCUS ON:
- Articles published BEFORE {resolution_date}
- Content discussing factors that existed before the outcome
- Analysis of conditions and trends leading up to the event
- Sources that discussed potential causes before the outcome occurred

Return a summary when you've collected enough evidence articles.""",
        required_vars=[
            "question_text", "ground_truth", "resolution_date", "domain", "min_articles", "start_date", "end_date"
        ]
    )

    def format_item(
        self,
        item: Tuple[Question, List[Article]],
        idx: int,
        content_preview_length: int = 200,
        **context
    ) -> str:
        """Format a question-evidence pair for the prompt.

        Args:
            item: Tuple of (Question, List[Article])
            idx: Index (not used for this generator)
            content_preview_length: Length of content preview
            **context: Additional context

        Returns:
            Formatted evidence articles string
        """
        question, evidence_articles = item

        if not evidence_articles:
            return "No evidence articles collected yet."

        formatted = []
        for article_idx, article in enumerate(evidence_articles, 1):
            content_preview = self.truncate_text(
                article.content,
                max_length=content_preview_length,
                suffix="..."
            )

            formatted_article = self.EVIDENCE_ARTICLE_TEMPLATE.format(
                idx=article_idx,
                article_id=article.id,
                title=article.title,
                source=article.source,
                published_date=self.format_datetime(article.published_date),
                resolution_date=self.format_datetime(question.resolution_date) if question.resolution_date else "N/A",
                domain=article.domain,
                content_preview=content_preview
            )
            formatted.append(formatted_article)

        return "\n".join(formatted)

    def get_hindsight_analysis_instruction(
        self,
        current_date: datetime,
        question: Question,
        evidence_articles: List[Article],
        min_confidence: float = 0.6,
        min_strength: float = 0.3,
        content_preview_length: int = 200,
        related_events: List = None,
    ) -> str:
        """Generate instruction for hindsight causal analysis.

        Args:
            current_date: Current datetime
            question: Resolved question being analyzed
            evidence_articles: Evidence articles collected after resolution
            min_confidence: Minimum confidence threshold
            min_strength: Minimum strength threshold
            content_preview_length: Length of content preview
            related_events: List of Event objects that could be sources

        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)
        resolution_str = self.format_datetime(question.resolution_date) if question.resolution_date else "N/A"

        # Format evidence articles
        evidence_text = self.format_item(
            (question, evidence_articles),
            idx=1,
            content_preview_length=content_preview_length
        )

        # Format related events
        if related_events:
            events_list = []
            for idx, event in enumerate(related_events, 1):
                event_str = f"{idx}. {event.id}"
                if event.title:
                    event_str += f" - {event.title}"
                if event.occurred_date:
                    event_str += f" ({self.format_datetime(event.occurred_date)})"
                events_list.append(event_str)
            related_events_text = "\n".join(events_list)
        else:
            related_events_text = "(No related events found in database)"

        return self.HINDSIGHT_ANALYSIS_TEMPLATE.format(
            question_id=question.id,
            question_text=question.question_text,
            ground_truth=str(question.ground_truth),
            resolution_date=resolution_str,
            target_event_id=question.target_event_id,
            evidence_articles_text=evidence_text,
            related_events_text=related_events_text,
            min_confidence=min_confidence,
            min_strength=min_strength,
        )

    def get_evidence_collection_instruction(
        self,
        current_date: datetime,
        question: Question,
        min_articles: int = 5,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        evidence_window_days: int = None,
    ) -> str:
        """Generate instruction for collecting hindsight evidence.

        Args:
            current_date: Current datetime
            question: Resolved question
            min_articles: Minimum articles to collect

        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)
        resolution_str = self.format_datetime(question.resolution_date) if question.resolution_date else "N/A"

        # If datetime start/end were provided, format them; otherwise use placeholder
        start_date_str = self.format_datetime(start_date) if start_date is not None else "(unspecified)"
        end_date_str = self.format_datetime(end_date) if end_date is not None else "(unspecified)"

        return self.EVIDENCE_COLLECTION_TEMPLATE.format(
            question_text=question.question_text,
            ground_truth=str(question.ground_truth),
            resolution_date=resolution_str,
            domain=question.domain,
            min_articles=min_articles,
            start_date=start_date_str,
            end_date=end_date_str,
        )

    def get_instruction(self, **kwargs) -> str:
        """Get generic instruction (delegates to specific instruction methods).

        Args:
            **kwargs: Must include either 'question' and 'evidence_articles'
                     for analysis, or just 'question' for collection

        Returns:
            Formatted instruction string
        """
        if 'evidence_articles' in kwargs:
            return self.get_hindsight_analysis_instruction(**kwargs)
        else:
            return self.get_evidence_collection_instruction(**kwargs)
