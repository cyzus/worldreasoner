"""Event identification tool using LLM to extract events from articles."""

import json
from datetime import datetime, timezone
from typing import List, Optional

from src.domain.models import (
    Article,
    Event,
    EventType,
    EventStatus,
    Domain,
    OutcomeScenario,
)
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.domain.models.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.utils.similarity import SimilarityMatcher
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.base import CollectorAwareTool, ToolResponseMixin
from src.tools.base.output_models import EventOutput


# Default similarity threshold for event deduplication
DEFAULT_SIMILARITY_THRESHOLD = 0.65


class EventIdentifierTool(CollectorAwareTool[Event], ToolResponseMixin):
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
    description = """Stores identified event data into structured Event format.

    Use this tool AFTER you've analyzed articles and identified specific events.
    Call this tool once for EACH event you identify (not all at once).
    
    Returns:
        Event (JSON containing event data and its ID).
    """

    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "title": {"type": "string", "description": "Short event title"},
        "description": {"type": "string", "description": "Detailed event description"},
        "domain": {
            "type": "string",
            "description": f"Event domain - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain),
        },
        "occurred_date": {
            "type": "string",
            "description": "When event occurred (ISO 8601 WITH timezone, e.g. 2025-11-27T14:30:00Z or 2025-11-27T14:30:00+00:00; MUST include 'Z' or an explicit offset)",
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
        },
        "is_outcome": {
            "type": "boolean",
            "description": "If True, marks this as an EXTENDED/ALTERNATIVE outcome event discovered during research (not one of the initial pre-generated outcomes).",
            "default": False,
            "nullable": True,
        },
        "outcome_impacts": {
            "type": "string",
            "description": 'JSON array of impact assessments on pre-created outcome events: [{"outcome_event_id": "evt_...", "direction": "positive|negative", "magnitude": 0.7, "confidence": 0.8, "reasoning": "..."}]. Use outcome_event_ids from the prompt.',
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(EventOutput)

    def __init__(
        self,
        collector=None,
        db_path: str = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        deduplicate: bool = True,
        time_window_days: int = 60,
        question_id: Optional[str] = None,
        alias_registry=None,
        staging: bool = False,
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

        # Initialize database using DatabaseAwareTool pattern
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

        # Ensure required tables exist (prevents "no such table" errors on fresh DBs)
        if self.db:
            from src.domain.models.event_outcome_impact import EventOutcomeImpact

            self.db.create_table(Event)
            self.db.create_table(EventOutcomeImpact)

        self.similarity_threshold = similarity_threshold
        self.deduplicate = deduplicate
        self.time_window_days = time_window_days
        self.question_id = question_id  # Provenance context
        self._matcher: Optional[SimilarityMatcher] = None
        self.alias_registry = alias_registry
        self.staging = staging

        # Initialize similarity matcher if database available
        if self.db:
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
        occurred_date: str,
        event_type: str = None,
        is_outcome: bool = False,
        outcome_impacts: str = None,
    ) -> EventOutput:
        """Store event data and return as structured Event.

        Args:
            title: Event title
            description: Event description
            domain: Event domain (string, will be converted to enum)
            occurred_date: Optional occurrence date (ISO format)
            event_type: Type of event (string, will be converted to enum)
            source_article_ids: Comma-separated article IDs
            is_outcome: If True, marks as discovered outcome event
            outcome_impacts: JSON array of impact assessments on pre-created outcome events

        Returns:
            EventOutput: Pydantic model with event details
        """
        # Parse occurred date or use current time
        event_date = parse_iso_datetime(occurred_date)
        event_date = ensure_timezone_aware(event_date)

        # Parse article IDs (resolve aliases like A1:BBCSanctions to real IDs)
        article_ids = []
        article_date_warnings = []
        if source_article_ids:
            if getattr(self, "alias_registry", None):
                source_article_ids = self.alias_registry.resolve_article_ids(
                    source_article_ids
                )
            article_ids = [aid.strip() for aid in source_article_ids.split(",")]
            if self.db is not None:
                # Verify article IDs exist in database
                missing_ids = []
                invalid_date_articles = []
                article_dates = []
                for aid in article_ids:
                    article = self.db.get(Article, aid)
                    if article is None:
                        missing_ids.append(aid)
                    else:
                        # Check that article date is not prior to event date
                        article_date = article.published_date
                        if article_date and event_date:
                            article_date = ensure_timezone_aware(article_date)
                            article_dates.append(article_date)
                            if article_date < event_date:
                                invalid_date_articles.append(
                                    f"{aid} (article: {article_date.isoformat()}, event: {event_date.isoformat()})"
                                )

                if missing_ids:
                    return EventOutput(
                        id="error",
                        title=title,
                        domain=domain,
                        status=f"error: missing_article_ids - The following article IDs do not exist in database: {', '.join(missing_ids)}"
                    )

                if invalid_date_articles:
                    return EventOutput(
                        id="error",
                        title=title,
                        domain=domain,
                        status=f"error: invalid_article_dates - The following articles have dates prior to the event occurring date, meaning they cannot be the source of this event: {', '.join(invalid_date_articles)}"
                    )

                # Date proximity check: flag only if ALL source articles are published before the event date
                # which is genuinely impossible (an article cannot report an event that hasn't happened yet)
                if article_dates and event_date:
                    latest_article = max(article_dates)
                    if latest_article.date() < event_date.date():
                        article_date_warnings.append(
                            f"DATE ACCURACY WARNING: All source articles were published before the event date ({event_date.strftime('%Y-%m-%d')}). "
                            f"This is impossible. Please verify the event date."
                        )

        # No article IDs provided — allowed (graph builder creates events without articles)
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
                    entity_type="Event",
                )

        # Try to find existing similar event (deduplication)
        existing_event = self._find_existing_event(
            title=title,
            description=description,
            domain=domain_enum,
            event_date=event_date,
        )

        event = None
        is_new = False
        updated_articles = False

        if existing_event:
            event = existing_event
            # Update existing event with new article links if provided
            updated_articles = self._update_existing_event(existing_event, article_ids)
        else:
            # Create new event
            event = self._create_new_event(
                title=title,
                description=description,
                domain_enum=domain_enum,
                event_type_enum=event_type_enum,
                event_date=event_date,
                article_ids=article_ids,
                is_outcome=is_outcome,
            )
            is_new = True

        # Handle outcome impacts if provided
        impact_results = []
        if outcome_impacts and self.db:
            impact_results = self._record_outcome_impacts(event.id, outcome_impacts)

        return self._format_response(
            event=event,
            is_new=is_new,
            updated_articles=updated_articles,
            time_window_validation=time_window_validation,
            article_date_warnings=article_date_warnings,
            impact_results=impact_results,
        )

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
            logger.info(
                f"Found existing event '{match.title}' (ID: {match.id}) - reusing instead of creating duplicate"
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
            self.db.save(Event, event)
            logger.debug(
                f"Updated event {event.id} with {len(new_ids)} new article links"
            )

        return True

    def _create_new_event(
        self,
        title: str,
        description: str,
        domain_enum: Domain,
        event_type_enum: EventType,
        event_date: datetime,
        article_ids: List[str],
        is_outcome: bool = False,
    ) -> Event:
        """Create a new event.

        Args:
            title: Event title
            description: Event description
            domain_enum: Event domain
            event_type_enum: Event type
            event_date: Event date
            article_ids: Source article IDs
            is_outcome: Whether this is a discovered outcome event

        Returns:
            New Event instance
        """
        # Generate unique event ID
        event_id = generate_event_id(domain_enum, event_date, self.get_stored_count())

        # Determine status based on date
        status = (
            EventStatus.OCCURRED
            if event_date <= datetime.now(timezone.utc)
            else EventStatus.PREDICTED
        )

        # Build metadata with provenance info
        metadata = {}
        if self.question_id:
            metadata["related_question_ids"] = [self.question_id]
            metadata["extracted_for_evidence"] = True

        # Determine source article (first article in list)
        source_article_id = article_ids[0] if article_ids else None

        # Determine outcome scenario
        outcome_scenario = None
        if is_outcome:
            outcome_scenario = OutcomeScenario.DISCOVERED

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
            is_outcome=is_outcome,
            outcome_scenario=outcome_scenario,
        )

        # Store event using unified collector interface
        self.store_result(event, context=f"Event {event.id}")

        # Persist to database if available
        if self.db is not None:
            self.db.save(Event, event)
            logger.debug(f"Event {event.id} persisted to database")

        return event

    def _record_outcome_impacts(
        self, event_id: str, outcome_impacts_json: str
    ) -> List[dict]:
        """Record impact assessments on outcome events.

        Args:
            event_id: ID of the event that has impacts
            outcome_impacts_json: JSON array of impact assessments

        Returns:
            List of result dicts for each impact
        """
        from src.domain.models.event_outcome_impact import (
            EventOutcomeImpact,
            ImpactDirection,
        )

        try:
            impacts = json.loads(outcome_impacts_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse outcome_impacts JSON: {e}")
            return [{"error": f"Invalid JSON: {e}"}]

        if not isinstance(impacts, list):
            return [{"error": "outcome_impacts must be a JSON array"}]

        results = []
        for impact_data in impacts:
            try:
                # Validate required fields
                required = [
                    "outcome_event_id",
                    "direction",
                    "magnitude",
                    "confidence",
                    "reasoning",
                ]
                missing = [f for f in required if f not in impact_data]
                if missing:
                    results.append({"error": f"Missing required fields: {missing}"})
                    continue

                # Verify outcome event exists and is marked as outcome
                outcome_event = self.db.get(Event, impact_data["outcome_event_id"])
                if not outcome_event:
                    # Provide helpful error with list of valid outcome events
                    error_msg = (
                        f"Outcome event {impact_data['outcome_event_id']} not found."
                    )

                    # Find available outcome events for this question
                    if self.question_id:
                        available_outcomes = self.db.get_many(
                            Event,
                            filters={
                                "extracted_for_question_id": self.question_id,
                                "is_outcome": True,
                            },
                        )
                        if available_outcomes:
                            outcome_list = [
                                f"{e.id} ({e.title})" for e in available_outcomes
                            ]
                            error_msg += f" Valid outcome events for this question: {', '.join(outcome_list)}"
                        else:
                            error_msg += " No outcome events found for this question. Create outcome events first using is_outcome=True."

                    results.append({"error": error_msg})
                    continue

                if not outcome_event.is_outcome:
                    # Provide helpful error explaining the issue
                    error_msg = f"Event {impact_data['outcome_event_id']} exists but is not marked as an outcome event."

                    # Find available outcome events
                    if self.question_id:
                        available_outcomes = self.db.get_many(
                            Event,
                            filters={
                                "extracted_for_question_id": self.question_id,
                                "is_outcome": True,
                            },
                        )
                        if available_outcomes:
                            outcome_list = [
                                f"{e.id} ({e.title})" for e in available_outcomes
                            ]
                            error_msg += (
                                f" Valid outcome events: {', '.join(outcome_list)}"
                            )
                        else:
                            error_msg += (
                                " Create outcome events with is_outcome=True first."
                            )

                    results.append({"error": error_msg})
                    continue

                # Parse impact direction
                try:
                    direction = ImpactDirection(impact_data["direction"].lower())
                except ValueError:
                    results.append(
                        {"error": f"Invalid direction: {impact_data['direction']}"}
                    )
                    continue

                # Check for existing impact (deduplication)
                existing = self.db.get_many(
                    EventOutcomeImpact,
                    filters={
                        "event_id": event_id,
                        "outcome_event_id": impact_data["outcome_event_id"],
                    },
                )

                if existing:
                    # Update existing impact
                    impact = existing[0]
                    impact.impact_direction = direction
                    impact.impact_magnitude = float(impact_data["magnitude"])
                    impact.confidence = float(impact_data["confidence"])
                    impact.reasoning = impact_data["reasoning"]
                    impact.last_confirmed_at = datetime.now(timezone.utc)
                    if (
                        self.question_id
                        and self.question_id not in impact.discovered_by_question_ids
                    ):
                        impact.discovered_by_question_ids.append(self.question_id)
                    self.db.save(EventOutcomeImpact, impact)
                    results.append(
                        {
                            "outcome_event_id": impact_data["outcome_event_id"],
                            "status": "updated",
                        }
                    )
                else:
                    # Create new impact
                    import uuid as uuid_module

                    impact = EventOutcomeImpact(
                        id=f"impact_{uuid_module.uuid4().hex[:12]}",
                        event_id=event_id,
                        outcome_event_id=impact_data["outcome_event_id"],
                        question_id=self.question_id or "",
                        impact_direction=direction,
                        impact_magnitude=float(impact_data["magnitude"]),
                        confidence=float(impact_data["confidence"]),
                        reasoning=impact_data["reasoning"],
                        evidence_article_ids=impact_data.get(
                            "evidence_article_ids", []
                        ),
                        causal_chain_hypothesis_ids=impact_data.get(
                            "causal_chain_ids", []
                        ),
                        discovered_by_question_ids=[self.question_id]
                        if self.question_id
                        else [],
                        identified_by=f"event_identifier_tool_{self.question_id}",
                    )
                    self.db.save(EventOutcomeImpact, impact)
                    results.append(
                        {
                            "outcome_event_id": impact_data["outcome_event_id"],
                            "status": "created",
                        }
                    )

            except Exception as e:
                logger.error(f"Error recording outcome impact: {e}")
                results.append({"error": str(e)})

        return results

    def _format_response(
        self,
        event: Event,
        is_new: bool,
        updated_articles: bool = False,
        time_window_validation: dict = None,
        article_date_warnings: List[str] = None,
        impact_results: List[dict] = None,
    ) -> str:
        """Format event response as JSON.

        Args:
            event: Event to format
            is_new: Whether this is a newly created event
            updated_articles: Whether existing event was updated with new articles
            time_window_validation: Optional validation warnings about event date
            article_date_warnings: Optional warnings about date proximity to source articles
            impact_results: Optional outcome impact recording results

        Returns:
            JSON string summary
        """
        status_msg = (
            "created"
            if is_new
            else ("updated" if updated_articles else "reused_existing")
        )

        # Collect all warnings to surface to agent
        all_warnings = []
        if time_window_validation and "warnings" in time_window_validation:
            all_warnings.extend(time_window_validation["warnings"])
            if "recommendation" in time_window_validation:
                all_warnings.append(time_window_validation["recommendation"])
        if article_date_warnings:
            all_warnings.extend(article_date_warnings)

        if all_warnings:
            status_msg = f"{status_msg}_with_warnings"

        # Format occurred_date for agent visibility
        event_date_str = None
        if event.occurred_date:
            event_date_str = event.occurred_date.isoformat()
        elif event.predicted_date:
            event_date_str = event.predicted_date.isoformat()

        # Generate alias if registry is provided
        alias_val = None
        if getattr(self, "alias_registry", None):
            alias_val = self.alias_registry.generate_alias(event.title, event.id)

        actual_outcome_id = None
        if self.db and getattr(self, "question_id", None):
            # Try to find the actual outcome event for this question
            events = self.db.get_many(Event)
            for e in events:
                if getattr(e, "extracted_for_question_id", None) == self.question_id and getattr(e, "is_outcome", False) and getattr(e, "is_actual_outcome", False):
                    actual_outcome_id = e.id
                    break

        return EventOutput(
            id=event.id,
            alias=alias_val,
            title=event.title,
            domain=event.domain.value if hasattr(event.domain, "value") else str(event.domain),
            status=status_msg,
            occurred_date=event_date_str,
            warnings=all_warnings if all_warnings else None,
            actual_outcome_event_id=actual_outcome_id,
        )
