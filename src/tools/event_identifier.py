"""Event identification tool using LLM to extract events from articles."""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from smolagents import Tool
from src.domain.models import Article, Event, EventType, EventStatus, Domain
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.utils.similarity import SimilarityMatcher
from src.tools.base import CollectorAwareTool


# Default similarity threshold for event deduplication
DEFAULT_SIMILARITY_THRESHOLD = 0.65


class EventIdentifierTool(CollectorAwareTool[Event]):
    """Stores and structures identified events from article analysis.
    
    This tool helps the agent:
    1. Check for existing similar events (deduplication)
    2. Convert analyzed event data into structured Event format
    3. Generate unique event IDs (only for new events)
    4. Link events to source articles
    5. Set proper event types and status
    
    DEDUPLICATION: Before creating a new event, this tool searches for existing
    events with similar titles/descriptions in the same domain. If a match is
    found (similarity >= threshold), the existing event is returned instead.
    
    NOTE: This tool does NOT analyze articles itself.
    The agent should first analyze the articles using its LLM reasoning,
    then use this tool to store each identified event in the proper structure.
    """
    
    name = "event_identifier"
    description = f"""Stores identified event data into structured Event format.

    Use this tool AFTER you've analyzed articles and identified specific events.
    Call this tool once for EACH event you identify (not all at once).
    
    NOTE: This tool automatically deduplicates events. If a similar event
    already exists in the database, it will return that event instead of
    creating a duplicate.

    Args:
        title (str): Short descriptive title of the event
        description (str): Detailed description of what happened/will happen
        domain (str): Event domain - one of: {', '.join(enum_to_list(Domain))}
        occurred_date (str, optional): When the event occurred (ISO format with time zone)
        event_type (str, optional): Type of event - one of: {', '.join(enum_to_list(EventType))}
        source_article_ids (str, optional): Comma-separated article IDs mentioning this event

    Returns:
        str: JSON string with the created/matched Event object including ID
    """
    
    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "title": {
            "type": "string", 
            "description": "Short event title"
            },
        "description": {
            "type": "string", 
            "description": "Detailed event description"
            },
        "domain": {
            "type": "string",
            "description": f"Event domain - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain)
        },
        "occurred_date": {
            "type": "string", 
            "description": "When event occurred (ISO 8601 WITH timezone, e.g. 2025-11-27T14:30:00Z or 2025-11-27T14:30:00+00:00; MUST include 'Z' or an explicit offset)", 
            "nullable": True},
        "event_type": {
            "type": "string",
            "description": f"Event type - one of: {', '.join(enum_to_list(EventType))}",
            "enum": enum_to_list(EventType),
            "nullable": True
        },
        "source_article_ids": 
            {
                "type": "string", 
                "description": "Comma-separated article IDs", 
            },
    }
    output_type = "string"  # JSON string
    
    def __init__(
        self,
        collector=None,
        db_path: str = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        deduplicate: bool = True,
        time_window_days: int = 60,
        question_id: Optional[str] = None,
    ):
        """Initialize the event identifier.

        Args:
            collector: Optional ResultCollector[Event] for storing results.
            db_path: Optional database path for persisting events.
            similarity_threshold: Minimum similarity score for deduplication (0.0-1.0).
            deduplicate: Whether to check for existing similar events.
            time_window_days: Time window for temporal proximity matching.
            question_id: Question ID for provenance tracking (sets extracted_for_question_id)
        """
        super().__init__(collector)
        self.db = None
        self.similarity_threshold = similarity_threshold
        self.deduplicate = deduplicate
        self.time_window_days = time_window_days
        self.question_id = question_id  # Provenance context
        self._matcher: Optional[SimilarityMatcher] = None

        if db_path:
            from src.core.database import GenericDatabase
            self.db = GenericDatabase(db_path)
            # Initialize similarity matcher for event deduplication
            self._matcher = SimilarityMatcher(
                db=self.db,
                model_class=Event,
                text_fields=[("title", 0.6), ("description", 0.4)],
                similarity_threshold=similarity_threshold,
            )
    
    def forward(
        self,
        title: str,
        description: str,
        domain: str,
        source_article_ids: str,
        occurred_date: str = None,
        event_type: str = None,
    ) -> str:
        """Store event data and return as structured JSON.

        Args:
            title: Event title
            description: Event description
            domain: Event domain (string, will be converted to enum)
            occurred_date: Optional occurrence date (ISO format)
            event_type: Type of event (string, will be converted to enum)
            source_article_ids: Comma-separated article IDs

        Returns:
            JSON string of Event object (new or existing match)
        """
        # Parse occurred date or use current time
        event_date = parse_iso_datetime(occurred_date)
        event_date = ensure_timezone_aware(event_date)
        
        # Parse article IDs
        article_ids = []
        if source_article_ids:
            article_ids = [aid.strip() for aid in source_article_ids.split(',')]
            if self.db is not None:
                # Verify article IDs exist in database
                missing_ids = []
                invalid_date_articles = []
                for aid in article_ids:
                    article = self.db.get(Article, aid)
                    if article is None:
                        missing_ids.append(aid)
                    else:
                        # Check that article date is not prior to event date
                        article_date = article.published_date
                        if article_date and event_date:
                            article_date = ensure_timezone_aware(article_date)
                            if article_date < event_date:
                                invalid_date_articles.append(
                                    f"{aid} (article: {article_date.isoformat()}, event: {event_date.isoformat()})"
                                )

                if missing_ids:
                    return json.dumps({
                        "error": "missing_article_ids",
                        "message": "The following article IDs do not exist in database",
                        "missing_ids": missing_ids
                    }, indent=2)

                if invalid_date_articles:
                    return json.dumps({
                        "error": "invalid_article_dates",
                        "message": "The following articles have dates prior to the event occurring date, meaning they cannot be the source of this event",
                        "invalid_articles": invalid_date_articles
                    }, indent=2)

        else:
            return json.dumps({
                "error": "empty_source_article_ids",
                "message": "source_article_ids cannot be empty"
            }, indent=2)
        # Validate and convert domain
        domain_enum = parse_domain(domain)

        # Validate and convert event_type
        event_type_enum = parse_event_type(event_type)

        # Validate event date against question time window
        # Store validation result to include in return message
        time_window_validation = None
        if self.question_id and self.db and event_date:
            from src.domain.models import Question
            from src.utils.date_utils import validate_date_against_question_window

            question = self.db.get(Question, self.question_id)
            if question:
                time_window_validation = validate_date_against_question_window(
                    date=event_date,
                    question_start_time=question.estimated_start_time,
                    question_resolution_date=question.resolution_date,
                    entity_type="Event"
                )

        # Try to find existing similar event (deduplication)
        existing_event = self._find_existing_event(
            title=title,
            description=description,
            domain=domain_enum,
            event_date=event_date,
        )

        if existing_event:
            # Update existing event with new article links if provided
            updated = self._update_existing_event(existing_event, article_ids)

            return self._format_response(
                event=existing_event,
                is_new=False,
                updated_articles=updated,
                time_window_validation=time_window_validation,
            )

        # Create new event
        event = self._create_new_event(
            title=title,
            description=description,
            domain_enum=domain_enum,
            event_type_enum=event_type_enum,
            event_date=event_date,
            article_ids=article_ids,
        )

        return self._format_response(event=event, is_new=True, time_window_validation=time_window_validation)

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

        if match:
            logger.info(f"Found existing event '{match.title}' (ID: {match.id}) - reusing instead of creating duplicate")

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
            self.db.save(Event, event)
            logger.debug(f"Updated event {event.id} with {len(new_ids)} new article links")

        return True

    def _create_new_event(
        self,
        title: str,
        description: str,
        domain_enum: Domain,
        event_type_enum: EventType,
        event_date: datetime,
        article_ids: List[str],
    ) -> Event:
        """Create a new event.

        Args:
            title: Event title
            description: Event description
            domain_enum: Event domain
            event_type_enum: Event type
            event_date: Event date
            article_ids: Source article IDs

        Returns:
            New Event instance
        """
        # Generate unique event ID
        event_id = generate_event_id(domain_enum, event_date, self.get_stored_count())

        # Determine status based on date
        status = EventStatus.OCCURRED if event_date <= datetime.now(timezone.utc) else EventStatus.PREDICTED

        # Build metadata with provenance info
        metadata = {}
        if self.question_id:
            metadata['related_question_ids'] = [self.question_id]
            metadata['extracted_for_evidence'] = True

        # Determine source article (first article in list)
        source_article_id = article_ids[0] if article_ids else None

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
            extracted_for_question_id=self.question_id,  # Provenance tracking
            source_article_id=source_article_id,  # Link to source article
            is_synthetic=False,
            metadata=metadata,
        )

        # Store event using unified collector interface
        self.store_result(event, context=f"Event {event.id}")

        # Persist to database if available
        if self.db is not None:
            self.db.save(Event, event)
            logger.debug(f"Event {event.id} persisted to database")

        return event

    def _format_response(
        self,
        event: Event,
        is_new: bool,
        updated_articles: bool = False,
        time_window_validation: dict = None,
    ) -> str:
        """Format event response as JSON.

        Args:
            event: Event to format
            is_new: Whether this is a newly created event
            updated_articles: Whether existing event was updated with new articles
            time_window_validation: Optional validation warnings about event date

        Returns:
            JSON string summary
        """
        status_msg = "created" if is_new else ("updated" if updated_articles else "reused_existing")

        summary = {
            "id": event.id,
            "title": event.title,
            "domain": event.domain.value if hasattr(event.domain, 'value') else str(event.domain),
            "event_type": event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
            "occurred_date": event.occurred_date.isoformat() if event.occurred_date else None,
            "description_preview": event.description[:150] + "..." if len(event.description) > 150 else event.description,
            "status": status_msg,
            "is_new": is_new,
        }

        if not is_new:
            summary["note"] = "Matched existing event - no duplicate created"

        # Add time window validation warnings if present
        if time_window_validation:
            summary["status"] = f"{status_msg}_with_warnings"
            summary["warnings"] = time_window_validation["warnings"]
            summary["recommendation"] = time_window_validation["recommendation"]
            summary["suggestion"] = "Consider identifying events that occurred within the valid time window for better causal analysis."

        return json.dumps(summary, indent=2, default=str)

