"""Temporal analysis utilities."""

from typing import List, Dict, Any, Tuple
from datetime import datetime, timezone

from src.core.database import GenericDatabase
from src.domain.models import Question, Event, Article


def ensure_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class TemporalAnalyzer:
    """Analyzer for temporal forecast progression."""

    def __init__(self, db: GenericDatabase):
        self.db = db

    def get_context_timeline(
        self, question: Question
    ) -> List[Tuple[datetime, int, str]]:
        """Get timeline of when context items become available."""
        timeline = []

        # events
        if question.related_event_ids:
            for event_id in question.related_event_ids:
                event = self.db.get(Event, event_id)
                if event and event.occurred_date:
                    timeline.append(
                        (ensure_aware(event.occurred_date), "event", event.id)
                    )

        from src.analysis.graph_analysis import resolve_target_event_id

        resolved_target = resolve_target_event_id(question, self.db)
        if resolved_target:
            event = self.db.get(Event, resolved_target)
            if event and event.occurred_date:
                timeline.append((ensure_aware(event.occurred_date), "event", event.id))

        # articles
        all_articles = self.db.get_many(Article)
        question_articles = [
            a
            for a in all_articles
            if "related_question_ids" in a.metadata
            and question.id in a.metadata["related_question_ids"]
        ]

        for article in question_articles:
            if article.published_date:
                timeline.append(
                    (ensure_aware(article.published_date), "article", article.id)
                )

        timeline.sort(key=lambda x: x[0])

        result = []
        for i, (timestamp, _, item_type) in enumerate(timeline):
            result.append((timestamp, i + 1, item_type))

        return result

    def calculate_forecast_points(
        self, question: Question, num_points: int = 5, min_context_items: int = 2
    ) -> List[Dict[str, Any]]:
        """Calculate optimal forecast points along the timeline."""
        timeline = self.get_context_timeline(question)

        # Filter before resolution
        valid_timeline = [
            (ts, count, item_type)
            for ts, count, item_type in timeline
            if ts < question.resolution_date
        ]

        if len(valid_timeline) < min_context_items:
            raise ValueError(
                f"Insufficient context items ({len(valid_timeline)}) before resolution date."
            )

        # Find valid indices
        valid_indices = [
            i
            for i in range(len(valid_timeline))
            if valid_timeline[i][1] >= min_context_items
        ]

        if not valid_indices:
            raise ValueError(f"No points with >={min_context_items} context items.")

        # Select points
        if num_points <= len(valid_indices):
            step = len(valid_indices) // num_points
            selected_indices = [valid_indices[i * step] for i in range(num_points)]
        else:
            selected_indices = valid_indices

        return [
            {
                "simulated_date": valid_timeline[idx][0],
                "context_count": valid_timeline[idx][1],
                "days_before_resolution": (
                    question.resolution_date - valid_timeline[idx][0]
                ).days,
            }
            for idx in selected_indices
        ]
