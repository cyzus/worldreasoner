"""Prompts for article collection stage."""

from datetime import datetime

from .base import build_instruction


COLLECTION_TEMPLATE = """
Search for news articles through "{source_name}" from the past {days_back} days.
Find up to {max_articles} relevant articles.{domain_context}

For each article you find:
1. Use web_search to find article URLs
2. Use web_fetch to fetch article content
3. Call {tool_name}

Return a summary when done.
"""


def get_instruction(
    current_date: datetime,
    source_name: str,
    days_back: int,
    max_articles: int,
    domain_context: str = "",
    tool_name: str = "article_collector",
) -> str:
    instruction_body = COLLECTION_TEMPLATE.format(
        source_name=source_name,
        days_back=days_back,
        max_articles=max_articles,
        domain_context=domain_context,
        tool_name=tool_name,
    )
    return build_instruction(current_date, instruction_body)
