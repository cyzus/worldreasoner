"""Prompts for question categorization."""

from typing import List, Optional

from src.domain.models import Question, Domain
from src.utils.enums import enum_to_list


CATEGORIZATION_PROMPT = """Categorize these prediction market questions into domains.

Questions:
{questions_text}

Available domains: {available_domains}

Return a JSON object with a "categorizations" key containing an array:
{{"categorizations": [{{"id": "question_id", "domain": "domain_name"}}, ...]}}

Only return the JSON object, nothing else."""


def _format_question(question: Question, idx: int) -> str:
    tags = (
        question.metadata.get("tags", [])
        if hasattr(question, "metadata") and question.metadata
        else []
    )
    tags_list = tags[:3] if isinstance(tags, list) else []
    return (
        f"{idx}. ID: {question.id}\n"
        f"   Q: {question.question_text}\n"
        f"   Tags: {', '.join(tags_list) if tags_list else 'none'}"
    )


def get_instruction(
    questions: List[Question], available_domains: Optional[List[str]] = None
) -> str:
    if available_domains is None:
        available_domains = enum_to_list(Domain)
    questions_text = "\n".join(
        _format_question(q, i) for i, q in enumerate(questions, 1)
    )
    return CATEGORIZATION_PROMPT.format(
        questions_text=questions_text,
        available_domains=", ".join(available_domains),
    )
