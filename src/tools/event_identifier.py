"""Event identification tool using LLM to extract events from articles."""

import json
from datetime import datetime, timezone
import uuid
from typing import List

from smolagents import Tool
from src.domain.models import Article, Event, EventType, EventStatus, Domain
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.tools.base import CollectorAwareTool


class EventIdentifierTool(CollectorAwareTool[Event]):
    """Stores and structures identified events from article analysis.
    
    This tool helps the agent:
    1. Convert analyzed event data into structured Event format
    2. Generate unique event IDs
    3. Link events to source articles
    4. Set proper event types and status
    
    NOTE: This tool does NOT analyze articles itself.
    The agent should first analyze the articles using its LLM reasoning,
    then use this tool to store each identified event in the proper structure.
    """
    
    name = "event_identifier"
    description = """Stores identified event data into structured Event format.

    Use this tool AFTER you've analyzed articles and identified specific events.
    Call this tool once for EACH event you identify (not all at once).

    Args:
        title (str): Short descriptive title of the event
        description (str): Detailed description of what happened/will happen
        domain (str): Event domain (finance|politics|tech|health|climate|general)
        occurred_date (str, optional): When the event occurred (ISO format)
        event_type (str, optional): Type of event (decision|outcome|indicator|milestone|external_shock)
        source_article_ids (str, optional): Comma-separated article IDs mentioning this event

    Returns:
        str: JSON string with the created Event object including generated ID
    """
    
    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "title": {"type": "string", "description": "Short event title"},
        "description": {"type": "string", "description": "Detailed event description"},
        "domain": {
            "type": "string",
            "description": f"Event domain - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain)
        },
        "occurred_date": {"type": "string", "description": "When event occurred (ISO format)", "nullable": True},
        "event_type": {
            "type": "string",
            "description": f"Event type - one of: {', '.join(enum_to_list(EventType))}",
            "enum": enum_to_list(EventType),
            "nullable": True
        },
        "source_article_ids": {"type": "string", "description": "Comma-separated article IDs", "nullable": True},
    }
    output_type = "string"  # JSON string
    
    def __init__(self, collector=None):
        """Initialize the event identifier.

        Args:
            collector: Optional ResultCollector[Event] for storing results.
                      If provided, events are added to the collector instead of internal storage.
        """
        super().__init__(collector)
    
    def forward(
        self,
        title: str,
        description: str,
        domain: str,
        occurred_date: str = None,
        event_type: str = None,
        source_article_ids: str = None
    ) -> str:
        """Store event data and return as structured JSON.

        Args:
            title: Event title
            description: Event description
            domain: Event domain (string, will be converted to enum)
            occurred_date: Optional occurrence date (ISO format)
            event_type: Type of event (string, will be converted to enum)
            source_article_ids: Optional comma-separated article IDs

        Returns:
            JSON string of Event object
        """
        # Parse occurred date or use current time
        event_date = parse_iso_datetime(occurred_date)
        event_date = ensure_timezone_aware(event_date)
        
        # Parse article IDs
        article_ids = []
        if source_article_ids:
            article_ids = [aid.strip() for aid in source_article_ids.split(',')]

        # Validate and convert domain
        domain_enum = parse_domain(domain)

        # Validate and convert event_type
        event_type_enum = parse_event_type(event_type)

        # Generate unique event ID (use count of stored events as counter)
        event_id = generate_event_id(domain_enum, event_date, self.get_stored_count())

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
        
        # Store event using unified collector interface
        self.store_result(event, context=f"Event {event.id}")
        
        # Return summary to save tokens (NOT full event)
        summary = {
            "id": event.id,
            "title": event.title,
            "domain": event.domain,
            "event_type": event.event_type.value,
            "status": event.status.value,
            "occurred_date": event.occurred_date.isoformat() if event.occurred_date else None,
            "description_preview": description[:150] + "..." if len(description) > 150 else description,
            "status": "stored"
        }
        
        return json.dumps(summary, indent=2, default=str)

