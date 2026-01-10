"""Prompts for question generation stage."""

from datetime import datetime
from typing import List, Optional
from src.domain.models import Event
from .base import ContextualPromptGenerator, PromptTemplate

EVENT_TEMPLATE = \
"""
Event {idx} (ID: {event_id}){status_note}:
- Title: {title}
- Description: {description}
- Date: {event_date}
- Domain: {domain}
- Confidence: {confidence}
"""

SHARED_RULES_DESC = \
"""
QUALITY:
- Broad appeal s.t. people are interested to answer (elections, major companies, crypto, policy, sports)
- Skip niche topics requiring insider knowledge
- Ask "Will X happen?" not "Which company will..." (don't assume outcomes)
- MCQ options from actual event participants only
- Use FUTURE tense when formating all the questions

ESTIMATED START TIME:
- When forecasting this question would have become viable with meaningful information
  * Set far enough before resolution_date (1 week to 1+ year depending on scope)
  * But not so early that relevant context didn't yet exist
  * For event-based questions: when event was first announced/became public knowledge
  * For trend questions: when baseline data became available for analysis
  * For policy questions: when policy was first proposed/publicly discussed
  * MUST be BEFORE resolution_date (use ISO 8601 format with timezone)

RESOLUTION DATE:
- When the event has already been resolved

A good answering window for a forecast question will be between ESTIMATED START TIME and RESOLUTION DATE. 
- If the date goes beyond the resolution date, the answer will be retrieved.
- If the date goes before the estimated start time, some conditional events or contexts might not be available.

"""

ARTICLE_TEMPLATE = \
"""
Article {idx} (Source: {source}):
- Title: {title}
- Date: {published_date}
- Content: {content}
"""

RULES_GROUND_TRUTH = \
"""RULES:
- Today: {current_date} → MAKE SURE that: {current_date} >= resolution_date >= estimated_start_time
- ground_truth = past outcome only (YES/NO/value, never future dates)
- resolution_date: when the event has already been resolved
- Alternate binary answers: YES, NO, YES, NO (avoid bias)
- Use round numbers ($100K, 1M users) not oddly specific values
- Format questions using the future tense as if they are in the future (even though all the events are already resolved)
- Natural deadlines ("by end of Q4 202X" or "by end of Oct 202X" not "by Oct 27")"""

RULES_FUTURE = \
"""RULES:
- Today: {current_date} → MAKE SURE that: resolution_date > {current_date} >= estimated_start_time
- NO ground_truth (outcomes unknown)
- resolution_date: 1 week to 1+ year in future
- Balance binary predictions: ~50% likely YES, ~50% likely NO
- Use round numbers ($100K, 1M users) not oddly specific values
- Natural deadlines ("by end of Q1 202X" not "by Mar 15")"""


QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH = \
"""
You are creating questions to assess the AI forecast capabilities.
AI will answer the questions in a control environment as if it was the day before the resolution_date.
Create {max_questions} forecast questions from already RESOLVED events.{domain_filter}

{events_text}

""" + RULES_GROUND_TRUTH + SHARED_RULES_DESC


QUESTION_GENERATION_TEMPLATE_FUTURE = \
"""
You are creating questions to assess the AI forecast capabilities.
AI will answer the questions in an open environment.
Create {max_questions} forecast questions about FUTURE events.{domain_filter}

{events_text}

""" + RULES_FUTURE + SHARED_RULES_DESC


ARTICLE_HEADER = \
"""Analyze these {num_articles} news articles and generate {max_questions} forecast questions.{domain_filter}

TRUSTED SOURCES:
{sources_text}

{articles_text}

INSTRUCTIONS:
- Identify the key events/claims in these articles.
- Use web search and web fetch if you think the articles are not enough.
- Create questions that forecast the outcomes of these events.
- If multiple articles discuss the same event, consolidate them into a single question.
"""

ARTICLE_QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH = \
ARTICLE_HEADER + RULES_GROUND_TRUTH + SHARED_RULES_DESC

ARTICLE_QUESTION_GENERATION_TEMPLATE_FUTURE = \
ARTICLE_HEADER + RULES_FUTURE + SHARED_RULES_DESC


class QuestionGenerationPrompts(ContextualPromptGenerator[Event]):
    """Prompts for the question generation stage."""
    
    # Template for formatting individual events
    EVENT_TEMPLATE = PromptTemplate(
        template=EVENT_TEMPLATE,
        required_vars=["idx", "event_id", "title", "description", "event_date", "domain", "confidence"],
        optional_vars={"status_note": ""}
    )
    
    # Template for GROUND TRUTH mode (past events only)
    GENERATION_TEMPLATE_GROUND_TRUTH = PromptTemplate(
        template=QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH,
        required_vars=["num_events", "events_text", "max_questions", "current_date", "min_resolution_date"],
        optional_vars={
            "domain_filter": "",
            "tool_name": "batch_question_generator"
        }
    )

    # Template for FUTURE events mode (predictions only)
    GENERATION_TEMPLATE_FUTURE = PromptTemplate(
        template=QUESTION_GENERATION_TEMPLATE_FUTURE,
        required_vars=["num_events", "events_text", "max_questions", "current_date", "max_resolution_date"],
        optional_vars={
            "domain_filter": "",
            "tool_name": "batch_question_generator"
        }
    )

    # Template for ARTICLE-based generation (GROUND TRUTH)
    GENERATION_TEMPLATE_ARTICLE_GROUND_TRUTH = PromptTemplate(
        template=ARTICLE_QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH,
        required_vars=["num_articles", "articles_text", "max_questions", "current_date"],
        optional_vars={
            "domain_filter": "",
            "sources_text": "None",
            "tool_name": "batch_question_generator"
        }
    )

    # Template for ARTICLE-based generation (FUTURE)
    GENERATION_TEMPLATE_ARTICLE_FUTURE = PromptTemplate(
        template=ARTICLE_QUESTION_GENERATION_TEMPLATE_FUTURE,
        required_vars=["num_articles", "articles_text", "max_questions", "current_date"],
        optional_vars={
            "domain_filter": "",
            "sources_text": "None",
            "tool_name": "batch_question_generator"
        }
    )
    
    def format_item(
        self,
        item: Event,
        idx: int,
        current_date: datetime,
        content_preview_length: int = 200,
        **context
    ) -> str:
        """Format a single event for the prompt.

        Args:
            item: Event to format
            idx: Index of the event (1-based)
            current_date: Current datetime for resolved event detection
            content_preview_length: Length of content preview (default: 200)
            **context: Additional context (not used)

        Returns:
            Formatted event summary
        """
        event_date = item.occurred_date or item.predicted_date

        # Determine if event is in the past (for ground truth)
        is_past_event = event_date and event_date < current_date if event_date else False
        status_note = " (RESOLVED EVENT - questions should include ground_truth)" if is_past_event else ""

        # Truncate description
        description = self.format_content_preview(
            item.description,
            max_length=content_preview_length
        )
        
        # Extract metadata with safe defaults
        location = item.metadata.get('location', 'Unknown') if item.metadata else 'Unknown'
        confidence = item.metadata.get('confidence', 0.8) if item.metadata else 0.8
        
        return self.EVENT_TEMPLATE.format(
            idx=idx,
            event_id=item.id,
            status_note=status_note,
            title=item.title,
            description=description,
            event_date=event_date,
            domain=item.domain,
            location=location,
            confidence=confidence
        )
    
    def get_instruction(
        self,
        current_date: datetime,
        events: List[Event],
        max_questions: int,
        domains: Optional[List[str]] = None,
        content_preview_length: int = 200,
        tool_name: str = "question_generator",
        require_ground_truth: bool = True,
        type_hints: Optional[List[str]] = None,
        category_hints: Optional[List[str]] = None,
        description_preview_length: int = None  # DEPRECATED: Use content_preview_length
    ) -> str:
        """Generate instruction for question generation.

        Args:
            current_date: Current datetime
            events: List of events to generate questions from
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            content_preview_length: Length of content preview (default: 200)
            tool_name: Name of the tool to call (default: question_generator)
            require_ground_truth: If True, only generate questions about resolved events with known outcomes.
                                 If False, only generate questions about future predictions.
            type_hints: Priority question types needed (e.g., ["boolean", "mcq"])
            category_hints: Priority categories needed (e.g., ["finance", "tech"])

        Returns:
            Formatted instruction string
        """
        # Handle deprecated parameter
        if description_preview_length is not None:
            import warnings
            warnings.warn(
                "description_preview_length is deprecated, use content_preview_length instead",
                DeprecationWarning,
                stacklevel=2
            )
            content_preview_length = description_preview_length

        # Calculate resolution date range based on mode
        min_resolution_date, max_resolution_date = self.calculate_date_window(
            current_date=current_date,
            require_past_events=require_ground_truth,
            events=events
        )

        min_res_str = self.format_datetime(min_resolution_date)
        max_res_str = self.format_datetime(max_resolution_date)
        date_str = self.format_datetime(current_date)

        # Format all events
        events_text = self.format_items(
            events,
            current_date=current_date,
            content_preview_length=content_preview_length
        )

        # Build domain filter
        domain_filter = ""
        if domains:
            domain_filter = f" Focus on domains: {self.format_list(domains)}."

        # Build priority guidance from hints
        priority_guidance = self.build_priority_guidance(
            type_hints=type_hints,
            category_hints=category_hints
        )

        # Select appropriate template based on mode
        if require_ground_truth:
            template = self.GENERATION_TEMPLATE_GROUND_TRUTH
            instruction_body = template.format(
                num_events=len(events),
                events_text=events_text,
                max_questions=max_questions,
                current_date=date_str,
                min_resolution_date=min_res_str,
                domain_filter=domain_filter,
                tool_name=tool_name
            )
        else:
            template = self.GENERATION_TEMPLATE_FUTURE
            instruction_body = template.format(
                num_events=len(events),
                events_text=events_text,
                max_questions=max_questions,
                current_date=date_str,
                max_resolution_date=max_res_str,
                domain_filter=domain_filter,
                tool_name=tool_name
            )

        # Add priority guidance if provided
        if priority_guidance:
            instruction_body = instruction_body + priority_guidance

        return self.build_instruction(current_date, instruction_body)

    def get_article_instruction(
        self,
        current_date: datetime,
        articles: List,  # List[Article] but typed loosely to avoid generic issues
        max_questions: int,
        domains: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,  # NEW
        tool_name: str = "batch_question_generator",
        require_ground_truth: bool = True,
        type_hints: Optional[List[str]] = None,
        category_hints: Optional[List[str]] = None,
    ) -> str:
        """Generate instruction for question generation from ARTICLES.

        Args:
            current_date: Current datetime
            articles: List of articles
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            tool_name: Name of the tool to call
            require_ground_truth: Whether to prefer ground truth questions
            type_hints: Priority question types needed
            category_hints: Priority categories needed

        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)

        # Format articles
        articles_text_parts = []
        for idx, article in enumerate(articles, 1):
            # Truncate content to avoid token limits
            content = article.content
            if len(content) > 500:
                content = content[:500] + "..."
            
            # Format published date
            pub_date = article.published_date.strftime('%Y-%m-%d') if article.published_date else "Unknown"

            articles_text_parts.append(
                ARTICLE_TEMPLATE.format(
                    idx=idx,
                    source=article.source,
                    title=article.title,
                    published_date=pub_date,
                    content=content
                )
            )
        
        articles_text = "\n".join(articles_text_parts)

        # Build domain filter
        domain_filter = ""
        if domains:
            domain_filter = f" Focus on domains: {self.format_list(domains)}."

        # Build sources text
        sources_text = "No specific trusted sources provided."
        if sources:
             sources_text = self.format_list(sources)

        if require_ground_truth:
            template = self.GENERATION_TEMPLATE_ARTICLE_GROUND_TRUTH
        else:
            template = self.GENERATION_TEMPLATE_ARTICLE_FUTURE

        # Build instruction
        instruction_body = template.format(
            num_articles=len(articles),
            articles_text=articles_text,
            sources_text=sources_text,  # NEW parameters
            max_questions=max_questions,
            current_date=date_str,
            domain_filter=domain_filter,
            tool_name=tool_name
        )

        # Add priority guidance
        priority_guidance = self.build_priority_guidance(
            type_hints=type_hints,
            category_hints=category_hints
        )
        if priority_guidance:
            instruction_body = instruction_body + priority_guidance

        return self.build_instruction(current_date, instruction_body)
