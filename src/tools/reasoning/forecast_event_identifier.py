"""Event identification for forecasting - dual DB access.

This tool reads from the question database for deduplication and writes
ForecastEvent instances to the forecast database.
"""

from typing import Optional
from datetime import datetime

from smolagents import Tool
from src.domain.models.forecast_graph import ForecastEvent
from src.domain.models.event import Event, EventType
from src.core.database import GenericDatabase
from src.utils.logging import logger
from src.utils.enums import parse_domain, parse_event_type, enum_to_list, Domain
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.domain.models.id_generator import generate_forecast_event_id
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import ForecastEventOutput


class ForecastEventIdentifierTool(Tool):
    """Identify events during forecasting, save to forecast DB.

    Dual DB access:
    - Read from question DB (deduplication)
    - Write to forecast DB (ForecastEvent instances)
    """

    name = "identify_forecast_event"
    description = """Identify event for forecast reasoning (saved to forecast DB).

    Use this tool to identify and record events that are relevant to your forecast.
    The tool checks for existing events and either reuses them or creates new ones.

    Args:
        title (str): Short descriptive title of the event
        description (str): Detailed description of what happened/will happen
        domain (str): Event domain (finance|politics|tech|health|climate|general)
        occurred_date (str): When the event occurred (ISO format with timezone)
        event_type (str, optional): Type of event (decision|outcome|indicator|milestone|external_shock)
        source_article_ids (str, optional): Comma-separated article IDs mentioning this event

    Returns:
        str: JSON string with event details and status (created or reused)
    """

    inputs = {
        "title": {"type": "string", "description": "Short event title"},
        "description": {"type": "string", "description": "Detailed event description"},
        "occurred_date": {
            "type": "string",
            "description": "When event occurred (ISO 8601 WITH timezone, e.g. 2025-11-27T14:30:00Z)",
        },
        "domain": {
            "type": "string",
            "description": "Event domain (optional, defaults to 'general' if invalid)",
            "nullable": True,
        },
        "event_type": {
            "type": "string",
            "description": f"Event type - one of: {', '.join(enum_to_list(EventType))}",
            "enum": enum_to_list(EventType),
            "nullable": True,
        },
        "source_article_ids": {
            "type": "string",
            "description": "Comma-separated article IDs",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(ForecastEventOutput)

    def __init__(
        self,
        question_db_path: str = "worldreasoner.db",
        forecast_db_path: str = None,
        session_id: str = None,
    ):
        """Initialize the forecast event identifier.

        Args:
            question_db_path: Path to question database for deduplication
            forecast_db_path: Path to forecast database for writing
            session_id: Session ID for tracking this forecast session
        """
        super().__init__()

        # Initialize databases using simplified pattern

        # Question DB for reading existing events
        self.question_db = GenericDatabase(question_db_path)

        # Forecast DB for writing ForecastEvents
        self.forecast_db_path = forecast_db_path or question_db_path
        self.forecast_db = GenericDatabase(self.forecast_db_path)

        self.session_id = session_id

    def forward(
        self,
        title: str,
        description: str,
        occurred_date: str,
        domain: Optional[str] = None,
        event_type: Optional[str] = None,
        source_article_ids: Optional[str] = None,
    ) -> ForecastEventOutput:
        """Identify event and save to forecast database.

        Args:
            title: Event title
            description: Event description
            domain: Event domain
            occurred_date: When event occurred (ISO format)
            event_type: Optional event type
            source_article_ids: Optional comma-separated article IDs

        Returns:
            ForecastEventOutput with event details
        """
        try:
            # Parse and validate with fallback
            domain_enum = parse_domain(domain, default=Domain.GENERAL)
            occurred_date_obj = parse_iso_datetime(occurred_date)
            occurred_date_obj = ensure_timezone_aware(occurred_date_obj)
            event_type_enum = parse_event_type(event_type) if event_type else None
            article_ids = (
                [aid.strip() for aid in source_article_ids.split(",") if aid.strip()]
                if source_article_ids
                else []
            )

            # Check question DB for existing event
            existing = self._find_existing_event(title, occurred_date_obj, domain_enum)
            if existing:
                # Reuse existing event, save ForecastEvent reference
                forecast_event = ForecastEvent(
                    id=existing.id,
                    forecast_id=None,
                    session_id=self.session_id,
                    title=existing.title,
                    description=existing.description,
                    domain=existing.domain,
                    occurred_date=existing.occurred_date,
                    event_type=existing.event_type,
                    source_article_ids=article_ids,
                    identified_by="forecast_agent_reused",
                )
                self.forecast_db.save(ForecastEvent, forecast_event)
                logger.info(f"Reused existing event: {existing.id}")
                return ForecastEventOutput(
                    status="reused",
                    event={
                        "id": forecast_event.id,
                        "title": forecast_event.title,
                        "domain": forecast_event.domain.value
                        if hasattr(forecast_event.domain, "value")
                        else forecast_event.domain,
                    },
                )

            # Create new ForecastEvent
            event_id = generate_forecast_event_id()
            forecast_event = ForecastEvent(
                id=event_id,
                forecast_id=None,
                session_id=self.session_id,
                title=title,
                description=description,
                domain=domain_enum,
                occurred_date=occurred_date_obj,
                event_type=event_type_enum,
                source_article_ids=article_ids,
            )

            self.forecast_db.save(ForecastEvent, forecast_event)
            logger.info(f"Saved forecast event: {event_id}")
            return ForecastEventOutput(
                status="created",
                event={
                    "id": forecast_event.id,
                    "title": forecast_event.title,
                    "domain": forecast_event.domain.value
                    if hasattr(forecast_event.domain, "value")
                    else forecast_event.domain,
                },
            )

        except Exception as e:
            logger.error(f"Error identifying forecast event: {e}")
            return ForecastEventOutput(
                status="error",
                event={"error": str(e)},
            )

    def _find_existing_event(
        self, title: str, occurred_date: datetime, domain
    ) -> Optional[Event]:
        """Find existing event in question DB for deduplication.

        Args:
            title: Event title
            occurred_date: Event occurrence date
            domain: Event domain

        Returns:
            Existing Event if found, None otherwise
        """
        try:
            # Query question DB for events with matching characteristics
            all_events = self.question_db.get_many(Event, filters={"domain": domain})

            # Simple fuzzy matching on title and date
            for event in all_events:
                if (
                    event.occurred_date
                    and abs((event.occurred_date - occurred_date).total_seconds())
                    < 86400
                ):
                    # Within 1 day
                    if (
                        title.lower() in event.title.lower()
                        or event.title.lower() in title.lower()
                    ):
                        return event

            return None
        except Exception as e:
            logger.debug(f"Could not check for existing events: {e}")
            return None
