"""Shared utility functions for prompt generation."""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d") -> str:
    return dt.strftime(format_str)


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_list(
    items: List[str], separator: str = ", ", empty_value: str = "None"
) -> str:
    return separator.join(items) if items else empty_value


def build_priority_guidance(
    type_hints: Optional[List[str]] = None,
    category_hints: Optional[List[str]] = None,
    time_horizon_hints: Optional[List[str]] = None,
    prefix: str = "\n\n⚠️ COLLECTION PRIORITIES:\n",
) -> str:
    if not type_hints and not category_hints and not time_horizon_hints:
        return ""

    guidance_parts = []
    if type_hints:
        guidance_parts.append(f"PRIORITY TYPES NEEDED: {format_list(type_hints)}")
    if category_hints:
        guidance_parts.append(
            f"PRIORITY CATEGORIES NEEDED: {format_list(category_hints)}"
        )
    if time_horizon_hints:
        from src.config.collection_goal import TimeHorizon

        horizon_descriptions = []
        for h in time_horizon_hints:
            try:
                th = TimeHorizon(h)
                min_d, max_d = TimeHorizon.get_day_range(th)
                horizon_descriptions.append(f"{h} ({min_d}-{max_d} days)")
            except ValueError:
                horizon_descriptions.append(h)
        guidance_parts.append(
            f"PRIORITY TIME HORIZONS NEEDED: {', '.join(horizon_descriptions)}"
        )
        guidance_parts.append(
            "Generate questions where the time between when the question becomes forecastable "
            "(estimated_start_time) and its resolution_date falls within the specified horizon range."
        )

    focus_items = []
    if type_hints:
        focus_items.append("types")
    if category_hints:
        focus_items.append("categories")
    if time_horizon_hints:
        focus_items.append("time horizons")
    return (
        prefix
        + "\n".join(guidance_parts)
        + f"\nFocus on generating questions matching these {'/'.join(focus_items)} first!"
    )


def build_domain_options(
    category_hints: Optional[List[str]] = None, fallback_enum=None
) -> str:
    if category_hints:
        return f"One of ({', '.join(category_hints)})"
    elif fallback_enum:
        from src.utils.enums import enum_to_list

        return f"One of ({', '.join(enum_to_list(fallback_enum))})"
    else:
        return "One of the available domains"


def build_instruction(
    current_date: datetime,
    instruction_body: str,
    include_date_header: bool = True,
) -> str:
    if not include_date_header:
        return instruction_body
    if instruction_body.strip().startswith("Today's date is"):
        return instruction_body
    date_str = format_datetime(current_date)
    return f"Today's date is {date_str}.\n\n{instruction_body}"


def calculate_date_window(
    current_date: datetime,
    require_past_events: bool,
    events: Optional[List] = None,
    future_days: int = 365,
) -> Tuple[datetime, datetime]:
    if require_past_events:
        if events:
            event_dates = [
                e.occurred_date or e.predicted_date
                for e in events
                if (e.occurred_date or e.predicted_date)
                and (e.occurred_date or e.predicted_date) < current_date
            ]
            min_date = (
                min(event_dates)
                if event_dates
                else current_date - timedelta(days=365)
            )
        else:
            min_date = current_date - timedelta(days=365)
        max_date = current_date
    else:
        min_date = current_date
        max_date = current_date + timedelta(days=future_days)
    return min_date, max_date
