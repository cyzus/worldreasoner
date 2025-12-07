"""Batch event identification tool for processing multiple events at once."""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.domain.models import Event, Domain
from src.utils.enums import parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.tools.event_identifier import EventIdentifierTool


class BatchEventIdentifierTool(EventIdentifierTool):
    """Stores multiple identified events from article analysis in a single call.

    This tool helps the agent:
    1. Submit ALL identified events in one structured call
    2. Generate unique event IDs for each
    3. Link events to source articles
    4. Set proper event types and status

    Use this instead of calling event_identifier multiple times to avoid
    JSON concatenation issues with Gemini models.
    """

    name = "batch_event_identifier"
    description = """Stores multiple identified events into structured Event format.

    Use this tool AFTER you've analyzed all articles and identified events.
    Call this tool ONCE with a JSON array containing ALL events you identified.

    Args:
        events_json (str): JSON array of event objects. Each event should have:
            - title (str): Short descriptive title
            - description (str): Detailed description
            - domain (str): Event domain (finance|politics|tech|health|climate|general)
            - occurred_date (str, optional): When event occurred (ISO 8601 WITH timezone)
            - event_type (str, optional): Type (decision|outcome|indicator|milestone|external_shock)
            - source_article_ids (str, optional): Comma-separated article IDs

    Example:
        [
          {
            "title": "Fed raises rates",
            "description": "Federal Reserve raises interest rates by 0.25%",
            "domain": "finance",
            "occurred_date": "2025-11-26T14:30:00+00:00",
            "event_type": "decision",
            "source_article_ids": "art_123,art_456"
          },
          {
            "title": "New iPhone announced",
            "description": "Apple announces iPhone 17 launch",
            "domain": "tech",
            "occurred_date": "2025-11-27T09:15:00Z",
            "event_type": "indicator",
            "source_article_ids": "art_789"
          }
        ]

    Returns:
        str: JSON summary with count of events stored
    """

    inputs = {
        "events_json": {
            "type": "string",
            "description": "JSON array of event objects with title, description, domain, occurred_date, event_type, source_article_ids"
        }
    }
    output_type = "string"

    def __init__(
        self,
        collector=None,
        db_path: str = None,
        similarity_threshold: float = 0.85,
        deduplicate: bool = True,
        time_window_days: int = 60,
        question_id: Optional[str] = None,
    ):
        """Initialize the batch event identifier.

        Args:
            collector: Optional ResultCollector[Event] for storing results.
            db_path: Optional path to database for persistence and deduplication
            similarity_threshold: Minimum similarity score for deduplication (0.0-1.0)
            deduplicate: Whether to check for existing similar events
            time_window_days: Time window for temporal proximity matching
            question_id: Question ID for provenance tracking
        """
        super().__init__(
            collector=collector,
            db_path=db_path,
            similarity_threshold=similarity_threshold,
            deduplicate=deduplicate,
            time_window_days=time_window_days,
            question_id=question_id
        )
        self.event_counter = 0

    def forward(self, events_json: str) -> str:
        """Store multiple events from JSON array.

        Args:
            events_json: JSON string containing array of event objects

        Returns:
            JSON string with summary of stored events
        """
        try:
            # Parse the JSON array
            events_data = json.loads(events_json)

            if not isinstance(events_data, list):
                return json.dumps({
                    "error": "events_json must be a JSON array",
                    "received_type": type(events_data).__name__,
                    "status": "failed"
                })

            stored_events = []
            errors = []

            for idx, event_data in enumerate(events_data):
                try:
                    # Use parent class forward method to process single event
                    result_json = super().forward(
                        title=event_data.get("title", ""),
                        description=event_data.get("description", ""),
                        domain=event_data.get("domain", "general"),
                        occurred_date=event_data.get("occurred_date"),
                        event_type=event_data.get("event_type"),
                        source_article_ids=event_data.get("source_article_ids", "")
                    )
                    
                    result = json.loads(result_json)
                    
                    if "error" in result_json or "Error:" in result_json:
                        errors.append({
                            "index": idx,
                            "error": result_json,
                            "event_data": event_data
                        })
                    else:
                        stored_events.append({
                            "id": result.get("id"),
                            "title": result.get("title"),
                            "domain": result.get("domain"),
                            "event_type": result.get("event_type"),
                            "status": "existing" if not result.get("is_new") else "new"
                        })
                        
                        # Update bidirectional article→event links if we have database
                        if self.db is not None:
                            # Get the stored event to update links
                            from src.domain.models import Event
                            event = self.db.get(Event, result.get("id"))
                            if event:
                                self._update_article_event_links(event)

                except Exception as e:
                    errors.append({
                        "index": idx,
                        "error": str(e),
                        "event_data": event_data
                    })
                    logger.warning(f"Failed to create event {idx}: {e}")

            summary = {
                "status": "completed",
                "total_submitted": len(events_data),
                "successfully_stored": len(stored_events),
                "errors": len(errors),
                "events": stored_events[:5]  # Show first 5 for brevity
            }

            if errors:
                summary["error_details"] = errors[:3]  # Show first 3 errors

            logger.info(f"Batch event identifier: {len(stored_events)}/{len(events_data)} events stored successfully")

            return json.dumps(summary, indent=2)

        except json.JSONDecodeError as e:
            return json.dumps({
                "error": f"Invalid JSON format: {str(e)}",
                "status": "failed"
            })
        except Exception as e:
            logger.error(f"Batch event identifier error: {e}")
            return json.dumps({
                "error": str(e),
                "status": "failed"
            })
    
    def _update_article_event_links(self, event: Event) -> None:
        """Update articles to include bidirectional link to this event.

        For each article referenced by the event, add this event's ID
        to the article's event_ids list.

        Args:
            event: Event to link to articles
        """
        if not self.db or not event.article_ids:
            return

        from src.domain.models import Article

        for article_id in event.article_ids:
            try:
                # Fetch article from database using GenericDatabase
                article = self.db.get(Article, article_id)
                if not article:
                    logger.debug(f"Article {article_id} not found for event {event.id}")
                    continue

                # Check if event ID is already linked
                if event.id in article.event_ids:
                    continue

                # Add event ID to article's event_ids
                article.event_ids.append(event.id)

                # Save updated article using GenericDatabase
                self.db.save(Article, article)
                logger.debug(f"Linked article {article_id} to event {event.id}")

            except Exception as e:
                logger.warning(f"Failed to update article {article_id} for event {event.id}: {e}")
