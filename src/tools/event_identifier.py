"""Event identification tool using LLM to extract events from articles."""

import json
from datetime import datetime, timezone
from typing import List, Optional

from src.domain.models import Article, Event, EventType, EventStatus, Domain
from src.utils.enums import enum_to_list, parse_domain, parse_event_type
from src.utils.id_generator import generate_event_id
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.utils.similarity import SimilarityMatcher
from src.tools.base import CollectorAwareTool, ToolResponseMixin


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
    description = f"""Stores identified event data into structured Event format.

    Use this tool AFTER you've analyzed articles and identified specific events.
    Call this tool once for EACH event you identify (not all at once).
    
    NOTE: This tool automatically deduplicates events. If a similar event
    already exists in the database, it will return that event instead of
    creating a duplicate.

    Args:
        title (str): Short descriptive title of the event
        description (str): Detailed description of what happened/will happen
        domain (str): Event domain - one of: {", ".join(enum_to_list(Domain))}
        occurred_date (str, optional): When the event occurred (ISO format with time zone)
        event_type (str, optional): Type of event - one of: {", ".join(enum_to_list(EventType))}
        source_article_ids (str, optional): Comma-separated article IDs mentioning this event

    Returns:
        str: JSON string with the created/matched Event object including ID
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
        },
        "is_target": {
            "type": "boolean",
            "description": "Set to True if this event is the TARGET event (the outcome/ground truth) for the question. Logic will fail if a target already exists.",
            "nullable": True,
        },
        "is_outcome": {
            "type": "boolean",
            "description": "Set to True if this event represents a possible outcome scenario for the question (e.g., 'Yes', 'No', or MCQ option)",
            "nullable": True,
        },
        "outcome_scenario": {
            "type": "string",
            "description": "Type of outcome scenario (only for is_outcome=True): positive_resolution | negative_resolution | mcq_option | counterfactual",
            "nullable": True,
        },
        "outcome_option_index": {
            "type": "integer",
            "description": "Option index for MCQ outcomes (0-based, only for outcome_scenario=mcq_option)",
            "nullable": True,
        },
        "outcome_impacts": {
            "type": "string",
            "description": 'JSON array of impact assessments: [{"outcome_event_id": "evt_...", "direction": "positive|negative", "magnitude": 0.7, "confidence": 0.8, "reasoning": "..."}]',
            "nullable": True,
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

        # Initialize database using DatabaseAwareTool pattern
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

        self.similarity_threshold = similarity_threshold
        self.deduplicate = deduplicate
        self.time_window_days = time_window_days
        self.question_id = question_id  # Provenance context
        self._matcher: Optional[SimilarityMatcher] = None

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
        occurred_date: str = None,
        event_type: str = None,
        is_target: bool = False,
        is_outcome: bool = False,
        outcome_scenario: str = None,
        outcome_option_index: int = None,
        outcome_impacts: str = None,
    ) -> str:
        """Store event data and return as structured JSON.

        Args:
            title: Event title
            description: Event description
            domain: Event domain (string, will be converted to enum)
            occurred_date: Optional occurrence date (ISO format)
            event_type: Type of event (string, will be converted to enum)
            source_article_ids: Comma-separated article IDs
            is_target: If True, attempts to set this event as the question's target
            is_outcome: If True, marks this as an outcome event
            outcome_scenario: Type of outcome (positive_resolution, negative_resolution, etc.)
            outcome_option_index: Option index for MCQ outcomes
            outcome_impacts: JSON array of impact assessments on outcome events

        Returns:
            JSON string of Event object (new or existing match)
        """
        # Parse occurred date or use current time
        event_date = parse_iso_datetime(occurred_date)
        event_date = ensure_timezone_aware(event_date)

        # Parse article IDs
        article_ids = []
        if source_article_ids:
            article_ids = [aid.strip() for aid in source_article_ids.split(",")]
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
                    return self.error_response(
                        "The following article IDs do not exist in database",
                        error="missing_article_ids",
                        missing_ids=missing_ids,
                    )

                if invalid_date_articles:
                    return self.error_response(
                        "The following articles have dates prior to the event occurring date, meaning they cannot be the source of this event",
                        error="invalid_article_dates",
                        invalid_articles=invalid_date_articles,
                    )

        else:
            return self.error_response(
                "source_article_ids cannot be empty", error="empty_source_article_ids"
            )
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
                outcome_scenario=outcome_scenario,
                outcome_option_index=outcome_option_index,
            )
            is_new = True

        # Handle target event assignment logic
        target_info = {}
        if is_target:
            if not self.question_id or not self.db:
                return self.error_response(
                    "Cannot set is_target=True without question_id and db_path configured.",
                    error="config_error",
                )

            from src.domain.models import Question

            question = self.db.get(Question, self.question_id)

            if not question:
                return self.error_response(
                    f"Question {self.question_id} not found", error="question_not_found"
                )

            if question.target_event_id and question.target_event_id != event.id:
                # Target already exists and is different - return ERROR as requested
                return self.error_response(
                    f"Question already has a target event ({question.target_event_id}). Cannot assign new target {event.id}.",
                    error="target_already_exists",
                    existing_target_id=question.target_event_id,
                    proposed_target_id=event.id,
                )

            if not question.target_event_id:
                question.target_event_id = event.id
                self.db.save(Question, question)
                logger.info(
                    f"Assigned event {event.id} as target for question {question.id}"
                )
                target_info = {"is_target": True, "action": "assigned_as_target"}
            else:
                target_info = {
                    "is_target": True,
                    "action": "already_target (no change)",
                }

        # Handle outcome impacts if provided
        impact_results = []
        if outcome_impacts and self.db:
            impact_results = self._record_outcome_impacts(event.id, outcome_impacts)

        return self._format_response(
            event=event,
            is_new=is_new,
            updated_articles=updated_articles,
            time_window_validation=time_window_validation,
            target_info=target_info,
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
        outcome_scenario: str = None,
        outcome_option_index: int = None,
    ) -> Event:
        """Create a new event.

        Args:
            title: Event title
            description: Event description
            domain_enum: Event domain
            event_type_enum: Event type
            event_date: Event date
            article_ids: Source article IDs
            is_outcome: Whether this is an outcome event
            outcome_scenario: Type of outcome scenario
            outcome_option_index: Option index for MCQ outcomes

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

        # Parse outcome scenario if provided
        from src.domain.models.event import OutcomeScenario

        outcome_scenario_enum = None
        if outcome_scenario:
            try:
                outcome_scenario_enum = OutcomeScenario(outcome_scenario.lower())
            except ValueError:
                pass

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
            outcome_scenario=outcome_scenario_enum,
            outcome_option_index=outcome_option_index,
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
        target_info: dict = None,
        impact_results: List[dict] = None,
    ) -> str:
        """Format event response as JSON.

        Args:
            event: Event to format
            is_new: Whether this is a newly created event
            updated_articles: Whether existing event was updated with new articles
            time_window_validation: Optional validation warnings about event date
            target_info: Optional target assignment info
            impact_results: Optional outcome impact recording results

        Returns:
            JSON string summary
        """
        status_msg = (
            "created"
            if is_new
            else ("updated" if updated_articles else "reused_existing")
        )

        summary = {
            "id": event.id,
            "title": event.title,
            "domain": event.domain.value
            if hasattr(event.domain, "value")
            else str(event.domain),
            "event_type": event.event_type.value
            if hasattr(event.event_type, "value")
            else str(event.event_type),
            "occurred_date": event.occurred_date.isoformat()
            if event.occurred_date
            else None,
            "description_preview": event.description[:150] + "..."
            if len(event.description) > 150
            else event.description,
            "status": status_msg,
            "is_new": is_new,
        }

        if not is_new:
            summary["note"] = "Matched existing event - no duplicate created"

        # Add outcome event info if applicable
        if event.is_outcome:
            summary["is_outcome"] = True
            summary["outcome_scenario"] = (
                event.outcome_scenario.value if event.outcome_scenario else None
            )
            if event.outcome_option_index is not None:
                summary["outcome_option_index"] = event.outcome_option_index

        # Add time window validation warnings if present
        if time_window_validation:
            summary["status"] = f"{status_msg}_with_warnings"
            summary["warnings"] = time_window_validation["warnings"]
            summary["recommendation"] = time_window_validation["recommendation"]
            summary["suggestion"] = (
                "Consider identifying events that occurred within the valid time window for better causal analysis."
            )

        if target_info:
            summary["target_info"] = target_info

        if impact_results:
            summary["outcome_impacts"] = impact_results

        return json.dumps(summary, indent=2, default=str)
