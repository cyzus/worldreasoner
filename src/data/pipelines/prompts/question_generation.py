"""Prompts for question generation stage."""

from datetime import datetime
from typing import List, Optional
from ...models import Event
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

For each question you create:
1. Write the question text (clear, specific, resolvable)
2. Call {tool_name} tool to store it with all required fields
3. Include related event IDs
4. {ground_truth_instruction}

Guidelines:
- Questions should be specific and unambiguous
- Boolean questions should have clear yes/no answers
- Include a mix of difficulties (1-5)
- Resolution dates should be realistic (days to months in future)
- For past events, provide ground_truth based on the event description
- Questions should be independently verifiable

Return a summary when done.""",
        required_vars=["num_events", "events_text", "max_questions"],
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
        date_str = self.format_datetime(current_date)
        
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
