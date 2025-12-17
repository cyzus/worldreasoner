"""Prompts for question categorization."""

from typing import List
from src.domain.models import Question, Domain
from src.utils.enums import enum_to_list
from .base import BasePromptGenerator, PromptTemplate

CATEGORIZATION_PROMPT = \
"""Categorize these prediction market questions into domains.

Questions:
{questions_text}

Available domains: {available_domains}

Return a JSON object with a "categorizations" key containing an array:
{{"categorizations": [{{"id": "question_id", "domain": "domain_name"}}, ...]}}

Only return the JSON object, nothing else."""

class QuestionCategorizationPrompts(BasePromptGenerator[Question]):
    """Prompts for categorizing questions into domains."""

    # Template for the categorization instruction
    CATEGORIZATION_TEMPLATE = PromptTemplate(
        template=CATEGORIZATION_PROMPT,
        required_vars=["questions_text", "available_domains"]
    )

    def format_item(
        self,
        item: Question,
        idx: int,
        **context
    ) -> str:
        """Format a single question for categorization.

        Args:
            item: Question to format
            idx: Index of the question (1-based)
            **context: Additional context (not used)

        Returns:
            Formatted question string
        """
        # Extract tags from metadata
        tags = item.metadata.get('tags', []) if hasattr(item, 'metadata') and item.metadata else []
        tags_list = tags[:3] if isinstance(tags, list) else []

        return (
            f"{idx}. ID: {item.id}\n"
            f"   Q: {item.question_text}\n"
            f"   Tags: {', '.join(tags_list) if tags_list else 'none'}"
        )

    def get_instruction(
        self,
        questions: List[Question],
        available_domains: List[str] = None
    ) -> str:
        """Generate instruction for question categorization.

        Args:
            questions: List of questions to categorize
            available_domains: List of available domain names (default: uses Domain enum)

        Returns:
            Formatted instruction string
        """
        # Default domains from Domain enum if not provided
        if available_domains is None:
            available_domains = enum_to_list(Domain)

        # Format all questions
        questions_text = self.format_items(questions)

        # Format the instruction
        return self.CATEGORIZATION_TEMPLATE.format(
            questions_text=questions_text,
            available_domains=", ".join(available_domains)
        )
