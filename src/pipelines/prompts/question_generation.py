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
- Natural deadlines ("by end of Q4 2024" not "by Oct 27")

QUALITY:
- Broad appeal (elections, major companies, crypto, policy, sports)
- Skip niche topics requiring insider knowledge
- Ask "Will X happen?" not "Which company will..." (don't assume outcomes)
- MCQ options from actual event participants only

TOOL USAGE:
1. Generate all {max_questions} questions as JSON array
2. Call {tool_name}(questions_json="[...]") ONCE
3. Then call final_answer

Required fields: question_text, question_type, domain, difficulty, resolution_date, resolution_criteria, ground_truth, resolution_reasoning, related_event_ids

Example: {tool_name}(questions_json='[{{"question_text": "Will Bitcoin exceed $100K by Dec 31, 2025?", "question_type": "boolean", "domain": "finance", "difficulty": 3, "resolution_date": "2025-12-31", "resolution_criteria": "CoinMarketCap closing price", "ground_truth": "YES", "resolution_reasoning": "BTC closed at $105K on Dec 31 per CoinMarketCap", "related_event_ids": "evt_fin_20251201_001"}}]')"""

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
- Natural deadlines ("by end of Q1 2026" not "by Mar 15")

QUALITY:
- Broad appeal (elections, major companies, crypto, policy, sports)
- Skip niche topics requiring insider knowledge
- Ask "Will X happen?" not "Which company will..." (don't assume outcomes)
- MCQ options from actual event participants only

TOOL USAGE:
1. Generate all {max_questions} questions as JSON array
2. Call {tool_name}(questions_json="[...]") ONCE
3. Then call final_answer

Required fields: question_text, question_type, domain, difficulty, resolution_date, resolution_criteria, related_event_ids
DO NOT include: ground_truth, resolution_reasoning (outcomes unknown)

Example: {tool_name}(questions_json='[{{"question_text": "Will Bitcoin exceed $150K by Dec 31, 2026?", "question_type": "boolean", "domain": "finance", "difficulty": 3, "resolution_date": "2026-12-31", "resolution_criteria": "CoinMarketCap closing price", "related_event_ids": "evt_fin_20260601_001"}}]')"""

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
        description_preview_length: int = 200,
        **context
    ) -> str:
        """Format a single event for the prompt.
        
        Args:
            item: Event to format
            idx: Index of the event (1-based)
            current_date: Current datetime for past event detection
            description_preview_length: Length of description preview (default: 200)
            **context: Additional context (not used)
            
        Returns:
            Formatted event summary
        """
        event_date = item.occurred_date or item.predicted_date
        
        # Determine if event is in the past (for ground truth)
        is_past_event = event_date and event_date < current_date if event_date else False
        status_note = " (PAST EVENT - questions should include ground_truth)" if is_past_event else ""
        
        # Truncate description
        description = self.truncate_text(
            item.description,
            max_length=description_preview_length,
            suffix="..."
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
        description_preview_length: int = 200,
        tool_name: str = "question_generator",
        require_ground_truth: bool = True,
        type_hints: Optional[List[str]] = None,
        category_hints: Optional[List[str]] = None
    ) -> str:
        """Generate instruction for question generation.

        Args:
            current_date: Current datetime
            events: List of events to generate questions from
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            description_preview_length: Length of description preview (default: 200)
            tool_name: Name of the tool to call (default: question_generator)
            require_ground_truth: If True, only generate questions about past events with known outcomes.
                                 If False, only generate questions about future predictions.
            type_hints: Priority question types needed (e.g., ["boolean", "mcq"])
            category_hints: Priority categories needed (e.g., ["finance", "tech"])

        Returns:
            Formatted instruction string
        """
        from datetime import timedelta

        date_str = self.format_datetime(current_date)

        # Calculate resolution date range based on mode
        if require_ground_truth:
            # Ground truth mode: Use past events only
            # Min: earliest event date (or 1 year ago)
            # Max: current_date (only events that already occurred)
            event_dates = []
            for event in events:
                event_date = event.occurred_date or event.predicted_date
                if event_date and event_date < current_date:
                    event_dates.append(event_date)

            if event_dates:
                min_resolution_date = min(event_dates)
            else:
                min_resolution_date = current_date - timedelta(days=365)

            max_resolution_date = current_date
        else:
            # Future prediction mode: Use future dates only
            # Min: current_date (tomorrow onwards)
            # Max: current_date + 1 year (reasonable forecasting horizon)
            min_resolution_date = current_date
            max_resolution_date = current_date + timedelta(days=365)

        min_res_str = self.format_datetime(min_resolution_date)
        max_res_str = self.format_datetime(max_resolution_date)

        # Format all events
        events_text = self.format_items(
            events,
            current_date=current_date,
            description_preview_length=description_preview_length
        )

        # Build domain filter
        domain_filter = ""
        if domains:
            domain_filter = f" Focus on domains: {self.format_list(domains)}."
        
        # Build priority guidance from hints
        priority_guidance = ""
        if type_hints or category_hints:
            guidance_parts = []
            if type_hints:
                guidance_parts.append(f"PRIORITY TYPES NEEDED: {self.format_list(type_hints)}")
            if category_hints:
                guidance_parts.append(f"PRIORITY CATEGORIES NEEDED: {self.format_list(category_hints)}")
            priority_guidance = "\n\n⚠️ COLLECTION PRIORITIES:\n" + "\n".join(guidance_parts) + "\nFocus on generating questions of these types/categories first!"

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

        return f"Today's date is {date_str}.\n\n{instruction_body}"
