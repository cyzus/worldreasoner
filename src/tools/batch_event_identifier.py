"""Batch event identification tool for processing multiple events at once."""

import json
from datetime import datetime, timezone
import uuid
from typing import List, Dict, Any

from smolagents import Tool
from src.domain.models import Event, EventType, EventStatus, Domain
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.tools.base import CollectorAwareTool


class BatchEventIdentifierTool(CollectorAwareTool[Event]):
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

    def __init__(self, collector=None):
        """Initialize the batch event identifier.

        Args:
            collector: Optional ResultCollector[Event] for storing results.
        """
        super().__init__(collector)
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
                    event = self._create_event(event_data, idx)

                    # Store event using unified collector interface
                    self.store_result(event, context=f"Event {event.id}")

                    stored_events.append({
                        "id": event.id,
                        "title": event.title,
                        "domain": event.domain.value,
                        "event_type": event.event_type.value
                    })

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

    def _create_event(self, event_data: Dict[str, Any], index: int) -> Event:
        """Create an Event object from event data dict.

        Args:
            event_data: Dictionary with event fields
            index: Index in batch (for ID generation)

        Returns:
            Event object
        """
        # Required fields
        title = event_data.get("title")
        description = event_data.get("description")
        domain_str = event_data.get("domain")

        if not title:
            raise ValueError("Missing required field: title")
        if not description:
            raise ValueError("Missing required field: description")
        if not domain_str:
            raise ValueError("Missing required field: domain")

        # Parse occurred date or use current time
        occurred_date_str = event_data.get("occurred_date")
        if occurred_date_str:
            event_date = parse_iso_datetime(occurred_date_str)
        else:
            event_date = datetime.now(timezone.utc)
        event_date = ensure_timezone_aware(event_date)

        # Parse article IDs
        article_ids = []
        source_article_ids = event_data.get("source_article_ids", "")
        if source_article_ids:
            article_ids = [aid.strip() for aid in source_article_ids.split(',')]

        # Validate and convert domain
        domain_enum = parse_domain(domain_str)

        # Validate and convert event_type
        event_type_enum = parse_event_type(event_data.get("event_type"))

        # Generate unique event ID
        event_id = generate_event_id(domain_enum, event_date, self.event_counter + index)

        # Determine status based on date
        status = EventStatus.OCCURRED if event_date <= datetime.now(timezone.utc) else EventStatus.PREDICTED

        # Create Event object
        event = Event(
            id=event_id,
            title=title,
            description=description,
            event_type=event_type_enum,
            domain=domain_enum,
            occurred_date=event_date if status == EventStatus.OCCURRED else None,
            predicted_date=event_date if status == EventStatus.PREDICTED else None,
            status=status,
            article_ids=article_ids,
            is_synthetic=False
        )

        return event
