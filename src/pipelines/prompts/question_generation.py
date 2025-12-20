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
- Broad appeal (elections, major companies, crypto, policy, sports)
- Skip niche topics requiring insider knowledge
- Ask "Will X happen?" not "Which company will..." (don't assume outcomes)
- MCQ options from actual event participants only
- Use future tense in question wording

ESTIMATED START TIME:
- estimated_start_time: When sufficient context exists for informed forecasting
  * For event-based questions: when event was first announced/became public
  * For trend questions: when baseline data became available
  * For policy questions: when policy was first proposed/discussed
  * MUST be BEFORE resolution_date (use ISO format with timezone)
  * Be conservative - better to start later with context than earlier without
  * If uncertain, omit this field

Required fields: question_text, question_type, domain, difficulty, resolution_date, resolution_criteria, ground_truth, resolution_reasoning, related_event_ids
Optional fields: estimated_start_time

Example: {tool_name}(questions_json='[{{"question_text": "Will Bitcoin exceed $100K by Dec 31, 2025?", "question_type": "boolean", "domain": "finance", "difficulty": 3, "resolution_date": "2025-12-31T23:59:59Z", "resolution_criteria": "CoinMarketCap closing price", "ground_truth": "YES", "resolution_reasoning": "BTC closed at $105K on Dec 31 per CoinMarketCap", "related_event_ids": "evt_fin_20251201_001", "estimated_start_time": "2025-01-01T00:00:00Z"}}]')
"""


QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH = \
"""Generate {max_questions} forecast questions from PAST events.{domain_filter}

{events_text}

RULES:
- Today: {current_date} → resolution_date ≤ {current_date}
- Only use events marked "(PAST EVENT)"
- ground_truth = past outcome only (YES/NO/value, never future dates)
- Alternate boolean answers: YES, NO, YES, NO (avoid bias)
- Types: boolean, mcq, quantity, timeframe (distribute evenly)
- Use round numbers ($100K, 1M users) not oddly specific values
- Natural deadlines ("by end of Q4 2024" not "by Oct 27")""" + SHARED_RULES_DESC


QUESTION_GENERATION_TEMPLATE_FUTURE = \
"""Generate {max_questions} forecast questions about FUTURE events.{domain_filter}

{events_text}

RULES:
- Today: {current_date} → resolution_date > {current_date}
- Skip events marked "(PAST EVENT)"
- NO ground_truth (outcomes unknown)
- Resolution dates: 1-12 months in future
- Balance boolean predictions: ~50% likely YES, ~50% likely NO
- Types: boolean, mcq, quantity, timeframe (distribute evenly)
- Use round numbers ($100K, 1M users) not oddly specific values
- Natural deadlines ("by end of Q1 2026" not "by Mar 15")""" + SHARED_RULES_DESC


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
            current_date: Current datetime for past event detection
            content_preview_length: Length of content preview (default: 200)
            **context: Additional context (not used)

        Returns:
            Formatted event summary
        """
        event_date = item.occurred_date or item.predicted_date

        # Determine if event is in the past (for ground truth)
        is_past_event = event_date and event_date < current_date if event_date else False
        status_note = " (PAST EVENT - questions should include ground_truth)" if is_past_event else ""

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
            require_ground_truth: If True, only generate questions about past events with known outcomes.
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
