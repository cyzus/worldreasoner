"""Shared utilities for event analysis - timeline, coverage, and quality metrics.

These utilities can be used to analyze event temporal distribution in causal graphs,
similar to how article_analysis.py analyzes article coverage.
"""

from typing import List, Dict, Optional
from collections import defaultdict
from datetime import datetime

from src.domain.models import Event


def analyze_event_timeline(
    events: List[Event],
    resolution_date: datetime,
    coverage_start: Optional[datetime] = None,
) -> Dict:
    """Analyze temporal distribution of events.

    Args:
        events: List of events
        resolution_date: Question resolution date (coverage endpoint)
        coverage_start: Optional expected start of coverage (e.g., estimated_start_time)

    Returns:
        Timeline statistics including:
        - has_dates: Whether events have date information
        - earliest: Earliest event date
        - latest: Latest event date (should be before resolution_date)
        - resolution_date: Question resolution date
        - span_days: Days between earliest event and latest event
        - expected_span_days: Days between coverage_start and resolution (if coverage_start provided)
        - monthly: Monthly event counts
        - dates: Sorted list of all event dates
    """
    dates = [e.occurred_date for e in events if e.occurred_date]

    result = {"has_dates": False, "resolution_date": resolution_date}

    # Calculate expected span if coverage_start is provided
    if coverage_start:
        result["expected_span_days"] = (resolution_date - coverage_start).days

    if not dates:
        return result

    dates.sort()
    earliest = dates[0]
    latest = dates[-1]
    span_days = (latest - earliest).days

    # Group by month for visualization
    monthly = defaultdict(int)
    for date in dates:
        month_key = date.strftime("%Y-%m")
        monthly[month_key] += 1

    result.update(
        {
            "has_dates": True,
            "earliest": earliest,
            "latest": latest,
            "span_days": span_days,
            "monthly": dict(monthly),
            "dates": dates,
        }
    )

    return result


def identify_event_gaps(timeline_data: Dict, min_gap_days: int = 30) -> List[Dict]:
    """Identify significant time gaps in event coverage.

    Args:
        timeline_data: Timeline analysis data from analyze_event_timeline()
        min_gap_days: Minimum gap size in days to report (default: 30)

    Returns:
        List of identified gaps with start, end, and duration in days
    """
    if not timeline_data.get("has_dates"):
        return []

    gaps = []
    dates = timeline_data["dates"]

    # Find gaps larger than min_gap_days
    for i in range(len(dates) - 1):
        gap_days = (dates[i + 1] - dates[i]).days
        if gap_days > min_gap_days:
            gaps.append({"start": dates[i], "end": dates[i + 1], "days": gap_days})

    return gaps


def calculate_event_gap_severity(gaps: List[Dict], timeline_span_days: int) -> float:
    """Calculate gap severity considering both absolute and relative size.

    Uses more lenient thresholds than article gaps since events are naturally
    more sparse than articles.

    Args:
        gaps: List of timeline gaps from identify_event_gaps()
        timeline_span_days: Total span of the coverage window in days

    Returns:
        Total gap severity penalty (0-1)
    """
    if not gaps or timeline_span_days <= 0:
        return 0.0

    total_penalty = 0.0
    for gap in gaps:
        gap_days = gap["days"]

        # Absolute penalty: more lenient for events than articles
        # 30-60 days: mild, 60-120 days: moderate, 120+ days: severe
        if gap_days <= 60:
            absolute_penalty = 0.05
        elif gap_days <= 120:
            absolute_penalty = 0.10
        elif gap_days <= 180:
            absolute_penalty = 0.20
        else:
            absolute_penalty = 0.30

        # Relative penalty: gap as % of total timeline
        relative_penalty = min(gap_days / timeline_span_days * 0.5, 0.3)

        # Combined penalty (take maximum to penalize both large absolute and relative gaps)
        total_penalty += max(absolute_penalty, relative_penalty)

    return min(total_penalty, 1.0)  # Cap at 1.0


def calculate_early_event_gap_penalty(
    earliest_event: datetime, coverage_start: datetime, timeline_span_days: int
) -> float:
    """Penalize missing event coverage at start of window.

    Args:
        earliest_event: Date of earliest event
        coverage_start: Expected start of coverage window
        timeline_span_days: Total span of the coverage window in days

    Returns:
        Early gap penalty (0-0.25)
    """
    if earliest_event <= coverage_start:
        return 0.0

    early_gap_days = (earliest_event - coverage_start).days

    # More lenient than articles - events at start may be harder to identify
    if early_gap_days <= 30:
        return 0.05
    elif early_gap_days <= 90:
        return 0.15
    else:
        return 0.25


def calculate_event_distribution_score(timeline_data: Dict) -> float:
    """Score based on how evenly events are distributed across timeline.

    Uses coefficient of variation to measure distribution evenness.
    More lenient than article distribution since events are naturally more sparse.

    Args:
        timeline_data: Timeline statistics from analyze_event_timeline()

    Returns:
        Distribution score (0-1), where 1.0 is perfectly even distribution
    """
    if not timeline_data.get("has_dates") or not timeline_data.get("monthly"):
        return 0.0

    monthly_counts = list(timeline_data["monthly"].values())
    if len(monthly_counts) <= 1:
        return 0.5  # Only one month has events

    # Calculate coefficient of variation (lower = more even distribution)
    mean = sum(monthly_counts) / len(monthly_counts)
    if mean == 0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in monthly_counts) / len(monthly_counts)
    std_dev = variance**0.5
    cv = std_dev / mean

    # Convert CV to score - more lenient for events
    # Events are naturally less evenly distributed than articles
    return max(0.0, min(1.0 - (cv / 3.0), 1.0))


def calculate_event_temporal_quality(
    events: List[Event],
    timeline_data: Dict,
    gaps: List[Dict],
    coverage_start: Optional[datetime] = None,
) -> Dict:
    """Calculate temporal coverage quality for events.

    Focuses on temporal distribution and gap analysis, not volume (since event
    count is already tracked separately in graph stats).

    Args:
        events: List of events
        timeline_data: Timeline statistics from analyze_event_timeline()
        gaps: Timeline gaps from identify_event_gaps()
        coverage_start: Expected start of coverage window (e.g., estimated_start_time)

    Returns:
        Quality metrics including:
        - temporal_score: Overall temporal quality score (0-1)
        - coverage_score: Score based on timeline gaps (0-1)
        - distribution_score: Score based on temporal distribution evenness (0-1)
        - gap_severity: Total gap severity penalty (0-1)
        - early_gap_penalty: Penalty for missing early coverage (0-0.25)
    """
    if not timeline_data.get("has_dates"):
        return {
            "temporal_score": 0.0,
            "coverage_score": 0.0,
            "distribution_score": 0.0,
            "gap_severity": 0.0,
            "early_gap_penalty": 0.0,
        }

    # Use expected span (coverage_start to resolution) if available,
    # otherwise fall back to event span (earliest to latest)
    timeline_span = timeline_data.get("expected_span_days", timeline_data["span_days"])

    # Gap severity penalty — attenuated when events span most of the window.
    # If span_coverage >= 80%, interior gaps matter less: severity scales down
    # linearly so that full span coverage reduces it by up to 40%.
    gap_severity = calculate_event_gap_severity(gaps, timeline_span)
    if timeline_span > 0 and gap_severity > 0:
        span_coverage = min(timeline_data["span_days"] / timeline_span, 1.0)
        gap_severity *= max(1.0 - span_coverage * 0.4, 0.6)

    # Early coverage gap penalty
    early_gap_penalty = 0.0
    if coverage_start and timeline_data.get("earliest"):
        early_gap_penalty = calculate_early_event_gap_penalty(
            timeline_data["earliest"], coverage_start, timeline_span
        )

    # Distribution score (how evenly events are spread)
    distribution_score = calculate_event_distribution_score(timeline_data)

    # Combined coverage score
    # Start at 1.0, apply penalties, blend with distribution score
    coverage_score = max(0.0, 1.0 - gap_severity - early_gap_penalty)
    coverage_score = (coverage_score * 0.7) + (distribution_score * 0.3)

    # Overall temporal quality (weighted combination)
    temporal_score = coverage_score

    return {
        "temporal_score": temporal_score,
        "coverage_score": coverage_score,
        "distribution_score": distribution_score,
        "gap_severity": gap_severity,
        "early_gap_penalty": early_gap_penalty,
    }


def get_event_temporal_recommendation(
    quality: Dict,
    gaps: List[Dict],
    timeline_data: Dict,
    coverage_start: Optional[datetime] = None,
) -> str:
    """Generate actionable recommendation based on event temporal coverage.

    Args:
        quality: Quality metrics from calculate_event_temporal_quality()
        gaps: Timeline gaps from identify_event_gaps()
        timeline_data: Timeline statistics from analyze_event_timeline()
        coverage_start: Expected start of coverage window

    Returns:
        Human-readable recommendation string
    """
    if quality["temporal_score"] >= 0.8:
        return "✓ Excellent temporal coverage! Events are well-distributed across the timeline."

    issues = []

    if not timeline_data.get("has_dates"):
        return "⚠ No event dates available - cannot assess temporal coverage"

    if quality.get("early_gap_penalty", 0) > 0.1 and coverage_start:
        earliest = timeline_data.get("earliest")
        if earliest:
            gap_days = (earliest - coverage_start).days
            issues.append(
                f"Missing early events (first event {gap_days} days after start)"
            )

    if gaps:
        top_gap = max(gaps, key=lambda g: g["days"])
        issues.append(
            f"Large time gap: {top_gap['start'].strftime('%Y-%m-%d')} to "
            f"{top_gap['end'].strftime('%Y-%m-%d')} ({top_gap['days']} days)"
        )

    if quality["distribution_score"] < 0.5:
        issues.append("Events are clustered unevenly across timeline")

    if issues:
        return (
            "⚠ "
            + " | ".join(issues)
            + "\n  → Consider identifying intermediate events to fill temporal gaps"
        )

    return "Fair temporal coverage, but could be improved with better distribution."
