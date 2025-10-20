"""Prompts for question generation stage."""

from datetime import datetime
from typing import List, Optional
from src.domain.models import Event
from .base import ContextualPromptGenerator, PromptTemplate


class QuestionGenerationPrompts(ContextualPromptGenerator[Event]):
    """Prompts for the question generation stage."""
    
    # Template for formatting individual events
    EVENT_TEMPLATE = PromptTemplate(
        template="""
Event {idx} (ID: {event_id}){status_note}:
- Title: {title}
- Description: {description}
- Date: {event_date}
- Domain: {domain}
- Location: {location}
- Confidence: {confidence}
""",
        required_vars=["idx", "event_id", "title", "description", "event_date", "domain", "location", "confidence"],
        optional_vars={"status_note": ""}
    )
    
    # Template for the main generation instruction
    GENERATION_TEMPLATE = PromptTemplate(
        template="""Generate forecast questions based on the following {num_events} events.

{events_text}

Create up to {max_questions} high-quality forecast questions.{domain_filter}

STRATEGY:
1. Review event summaries below (descriptions are truncated)
2. For events that seem interesting, use event_details to get full context
3. Read the complete article content to understand nuances
4. Generate deep, insightful questions that go beyond surface-level facts
5. Store questions using {tool_name} tool

IMPORTANT - Resolution Date Requirements:
- Today's date: {current_date}
- Resolution dates MUST be within this range: {min_resolution_date} to {max_resolution_date}

For PAST EVENTS (already occurred):
  * resolution_date: Use the event date OR shortly after (when outcome became verifiable)
  * Example: Event on 2024-11-09 → resolution_date could be 2024-11-09 or 2024-11-10
  * MUST include ground_truth with the known outcome

For FUTURE EVENTS (not yet occurred):
  * resolution_date: Set between today and {max_resolution_date}
  * Should be realistic (days to months in the future, not years)
  * Example: For event predicted on 2026-01-15, resolution_date could be 2026-01-20

For each question you create:
1. Write the question text (clear, specific, resolvable)
2. Verify resolution_date is within the allowed range
3. Call {tool_name} tool with all required fields:
   - question_text
   - question_type - MUST be EXACTLY one of these (case-sensitive):
     * "boolean" - for yes/no questions (e.g., "Will X happen?")
     * "mcq" - for multiple choice (provide answer options)
     * "quantity" - for numerical answers (e.g., "What percentage...", "How many...")
     * "timeframe" - for "when will X happen" questions
   - domain
   - difficulty (1-5)
   - resolution_date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
     * MUST be between {min_resolution_date} and {max_resolution_date}
   - resolution_criteria (how to verify the answer)
   - related_event_ids (comma-separated)
   - ground_truth (REQUIRED if PAST EVENT, omit if future)
   - cutoff_date (OPTIONAL - will be set during evaluation if needed)
4. {ground_truth_instruction}

CRITICAL - Question Type Validation:
- Use "quantity" NOT "numeric"
- Use "mcq" NOT "multiple_choice"
- These must be exact matches (lowercase)

Guidelines:
- Questions should be specific and unambiguous
- Boolean questions should have clear yes/no answers
- Include a mix of difficulties (1-5)
- Questions should be independently verifiable
- Focus on questions that test real forecasting ability
- Stay within the specified date range!

Return a summary when done.""",
        required_vars=["num_events", "events_text", "max_questions", "current_date", "min_resolution_date", "max_resolution_date"],
        optional_vars={
            "domain_filter": "",
            "tool_name": "question_generator",
            "ground_truth_instruction": "IMPORTANT: If the event already occurred (marked as PAST EVENT), include ground_truth with the known outcome"
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
        include_ground_truth_instruction: bool = True
    ) -> str:
        """Generate instruction for question generation.
        
        Args:
            current_date: Current datetime
            events: List of events to generate questions from
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            description_preview_length: Length of description preview (default: 200)
            tool_name: Name of the tool to call (default: question_generator)
            include_ground_truth_instruction: Whether to include ground truth instruction
            
        Returns:
            Formatted instruction string
        """
        from datetime import timedelta
        
        date_str = self.format_datetime(current_date)
        
        # Calculate resolution date range
        # Min: earliest event date (or current_date - 1 year if no events)
        # Max: current_date + 1 year (reasonable forecasting horizon)
        event_dates = []
        for event in events:
            event_date = event.occurred_date or event.predicted_date
            if event_date:
                event_dates.append(event_date)
        
        if event_dates:
            min_resolution_date = min(event_dates)
        else:
            min_resolution_date = current_date - timedelta(days=365)
        
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
        
        # Build ground truth instruction
        ground_truth_instruction = (
            "IMPORTANT: If the event already occurred (marked as PAST EVENT), include ground_truth with the known outcome"
            if include_ground_truth_instruction
            else "Include ground_truth if the outcome is already known"
        )
        
        # Format the instruction body
        instruction_body = self.GENERATION_TEMPLATE.format(
            num_events=len(events),
            events_text=events_text,
            max_questions=max_questions,
            current_date=date_str,
            min_resolution_date=min_res_str,
            max_resolution_date=max_res_str,
            domain_filter=domain_filter,
            tool_name=tool_name,
            ground_truth_instruction=ground_truth_instruction
        )
        
        return f"Today's date is {date_str}.\n\n{instruction_body}"
    
    @staticmethod
    def format_event_summary(event: Event, idx: int, current_date: datetime) -> str:
        """Static method for backward compatibility.
        
        Args:
            event: Event to format
            idx: Index of the event (1-based)
            current_date: Current datetime for past event detection
            
        Returns:
            Formatted event summary
        """
        generator = QuestionGenerationPrompts()
        return generator.format_item(event, idx, current_date=current_date)
    
    @staticmethod
    def get_generation_instruction(
        current_date: datetime,
        events: List[Event],
        max_questions: int,
        domains: List[str] = None
    ) -> str:
        """Static convenience method for backward compatibility.
        
        Args:
            current_date: Current datetime
            events: List of events to generate questions from
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            
        Returns:
            Formatted instruction string
        """
        generator = QuestionGenerationPrompts()
        return generator.get_instruction(
            current_date=current_date,
            events=events,
            max_questions=max_questions,
            domains=domains
        )
