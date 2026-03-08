"""Shared formatting utilities for inspector tools.

Provides reusable formatting functions for consistent visualization across
graph_inspector, article_inspector, and other inspector tools.
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from src.utils.date_utils import ensure_timezone_aware


class InspectorReportBuilder:
    """Builder for creating standardized, clean, and token-efficient inspector reports."""

    def __init__(self, title: str, width: int = 64):
        self.width = width
        self.lines: List[str] = []
        self.add_header(title)

    def add_header(self, title: str) -> "InspectorReportBuilder":
        """Add a minimal header."""
        self.lines.extend([f"## {title}", ""])
        return self

    def add_section_header(self, title: str) -> "InspectorReportBuilder":
        """Add a minimal section header."""
        self.lines.extend([f"### {title}", ""])
        return self

    def add_kv(self, key: str, value: Any, indent: int = 0) -> "InspectorReportBuilder":
        """Add a key-value pair line."""
        prefix = " " * indent
        self.lines.append(f"{prefix}- {key}: {value}")
        return self

    def add_line(self, text: str = "", indent: int = 0) -> "InspectorReportBuilder":
        """Add a single line of text."""
        prefix = " " * indent
        self.lines.append(f"{prefix}{text}")
        return self

    def add_time_window(
        self,
        resolution_date: datetime,
        estimated_start_time: Optional[datetime],
        indent: int = 0,
    ) -> "InspectorReportBuilder":
        """Add standardized time window display."""
        q_resolution = ensure_timezone_aware(resolution_date)
        prefix = " " * indent

        if estimated_start_time:
            q_start = ensure_timezone_aware(estimated_start_time)
            self.lines.append(
                f"{prefix}- Time Window: {q_start.strftime('%Y-%m-%d')} -> {q_resolution.strftime('%Y-%m-%d')}"
            )
            window_days = (q_resolution - q_start).days
            self.lines.append(f"{prefix}- Window Span: {window_days} days")
        else:
            self.lines.append(
                f"{prefix}- Resolution Date: {q_resolution.strftime('%Y-%m-%d')}"
            )

        return self

    def add_coverage_range(
        self,
        earliest: datetime,
        latest: datetime,
        resolution_date: datetime,
        estimated_start_time: Optional[datetime],
        item_type: str = "Item",
        indent: int = 0,
    ) -> "InspectorReportBuilder":
        """Add item coverage range info."""
        earliest = ensure_timezone_aware(earliest)
        latest = ensure_timezone_aware(latest)
        span_days = (latest - earliest).days
        prefix = " " * indent

        self.lines.append(
            f"{prefix}- {item_type} Range: {earliest.strftime('%Y-%m-%d')} -> {latest.strftime('%Y-%m-%d')} ({span_days} days)"
        )

        q_start = (
            ensure_timezone_aware(estimated_start_time)
            if estimated_start_time
            else None
        )
        if q_start and earliest > q_start:
            gap_days = (earliest - q_start).days
            self.lines.append(
                f"{prefix}  - WARNING: Missing early coverage ({gap_days} days)"
            )

        return self

    def add_monthly_bar_chart(
        self,
        monthly_data: Dict[str, int],
        item_type: str = "Items",
        bar_width: int = 20,
        indent: int = 0,
    ) -> "InspectorReportBuilder":
        """Add compact monthly distribution."""
        prefix = " " * indent
        if not monthly_data:
            self.lines.append(f"{prefix}- No monthly data")
            return self

        self.lines.append(f"{prefix}- {item_type} by Month:")
        max_count = max(monthly_data.values()) if monthly_data else 0

        for month in sorted(monthly_data.keys()):
            count = monthly_data[month]
            # Use smaller bar or just text for efficiency?
            # Interactive text charts are good, but maybe keep it smaller.
            bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
            bar = "|" * bar_len
            self.lines.append(f"{prefix}  - {month}: {bar} ({count})")

        return self

    def add_timeline_gaps(
        self,
        gaps: List[Dict],
        min_gap_label: str,
        max_display: int = 5,
        compact: bool = True,
        indent: int = 0,
    ) -> "InspectorReportBuilder":
        """Add timeline gaps section."""
        if not gaps:
            return self

        self.add_line(f"- Timeline Gaps ({min_gap_label}):", indent=indent)

        prefix = " " * indent
        for gap in gaps[:max_display]:
            start_str = gap["start"].strftime("%Y-%m-%d")
            end_str = gap["end"].strftime("%Y-%m-%d")
            days = gap["days"]
            self.lines.append(
                f"{prefix}  - GAP: {start_str} -> {end_str} ({days} days)"
            )

        return self

    def add_metrics(
        self,
        metrics: Dict[str, float],
        labels: Optional[Dict[str, str]] = None,
        indent: int = 0,
    ) -> "InspectorReportBuilder":
        """Add aligned metric lines (compact)."""
        if not metrics:
            return self

        labels = labels or {}
        prefix = " " * indent
        # Just key: value, no fancy alignment padding to save whitespace/tokens
        for k, v in metrics.items():
            label = labels.get(k, k)
            if isinstance(v, (float, int)) and not isinstance(v, bool):
                self.lines.append(f"{prefix}- {label}: {v:.2f}")
            else:
                self.lines.append(f"{prefix}- {label}: {v}")

        return self

    def build(self) -> str:
        """Return the complete report string."""
        return "\n".join(self.lines)


def format_inspector_header(title: str, width: int = 64) -> str:
    return f"## {title}"


def format_section_header(title: str, width: int = 64) -> List[str]:
    return ["", title, "━" * width, ""]


def format_time_window(
    resolution_date: datetime,
    estimated_start_time: Optional[datetime] = None,
    indent: str = "  ",
) -> List[str]:
    q_resolution = ensure_timezone_aware(resolution_date)
    lines = []
    if estimated_start_time:
        q_start = ensure_timezone_aware(estimated_start_time)
        lines.append(
            f"{indent}- Time Window: {q_start.strftime('%Y-%m-%d')} -> {q_resolution.strftime('%Y-%m-%d')}"
        )
        window_days = (q_resolution - q_start).days
        lines.append(f"{indent}- Window Span: {window_days} days")
    else:
        lines.append(f"{indent}- Resolution Date: {q_resolution.strftime('%Y-%m-%d')}")
    return lines


def format_coverage_range(
    earliest: datetime,
    latest: datetime,
    resolution_date: datetime,
    estimated_start_time: Optional[datetime],
    span_days: int,
    item_type: str = "Item",
    indent: str = "  ",
) -> List[str]:
    earliest = ensure_timezone_aware(earliest)
    latest = ensure_timezone_aware(latest)
    span = (latest - earliest).days
    lines = [
        f"{indent}- {item_type} Range: {earliest.strftime('%Y-%m-%d')} -> {latest.strftime('%Y-%m-%d')} ({span} days)"
    ]
    if estimated_start_time:
        q_start = ensure_timezone_aware(estimated_start_time)
        if earliest > q_start:
            gap_days = (earliest - q_start).days
            lines.append(
                f"{indent}  - WARNING: Missing early coverage ({gap_days} days)"
            )
    return lines


def render_monthly_bar_chart(
    monthly_data: Dict[str, int],
    item_type: str = "items",
    indent: str = "  ",
    bar_width: int = 30,
) -> List[str]:
    if not monthly_data:
        return [f"{indent}- No monthly data"]
    max_count = max(monthly_data.values())
    lines = [f"{indent}- {item_type} by Month:"]
    for month in sorted(monthly_data.keys()):
        count = monthly_data[month]
        bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
        bar = "|" * bar_len
        lines.append(f"{indent}  - {month}: {bar} ({count})")
    return lines


def format_timeline_gaps(
    gaps: List[Dict],
    min_gap_label: str,
    max_display: int = 5,
    indent: str = "  ",
    compact: bool = False,
) -> List[str]:
    if not gaps:
        return []
    lines = [f"{indent}- Timeline Gaps ({min_gap_label}):"]
    for gap in gaps[:max_display]:
        start_str = gap["start"].strftime("%Y-%m-%d")
        end_str = gap["end"].strftime("%Y-%m-%d")
        days = gap["days"]
        lines.append(f"{indent}  - GAP: {start_str} -> {end_str} ({days} days)")
    return lines


def format_metric_line(
    label: str,
    value: float,
    suffix: str = "",
    indent: str = "  ",
    precision: int = 2,
    label_width: int = 18,
) -> str:
    formatted_label = f"{label}:"
    return f"{indent}{formatted_label:<{label_width}} {value:.{precision}f}{suffix}"
