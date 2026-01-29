"""Reusable table displays for CLI."""

from typing import List, Dict, Optional, Any, Callable, Tuple
from rich.table import Table
from rich.console import Console
from src.domain.models import Question, Event, Article


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit, adding ellipsis if needed."""
    if not text:
        return ""
    return text[: limit - 3] + "..." if len(text) > limit else text


def _get_val(val: Any) -> str:
    """Get string value from enum or string."""
    return val.value if hasattr(val, "value") else str(val)


def _display_table(
    items: List[Any],
    title: str,
    columns: List[Tuple[str, Dict[str, Any]]],
    row_func: Callable[[Any, int], List[str]],
    console: Optional[Console] = None,
):
    """Generic table display function."""
    table = Table(title=title, show_header=True)
    for header, args in columns:
        table.add_column(header, **args)

    for i, item in enumerate(items, 1):
        table.add_row(*row_func(item, i))

    (console or Console()).print(table)


def display_question_table(
    questions: List[Question],
    evidence_map: Optional[Dict[str, bool]] = None,
    console: Optional[Console] = None,
):
    """Display questions in a rich table."""
    cols = [
        ("#", {"style": "cyan", "width": 4}),
        ("ID", {"style": "magenta", "width": 15}),
        ("Question Text", {"width": 50}),
        ("Domain", {"style": "green"}),
        ("Type", {"style": "blue"}),
        ("Quality", {"justify": "right"}),
        ("Resolved", {"justify": "center"}),
        ("Evidence", {"justify": "center"}),
    ]

    def get_row(q: Question, i: int) -> List[str]:
        has_ev = "?"
        if evidence_map is not None:
            has_ev = "✓" if evidence_map.get(q.id, False) else "✗"

        return [
            str(i),
            q.id,
            _truncate(q.question_text, 50),
            _get_val(q.domain),
            _get_val(q.question_type),
            f"{q.quality_score:.2f}" if q.quality_score is not None else "N/A",
            "✓" if q.ground_truth else "✗",
            has_ev,
        ]

    _display_table(
        questions, f"Questions ({len(questions)} total)", cols, get_row, console
    )


def display_event_table(events: List[Event], console: Optional[Console] = None):
    """Display events in a rich table."""
    cols = [
        ("ID", {"style": "cyan", "no_wrap": True, "max_width": 16}),
        ("Title", {"style": "white", "overflow": "ellipsis", "max_width": 60}),
        ("Domain", {"style": "yellow"}),
    ]

    def get_row(e: Event, _: int) -> List[str]:
        return [_truncate(e.id, 17), _truncate(e.title, 60), _get_val(e.domain)]

    _display_table(events, f"Events (showing {len(events)})", cols, get_row, console)


def display_article_table(articles: List[Article], console: Optional[Console] = None):
    """Display articles in a rich table."""
    cols = [
        ("ID", {"style": "cyan", "no_wrap": True, "max_width": 16}),
        ("Title", {"style": "white", "overflow": "ellipsis", "max_width": 60}),
        ("Source", {"style": "green"}),
    ]

    def get_row(a: Article, _: int) -> List[str]:
        return [_truncate(a.id, 17), _truncate(a.title, 60), a.source or "N/A"]

    _display_table(
        articles, f"Articles (showing {len(articles)})", cols, get_row, console
    )
