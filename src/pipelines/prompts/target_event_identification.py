"""Prompts for target event identification stage."""

from datetime import datetime
from src.domain.models import Question
from .base import BasePromptGenerator, PromptTemplate

TARGET_EVENT_IDENTIFICATION_PROMPT = \
"""You are analyzing a resolved forecast question to identify the target event (what actually happened).

Question: {question_text}
Question Type: {question_type}
Ground Truth: {ground_truth}
Resolution Date: {resolution_date}
Domain: {domain}

Based on this information, describe the EVENT that occurred (or didn't occur) in a clear, factual way.

Guidelines:
- Be specific and concrete
- Use past tense (the event already happened or didn't happen)
- Focus on WHAT happened, not WHY
- Keep it under 150 characters
- If ground_truth is False/No, phrase it as "X did NOT happen" or describe what happened instead

Examples:
Question: "Will Bitcoin reach $100,000 by Dec 31, 2024?"
Ground Truth: True
→ "Bitcoin reaches $100,000 USD"

Question: "Will Donald Trump win the 2024 US Presidential Election?"
Ground Truth: True
→ "Donald Trump wins 2024 US Presidential Election"

Question: "Will there be a recession in 2024?"
Ground Truth: False
→ "No recession occurs in 2024"

Return a JSON object with the event description:
{{"event_description": "your event description here"}}

Only return the JSON object, nothing else."""

class TargetEventIdentificationPrompts(BasePromptGenerator[Question]):
    """Prompts for identifying target events from resolved questions."""

    # Template for event extraction instruction
    EXTRACTION_TEMPLATE = PromptTemplate(
        template=TARGET_EVENT_IDENTIFICATION_PROMPT,
        required_vars=["question_text", "question_type", "ground_truth", "resolution_date", "domain"]
    )

    def format_item(self, item: Question, idx: int, **context) -> str:
        """Format a single question for the prompt.

        Args:
            item: Question to format
            idx: Index of the question (not used for this prompt)
            **context: Additional context (not used)

        Returns:
            Formatted question (not typically used for individual formatting)
        """
        # This generator doesn't use list formatting, but we implement for interface compliance
        return f"{idx}. {item.question_text}"

    def get_instruction(
        self,
        question: Question,
        current_date: datetime = None,
        **kwargs
    ) -> str:
        """Generate instruction for extracting target event from a question.

        Args:
            question: Question to analyze
            current_date: Current datetime (optional, not used in this prompt)
            **kwargs: Additional context (not used)

        Returns:
            Formatted instruction string
        """
        # Format resolution date
        resolution_date_str = self.format_datetime(question.resolution_date)

        # Build the instruction
        return self.EXTRACTION_TEMPLATE.format(
            question_text=question.question_text,
            question_type=question.question_type.value,
            ground_truth=str(question.ground_truth),
            resolution_date=resolution_date_str,
            domain=question.domain.value
        )
