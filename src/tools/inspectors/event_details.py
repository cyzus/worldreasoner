"""Tool for retrieving full event details and linked article content."""

from typing import Optional, TYPE_CHECKING
from src.tools.base.database_mixin import DatabaseAwareTool
from src.tools.base.base import ToolResponseMixin
from src.tools.base.output_models import EventDetailsOutput
from src.domain.models import Event, Article
from src.tools.base.schema_helper import pydantic_to_output_schema

if TYPE_CHECKING:
    from src.core.database import GenericDatabase


class EventDetailsTool(DatabaseAwareTool, ToolResponseMixin):
    """Tool that provides full event details including linked article content.

    The agent can use this tool to get more context about events before
    generating questions, allowing for deeper, more insightful questions.

    Always uses database backend for simplicity.
    """

    name = "event_details"
    description = """Get full details about a specific event including linked article content.

    Use this tool when you need more information about an event to generate
    high-quality, insightful forecast questions. This gives you access to:
    - Full event description (not truncated)
    - Complete article content from source articles
    - All event metadata and entities

    Args:
        event_id: The ID of the event to get details for

    Returns:
        Dictionary with full event details and article content
    """

    inputs = {
        "event_id": {
            "type": "string",
            "description": "The ID of the event (e.g., 'evt_tech_20251019_001')",
        }
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(EventDetailsOutput)

    def __init__(
        self, db: Optional["GenericDatabase"] = None, db_path: Optional[str] = None
    ):
        """Initialize tool with database.

        Args:
            db: Optional GenericDatabase instance
            db_path: Optional path to database file (creates new GenericDatabase if provided)

        Note:
            If neither db nor db_path is provided, will use default database path
        """
        super().__init__(db=db, db_path=db_path, ensure_tables=[Event, Article])

    def forward(self, event_id: str) -> EventDetailsOutput:
        """Get full details for an event.

        Args:
            event_id: Event ID to look up

        Returns:
            EventDetailsOutput Pydantic model with event details and article content
        """
        # Fetch event from database
        event = self.db.get(Event, event_id)
        if not event:
            import json
            error_json = self.not_found_response("Event", event_id, Event)
            error_dict = json.loads(error_json)
            return EventDetailsOutput(
                event={"id": "error", "error": error_dict.get("error", "Not found"), "available_items": error_dict.get("available_items", [])},
                linked_articles=[],
                summary=f"Error: {error_dict.get('error', 'Not found')}",
            )

        # Fetch linked articles from database
        linked_articles = []
        if event.article_ids:
            articles = self.db.get_many(Article, ids=event.article_ids)
            for article in articles:
                linked_articles.append(
                    {
                        "id": article.id,
                        "title": article.title,
                        "url": article.url,
                        "source": article.source,
                        "published_date": str(article.published_date),
                        "content": article.content,  # Full content!
                        "word_count": article.word_count,
                    }
                )

        # Build and return Pydantic model directly
        event_dict = self._build_event_dict(event)
        return EventDetailsOutput(
            event=event_dict,
            linked_articles=linked_articles,
            summary=f"Event '{event.title}' with {len(linked_articles)} linked article(s)",
        )

    def _build_event_dict(self, event: Event) -> dict:
        """Build event dictionary for output.

        Args:
            event: Event object

        Returns:
            Event dictionary
        """
        return {
            "id": event.id,
            "title": event.title,
            "description": event.description,  # Full description
            "occurred_date": str(event.occurred_date) if event.occurred_date else None,
            "predicted_date": str(event.predicted_date)
            if event.predicted_date
            else None,
            "event_type": event.event_type.value
            if hasattr(event.event_type, "value")
            else event.event_type,
            "domain": event.domain.value
            if hasattr(event.domain, "value")
            else event.domain,
            "status": event.status.value
            if hasattr(event.status, "value")
            else event.status,
            "metadata": event.metadata,
            "tags": event.tags if hasattr(event, "tags") else [],
        }
