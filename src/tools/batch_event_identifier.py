"""Batch event identification tool for processing multiple events at once."""

import json
from datetime import datetime, timezone
import uuid
from typing import List, Dict, Any, Optional

from smolagents import Tool
from src.domain.models import Event, EventType, EventStatus, Domain
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.tools.base import CollectorAwareTool
from src.utils.similarity import SimilarityMatcher


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

    def __init__(
        self,
        collector=None,
        db_path: str = None,
        similarity_threshold: float = 0.85,
        deduplicate: bool = True,
        time_window_days: int = 60
    ):
        """Initialize the batch event identifier.

        Args:
            collector: Optional ResultCollector[Event] for storing results.
            db_path: Optional path to database for persistence and deduplication
            similarity_threshold: Minimum similarity score for deduplication (0.0-1.0)
            deduplicate: Whether to check for existing similar events
            time_window_days: Time window for temporal proximity matching
        """
        super().__init__(collector)
        self.event_counter = 0
        self.similarity_threshold = similarity_threshold
        self.deduplicate = deduplicate
        self.time_window_days = time_window_days
        self._matcher: Optional[SimilarityMatcher] = None

        # Database for persistence
        self.db = None
        if db_path:
            from src.core.database import Database, GenericDatabase
            self.db = Database(db_path)

            # Initialize similarity matcher for event deduplication
            if deduplicate:
                generic_db = GenericDatabase(db_path)
                self._matcher = SimilarityMatcher(
                    db=generic_db,
                    model_class=Event,
                    text_fields=[("title", 0.6), ("description", 0.4)],
                    similarity_threshold=similarity_threshold,
                )

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
                    # Try to find existing similar event (deduplication)
                    title = event_data.get("title", "")
                    description = event_data.get("description", "")
                    domain_str = event_data.get("domain", "general")
                    occurred_date_str = event_data.get("occurred_date")

                    # Parse domain for filtering
                    domain_enum = parse_domain(domain_str)

                    # Parse event date for temporal filtering
                    if occurred_date_str:
                        event_date = parse_iso_datetime(occurred_date_str)
                    else:
                        event_date = datetime.now(timezone.utc)
                    event_date = ensure_timezone_aware(event_date)

                    # Check for existing event
                    existing_event = self._find_existing_event(
                        title=title,
                        description=description,
                        domain=domain_enum,
                        event_date=event_date
                    )

                    if existing_event:
                        # Update existing event with new article links if provided
                        article_ids_str = event_data.get("source_article_ids", "")
                        article_ids = [aid.strip() for aid in article_ids_str.split(',')] if article_ids_str else []
                        self._update_existing_event(existing_event, article_ids)

                        # Update bidirectional article→event links
                        if self.db is not None:
                            self._update_article_event_links(existing_event)

                        # Add to collector even if duplicate
                        self.store_result(existing_event, context=f"Event {existing_event.id} (existing)")

                        stored_events.append({
                            "id": existing_event.id,
                            "title": existing_event.title,
                            "domain": existing_event.domain.value,
                            "event_type": existing_event.event_type.value,
                            "status": "existing"
                        })
                        logger.debug(f"Found existing event '{existing_event.title}' (ID: {existing_event.id}) - reusing instead of creating duplicate")
                        continue

                    # Create new event
                    event = self._create_event(event_data, idx)

                    # Store event using unified collector interface
                    self.store_result(event, context=f"Event {event.id}")

                    # Persist to database if available
                    if self.db is not None:
                        self.db.save_event(event)
                        logger.debug(f"Event {event.id} persisted to database")

                        # Update bidirectional article→event links
                        self._update_article_event_links(event)

                    stored_events.append({
                        "id": event.id,
                        "title": event.title,
                        "domain": event.domain.value,
                        "event_type": event.event_type.value,
                        "status": "new"
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

    def _find_existing_event(
        self,
        title: str,
        description: str,
        domain: Domain,
        event_date: datetime,
    ) -> Optional[Event]:
        """Find existing event matching the description.

        Args:
            title: Event title to match
            description: Event description to match
            domain: Event domain
            event_date: Event date for temporal filtering

        Returns:
            Matching event or None
        """
        if not self.deduplicate or not self._matcher:
            return None

        # Define temporal filter - events within time window
        def temporal_filter(event: Event) -> bool:
            if not event.occurred_date and not event.predicted_date:
                return True  # Include events without dates

            check_date = event.occurred_date or event.predicted_date
            time_diff = abs((check_date - event_date).days)
            return time_diff <= self.time_window_days

        # Use the generic matcher
        match = self._matcher.find_match(
            filters={"domain": domain.value},
            additional_filter=temporal_filter,
            title=title,
            description=description,
        )

        return match

    def _update_existing_event(self, event: Event, new_article_ids: List[str]) -> bool:
        """Update existing event with new article links.

        Args:
            event: Existing event to update
            new_article_ids: New article IDs to add

        Returns:
            True if event was updated, False otherwise
        """
        if not new_article_ids:
            return False

        existing_ids = set(event.article_ids or [])
        new_ids = set(new_article_ids) - existing_ids

        if not new_ids:
            return False

        # Add new article IDs
        event.article_ids = list(existing_ids | new_ids)

        # Persist update if database is available
        if self.db is not None:
            self.db.save_event(event)
            logger.debug(f"Updated event {event.id} with {len(new_ids)} new article links")

        return True

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
                # Fetch article from database
                article = self.db.db.get(Article, article_id)
                if not article:
                    logger.debug(f"Article {article_id} not found for event {event.id}")
                    continue

                # Check if event ID is already linked
                if event.id in article.event_ids:
                    continue

                # Add event ID to article's event_ids
                article.event_ids.append(event.id)

                # Save updated article
                self.db.save_article(article)
                logger.debug(f"Linked article {article_id} to event {event.id}")

            except Exception as e:
                logger.warning(f"Failed to update article {article_id} for event {event.id}: {e}")
