"""Prompts for question generation stage."""

from datetime import datetime
from typing import List, Optional

from src.domain.models import Event

from .base import (
    build_instruction,
    build_priority_guidance,
    calculate_date_window,
    format_datetime,
    format_list,
    truncate_text,
)


EVENT_TEMPLATE = """
Event {idx} (ID: {event_id}){status_note}:
- Title: {title}
- Description: {description}
- Date: {event_date}
- Domain: {domain}
- Confidence: {confidence}
"""

SHARED_RULES_DESC = """
QUALITY:
- Broad appeal s.t. people are interested to answer (elections, major companies, crypto, policy, sports)
- Skip niche topics requiring insider knowledge
- Ask "Will X happen?" not "Which company will..." (don't assume outcomes)
- MCQ options from actual event participants only
- Use FUTURE tense when formating all the questions

FORECAST WINDOW (provide at least one):
- estimated_start_time: exact ISO 8601 datetime when the question became forecastable
  * For event-based questions: when the event was first announced/publicly known
  * For trend questions: when baseline data became available
  * For policy questions: when the policy was first proposed
  * MUST be before resolution_date
- time_horizon: 'short' / 'medium' / 'long' when the exact date is unknown
  * short = up to 7 days (e.g. match result, earnings release)
  * medium = ~30 days (e.g. monthly policy decision, product launch)
  * long = ~180 days (e.g. annual election, multi-month trend)
- Prefer estimated_start_time when the specific announcement date is known

RESOLUTION DATE:
- When the event has already been resolved

A good answering window for a forecast question will be between ESTIMATED START TIME and RESOLUTION DATE.
- If the date goes beyond the resolution date, the answer will be retrieved.
- If the date goes before the estimated start time, some conditional events or contexts might not be available.

"""

ARTICLE_TEMPLATE = """
Article {idx} (Source: {source}):
- Title: {title}
- Date: {published_date}
- Content: {content}
"""

RULES_GROUND_TRUTH = """RULES:
- Today: {current_date} → MAKE SURE that: {current_date} >= resolution_date >= estimated_start_time (or resolution_date - time_horizon offset)
- ground_truth = past outcome only (YES/NO/value, never future dates)
- resolution_date: when the event has already been resolved
- Alternate binary answers: YES, NO, YES, NO (avoid bias)
- Use round numbers ($100K, 1M users) not oddly specific values
- Format questions using the future tense as if they are in the future (even though all the events are already resolved)
- Natural deadlines ("by end of Q4 202X" or "by end of Oct 202X" not "by Oct 27")"""

RULES_FUTURE = """RULES:
- Today: {current_date} → MAKE SURE that: resolution_date > {current_date} >= estimated_start_time (or resolution_date - time_horizon offset)
- NO ground_truth (outcomes unknown)
- resolution_date: 1 week to 1+ year in future
- Balance binary predictions: ~50% likely YES, ~50% likely NO
- Use round numbers ($100K, 1M users) not oddly specific values
- Natural deadlines ("by end of Q1 202X" not "by Mar 15")"""


QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH = (
    """
You are creating questions to assess the AI forecast capabilities.
AI will answer the questions in a control environment as if it was the day before the resolution_date.
Create {max_questions} forecast questions from already RESOLVED events.{domain_filter}

{events_text}

"""
    + RULES_GROUND_TRUTH
    + SHARED_RULES_DESC
)


QUESTION_GENERATION_TEMPLATE_FUTURE = (
    """
You are creating questions to assess the AI forecast capabilities.
AI will answer the questions in an open environment.
Create {max_questions} forecast questions about FUTURE events.{domain_filter}

{events_text}

"""
    + RULES_FUTURE
    + SHARED_RULES_DESC
)


ARTICLE_HEADER = """Analyze these {num_articles} news articles and generate {max_questions} forecast questions.{domain_filter}

TRUSTED SOURCES:
{sources_text}

{articles_text}

INSTRUCTIONS:
- Identify the key events/claims in these articles.
- Use web search and web fetch if you think the articles are not enough.
- Create questions that forecast the outcomes of these events.
- If multiple articles discuss the same event, consolidate them into a single question.
"""

ARTICLE_QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH = (
    ARTICLE_HEADER + RULES_GROUND_TRUTH + SHARED_RULES_DESC
)

ARTICLE_QUESTION_GENERATION_TEMPLATE_FUTURE = (
    ARTICLE_HEADER + RULES_FUTURE + SHARED_RULES_DESC
)


def _format_event(
    item: Event,
    idx: int,
    current_date: datetime,
    content_preview_length: int = 200,
) -> str:
    event_date = item.occurred_date or item.predicted_date
    is_past_event = event_date and event_date < current_date if event_date else False
    status_note = (
        " (RESOLVED EVENT - questions should include ground_truth)"
        if is_past_event
        else ""
    )
    description = truncate_text(item.description, content_preview_length)
    confidence = item.metadata.get("confidence", 0.8) if item.metadata else 0.8
    return EVENT_TEMPLATE.format(
        idx=idx,
        event_id=item.id,
        status_note=status_note,
        title=item.title,
        description=description,
        event_date=event_date,
        domain=item.domain,
        confidence=confidence,
    )


def get_instruction(
    current_date: datetime,
    events: List[Event],
    max_questions: int,
    domains: Optional[List[str]] = None,
    content_preview_length: int = 200,
    tool_name: str = "question_generator",
    require_ground_truth: bool = True,
    type_hints: Optional[List[str]] = None,
    category_hints: Optional[List[str]] = None,
    time_horizon_hints: Optional[List[str]] = None,
) -> str:
    min_resolution_date, max_resolution_date = calculate_date_window(
        current_date=current_date,
        require_past_events=require_ground_truth,
        events=events,
    )

    min_res_str = format_datetime(min_resolution_date)
    max_res_str = format_datetime(max_resolution_date)
    date_str = format_datetime(current_date)

    events_text = "\n".join(
        _format_event(e, i, current_date, content_preview_length)
        for i, e in enumerate(events, 1)
    )

    domain_filter = f" Focus on domains: {format_list(domains)}." if domains else ""

    priority_guidance = build_priority_guidance(
        type_hints=type_hints,
        category_hints=category_hints,
        time_horizon_hints=time_horizon_hints,
    )

    if require_ground_truth:
        instruction_body = QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH.format(
            num_events=len(events),
            events_text=events_text,
            max_questions=max_questions,
            current_date=date_str,
            min_resolution_date=min_res_str,
            domain_filter=domain_filter,
            tool_name=tool_name,
        )
    else:
        instruction_body = QUESTION_GENERATION_TEMPLATE_FUTURE.format(
            num_events=len(events),
            events_text=events_text,
            max_questions=max_questions,
            current_date=date_str,
            max_resolution_date=max_res_str,
            domain_filter=domain_filter,
            tool_name=tool_name,
        )

    if priority_guidance:
        instruction_body = instruction_body + priority_guidance

    return build_instruction(current_date, instruction_body)


def get_article_instruction(
    current_date: datetime,
    articles: List,
    max_questions: int,
    domains: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    tool_name: str = "batch_question_generator",
    require_ground_truth: bool = True,
    type_hints: Optional[List[str]] = None,
    category_hints: Optional[List[str]] = None,
    time_horizon_hints: Optional[List[str]] = None,
) -> str:
    date_str = format_datetime(current_date)

    articles_text_parts = []
    for idx, article in enumerate(articles, 1):
        content = article.content
        if len(content) > 500:
            content = content[:500] + "..."
        pub_date = (
            article.published_date.strftime("%Y-%m-%d")
            if article.published_date
            else "Unknown"
        )
        articles_text_parts.append(
            ARTICLE_TEMPLATE.format(
                idx=idx,
                source=article.source,
                title=article.title,
                published_date=pub_date,
                content=content,
            )
        )

    articles_text = "\n".join(articles_text_parts)
    domain_filter = f" Focus on domains: {format_list(domains)}." if domains else ""
    sources_text = (
        format_list(sources) if sources else "No specific trusted sources provided."
    )

    template = (
        ARTICLE_QUESTION_GENERATION_TEMPLATE_GROUND_TRUTH
        if require_ground_truth
        else ARTICLE_QUESTION_GENERATION_TEMPLATE_FUTURE
    )

    instruction_body = template.format(
        num_articles=len(articles),
        articles_text=articles_text,
        sources_text=sources_text,
        max_questions=max_questions,
        current_date=date_str,
        domain_filter=domain_filter,
        tool_name=tool_name,
    )

    priority_guidance = build_priority_guidance(
        type_hints=type_hints,
        category_hints=category_hints,
        time_horizon_hints=time_horizon_hints,
    )
    if priority_guidance:
        instruction_body = instruction_body + priority_guidance

    return build_instruction(current_date, instruction_body)
