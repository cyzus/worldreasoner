"""Shared formatting utilities for inspector tools.

Provides reusable formatting functions for consistent visualization across
graph_inspector, article_inspector, and other inspector tools.
"""

from typing import List, Dict, Optional
from datetime import datetime
from src.utils.date_utils import ensure_timezone_aware


def format_inspector_header(title: str, width: int = 64) -> str:
    """Format a box header with centered title.

    Args:
        title: Title text to display
        width: Total width of the box (default: 64)

    Returns:
        Formatted header string with box characters
    """
    # Calculate padding for centered title
    padding = (width - len(title) - 2) // 2
    title_line = "║" + " " * padding + title + " " * (width - len(title) - padding - 2) + "║"

    return f"""
╔{"=" * (width - 2)}╗
{title_line}
╚{"=" * (width - 2)}╝
"""


def format_section_header(title: str, width: int = 64) -> List[str]:
    """Format section title with separator line.

    Args:
        title: Section title
        width: Width of separator line (default: 64)

    Returns:
        List of formatted lines
    """
    return [
        "",
        title,
        "━" * width,
        ""
    ]


def format_time_window(
    resolution_date: datetime,
    estimated_start_time: Optional[datetime] = None,
    indent: str = "  "
) -> List[str]:
    """Format time window display for question context.

    Args:
        resolution_date: Question resolution date
        estimated_start_time: Optional question start time
        indent: Indentation prefix (default: "  ")

    Returns:
        List of formatted lines showing time window
    """
    q_resolution = ensure_timezone_aware(resolution_date)
    q_start = ensure_timezone_aware(estimated_start_time) if estimated_start_time else None

    lines = []
    if q_start:
        lines.append(
            f"{indent}Time Window: {q_start.strftime('%Y-%m-%d')} "
            f"→ {q_resolution.strftime('%Y-%m-%d')}"
        )
        window_days = (q_resolution - q_start).days
        lines.append(f"{indent}Window Span: {window_days} days")
    else:
        lines.append(f"{indent}Resolution Date: {q_resolution.strftime('%Y-%m-%d')}")

    return lines


def format_coverage_range(
    earliest: datetime,
    latest: datetime,
    resolution_date: datetime,
    estimated_start_time: Optional[datetime],
    span_days: int,
    item_type: str = "Item",
    indent: str = "  "
) -> List[str]:
    """Format coverage range display with early gap detection.

    Args:
        earliest: Earliest item date
        latest: Latest item date
        resolution_date: Question resolution date
        estimated_start_time: Optional question start time
        span_days: Days between earliest and latest
        item_type: Type of items (e.g., "Article", "Event")
        indent: Indentation prefix (default: "  ")

    Returns:
        List of formatted lines showing coverage range
    """
    q_resolution = ensure_timezone_aware(resolution_date)
    q_start = ensure_timezone_aware(estimated_start_time) if estimated_start_time else None
    earliest = ensure_timezone_aware(earliest)
    latest = ensure_timezone_aware(latest)

    lines = []
    lines.append(
        f"{indent}{item_type} Range:  {earliest.strftime('%Y-%m-%d')} "
        f"→ {latest.strftime('%Y-%m-%d')} "
        f"({span_days} days)"
    )

    # Note if items don't cover the full window
    if q_start and earliest > q_start:
        gap_days = (earliest - q_start).days
        lines.append(f"{indent}⚠ Missing early coverage: {gap_days} days gap from start")

    return lines


def render_monthly_bar_chart(
    monthly_data: Dict[str, int],
    item_type: str = "items",
    indent: str = "  ",
    bar_width: int = 30
) -> List[str]:
    """Render a monthly bar chart showing item distribution.

    Args:
        monthly_data: Dictionary mapping month strings (YYYY-MM) to counts
        item_type: Type of items for label (e.g., "Articles", "Events")
        indent: Indentation prefix (default: "  ")
        bar_width: Maximum width of bars in characters (default: 30)

    Returns:
        List of formatted lines with bar chart
    """
    if not monthly_data:
        return [f"{indent}No monthly data available", ""]

    lines = [f"{indent}{item_type} by Month:"]
    max_count = max(monthly_data.values())

    for month in sorted(monthly_data.keys()):
        count = monthly_data[month]
        bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
        bar = "█" * bar_len
        lines.append(f"{indent}  {month}: {bar} ({count})")

    lines.append("")
    return lines


def format_timeline_gaps(
    gaps: List[Dict],
    min_gap_label: str,
    max_display: int = 5,
    indent: str = "  ",
    compact: bool = False
) -> List[str]:
    """Format timeline gaps display.

    Args:
        gaps: List of gap dictionaries with 'start', 'end', and 'days' keys
        min_gap_label: Label for minimum gap size (e.g., ">7 days", ">30 days")
        max_display: Maximum number of gaps to display (default: 5)
        indent: Indentation prefix (default: "  ")
        compact: If True, use compact single-line format (default: False)

    Returns:
        List of formatted lines showing gaps
    """
    if not gaps:
        return []

    lines = []
    if not compact:
        lines.extend([
            "",
            f"TIMELINE GAPS ({min_gap_label})",
            "━" * 64,
            ""
        ])
    else:
        lines.append(f"{indent}Timeline Gaps ({min_gap_label}):")

    for gap in gaps[:max_display]:
        if compact:
            lines.append(
                f"{indent}  ⚠ {gap['start'].strftime('%Y-%m-%d')} → "
                f"{gap['end'].strftime('%Y-%m-%d')} ({gap['days']} days)"
            )
        else:
            lines.append(f"{indent}⚠ {gap['start'].strftime('%Y-%m-%d')} → {gap['end'].strftime('%Y-%m-%d')}")
            lines.append(f"{indent}   Gap: {gap['days']} days")

    lines.append("")
    return lines


def format_quality_metrics(
    metrics: Dict[str, float],
    labels: Dict[str, str],
    indent: str = "  ",
    precision: int = 2
) -> List[str]:
    """Format quality metrics with aligned labels.

    Args:
        metrics: Dictionary of metric names to values
        labels: Dictionary mapping metric names to display labels
        indent: Indentation prefix (default: "  ")
        precision: Decimal precision for values (default: 2)

    Returns:
        List of formatted lines with aligned metrics
    """
    if not metrics:
        return []

    # Calculate max label width for alignment
    max_label_width = max(len(labels.get(key, key)) for key in metrics.keys())

    lines = []
    for key, value in metrics.items():
        label = labels.get(key, key)
        # Align labels and format values
        lines.append(f"{indent}{label + ':':<{max_label_width + 1}} {value:.{precision}f}")

    return lines


def format_metric_line(
    label: str,
    value: float,
    suffix: str = "",
    indent: str = "  ",
    precision: int = 2,
    label_width: int = 18
) -> str:
    """Format a single metric line with aligned label and value.

    Args:
        label: Metric label
        value: Metric value
        suffix: Optional suffix after value (e.g., "/1.00", "(penalty)")
        indent: Indentation prefix (default: "  ")
        precision: Decimal precision for value (default: 2)
        label_width: Width for label alignment (default: 18)

    Returns:
        Formatted metric line
    """
    formatted_label = f"{label}:"
    return f"{indent}{formatted_label:<{label_width}} {value:.{precision}f}{suffix}"
