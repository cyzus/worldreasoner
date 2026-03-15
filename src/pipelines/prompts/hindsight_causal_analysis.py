"""Prompts for hindsight causal analysis using multi-agent system."""

from typing import List, Optional

from src.domain.models import Question

from .base import format_datetime


# ---------------------------------------------------------------------------
# Evidence agent
# ---------------------------------------------------------------------------

_EVIDENCE_ROLE = """
# Role
Specialist agent for collecting evidence articles.
"""

_EVIDENCE_GUIDELINES = """
# Guidelines
- Be multifaceted - look for causes supporting ground truth AND alternative outcome paths
- Work backwards from resolution date
- Prioritize high-quality sources and diverse perspectives
- Fetch article content and capture correct published dates (all BEFORE resolution date)
- Use article_collector to save articles (target: {min_evidence_articles}+ articles)
- Before submission, use article_inspector to check timeline coverage
- Fill any gaps by collecting more articles from those periods
"""

EVIDENCE_AGENT_DESCRIPTION = _EVIDENCE_ROLE + _EVIDENCE_GUIDELINES


# ---------------------------------------------------------------------------
# Manager agent
# ---------------------------------------------------------------------------

_MANAGER_ROLE = """
Your task: make a comprehensive causal analysis for this question with hindsight.
The question has already been resolved with a known ground truth.
"""

_MANAGER_CONTEXT = """
# Context
- **Question:** {question_text}
- **Resolution date:** {resolution_date}
- **Ground truth (known outcome):** {ground_truth}

# Outcome Events
{outcome_events_info}
{market_turning_points_section}
"""

_MANAGER_COLLECT_EVIDENCE = """
# Step 1 — Collect Evidence
- Delegate to `evidence_collector` to gather and store relevant articles
- Time window: {window_start} to {resolution_date} ({actual_window_days} days)
- Target: {min_evidence_articles}+ high-quality articles spread across different dates
- After collection, inspect the results yourself with article_inspector
- If coverage is insufficient, repeat — without enough evidence there is no causal graph
{turning_points_evidence_hint}
"""

_MANAGER_WRITE_EXPLANATION = """
# Step 2 — Write Causal Explanation
1. Call get_question_articles to get the collected articles and their exact IDs
2. Use article_retrieval to read full content of key articles before writing

Write a comprehensive markdown report explaining **how and why** the outcome came about.
Use the exact heading structure below so downstream validation and graph extraction can rely on it.

# Required Output Format (use these exact section headings)

## Executive Summary
- 3-6 sentences summarizing the dominant causal path to the known outcome.

## Timeline Of Key Events
- Chronological bullet list with explicit dates (and times when possible).
- Events should span the full window but focus on critical moments.
- Include event-level article citations inline.

## Causal Chain Analysis
- Explain root causes -> intermediate mechanisms -> proximate triggers -> final outcome.
- Use explicit causal language (caused, triggered, led to, resulted in, because).
- Include at least one citation for each major causal step.

## Countervailing Factors
- Document important forces that pushed against the actual outcome.
- Explain why they failed or were overwhelmed.

## Event Candidate Inventory
- Enumerate graph-ready event candidates as E1, E2, E3... in markdown bullets.
- For each event candidate include:
    - title
    - date (or bounded date range with uncertainty note)
    - why it matters causally
    - source article IDs

## Evidence Mapping Table
- Add a markdown table mapping major claims/events to evidence.
- Use columns: Claim/Event | Article IDs | Date Support | Confidence (0-1) | Notes

## Uncertainties And Alternative Paths
- Briefly list unresolved uncertainty and plausible alternative causal paths.

Quality requirements:
- Provide broad source coverage (do not rely on only a few articles).
- Cite exact article IDs inline (e.g. [art_tech_20240101_001_abc]).
- Keep the report specific and evidence-grounded, not generic.

Call save_explanation to store it. If it returns warnings, address them and save again before finishing.
"""

_MANAGER_TEMPLATE = (
    _MANAGER_ROLE
    + _MANAGER_CONTEXT
    + _MANAGER_COLLECT_EVIDENCE
    + _MANAGER_WRITE_EXPLANATION
)

# Public alias used by HindsightAgent (imports this name)
MANAGER_AGENT_DESCRIPTION = _MANAGER_TEMPLATE


# ---------------------------------------------------------------------------
# Market signal templates
# ---------------------------------------------------------------------------

_LEAD_CHANGES_SECTION = """
## Lead Changes (market prediction flipped)
These are moments when the favored outcome changed — critical events to investigate:
{items}
"""

_TURNING_POINTS_SECTION = """
## Turning Points (significant price reversals)
Moments when market sentiment shifted significantly:
{items}
"""

_CRITICAL_DATES_HINT = (
    "- **Critical dates** (lead changes — prediction flipped): {dates}\n"
    "  Find what news caused the market to flip its prediction on these dates."
)

_PRIORITY_DATES_HINT = (
    "- **Priority dates** (turning points): {dates}\n"
    "  Search for news around these dates — they mark significant sentiment shifts."
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_outcome_events(outcome_events: Optional[List]) -> str:
    if not outcome_events:
        return "No pre-created outcomes available."
    lines = []
    for event in outcome_events:
        scenario = f" ({event.outcome_scenario.value})" if event.outcome_scenario else ""
        is_actual = " [TARGET GROUND TRUTH]" if event.is_actual_outcome else ""
        lines.append(f"- {event.title}{scenario}{is_actual}")
    return "\n".join(lines)


def _format_lead_change(lc: dict) -> str:
    from datetime import datetime as dt
    lc_time = dt.fromtimestamp(lc["timestamp"])
    price_pct = lc["price"] * 100
    prev_pct = lc["previous_price"] * 100
    if lc["direction"] == "above":
        desc = f"'Yes' became favored (crossed above 50%: {prev_pct:.1f}% → {price_pct:.1f}%)"
    else:
        desc = f"'No' became favored (crossed below 50%: {prev_pct:.1f}% → {price_pct:.1f}%)"
    time_info = ""
    if lc.get("time_in_previous_state_hours"):
        time_info = f" [held previous state for {lc['time_in_previous_state_hours']:.1f}h]"
    return f"- {lc_time.strftime('%Y-%m-%d %H:%M')}: {desc}{time_info}"


def _format_turning_point(tp: dict) -> str:
    from datetime import datetime as dt
    tp_time = dt.fromtimestamp(tp["timestamp"])
    if tp["type"] == "peak":
        direction_desc = f"rose {tp['change_before']:.1f}pp then fell {abs(tp['change_after']):.1f}pp"
    else:
        direction_desc = f"dropped {abs(tp['change_before']):.1f}pp then recovered {tp['change_after']:.1f}pp"
    return (
        f"- {tp['type'].capitalize()} on {tp_time.strftime('%Y-%m-%d %H:%M')}: "
        f"price {direction_desc} (significance: {tp['significance']:.1f})"
    )


def _format_turning_points_section(
    turning_points: Optional[List], lead_changes: Optional[List] = None
) -> str:
    parts = []
    if lead_changes:
        items = "\n".join(_format_lead_change(lc) for lc in lead_changes)
        parts.append(_LEAD_CHANGES_SECTION.format(items=items))
    if turning_points:
        items = "\n".join(_format_turning_point(tp) for tp in turning_points[:5])
        parts.append(_TURNING_POINTS_SECTION.format(items=items))
    return "\n".join(parts)


def _format_turning_points_hint(
    turning_points: Optional[List], lead_changes: Optional[List] = None
) -> str:
    from datetime import datetime as dt

    critical_dates: List[str] = []
    priority_dates: List[str] = []

    if lead_changes:
        for lc in lead_changes:
            date_str = dt.fromtimestamp(lc["timestamp"]).strftime("%Y-%m-%d")
            if date_str not in critical_dates:
                critical_dates.append(date_str)

    if turning_points:
        for tp in turning_points[:5]:
            date_str = dt.fromtimestamp(tp["timestamp"]).strftime("%Y-%m-%d")
            if date_str not in priority_dates and date_str not in critical_dates:
                priority_dates.append(date_str)

    lines = []
    if critical_dates:
        lines.append(_CRITICAL_DATES_HINT.format(dates=", ".join(critical_dates)))
    if priority_dates:
        lines.append(_PRIORITY_DATES_HINT.format(dates=", ".join(priority_dates)))
    return "\n".join(lines)


def get_prompt(
    question: Question,
    min_evidence_articles: int,
    evidence_window_days: int,
    min_graph_depth: int,
    confidence_threshold: float,
    outcome_events: Optional[List] = None,
    turning_points: Optional[List] = None,
    lead_changes: Optional[List] = None,
) -> str:
    from src.services.temporal_filter_service import TemporalFilterService

    window_start, window_end = TemporalFilterService.get_evidence_window(
        question.resolution_date,
        question.estimated_start_time,
        fallback_window_days=evidence_window_days,
    )

    resolution_date_str = format_datetime(question.resolution_date)
    window_start_str = format_datetime(window_start)
    actual_window_days = (window_end - window_start).days

    return MANAGER_AGENT_DESCRIPTION.format(
        question_text=question.question_text,
        resolution_date=resolution_date_str,
        window_start=window_start_str,
        actual_window_days=actual_window_days,
        ground_truth=str(question.ground_truth),
        outcome_events_info=_format_outcome_events(outcome_events),
        market_turning_points_section=_format_turning_points_section(
            turning_points, lead_changes
        ),
        turning_points_evidence_hint=_format_turning_points_hint(
            turning_points, lead_changes
        ),
        min_graph_depth=min_graph_depth,
        min_evidence_articles=min_evidence_articles,
        confidence_threshold=confidence_threshold,
    )
