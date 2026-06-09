"""Questions API endpoints.

Provides REST API for querying forecast questions.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field

from src.core.database import GenericDatabase
from src.domain.models import Question, CausalHypothesis, Article
from src.domain.models.domain import Domain
from src.domain.models.question import QuestionType
from src.api.routes.database import get_current_db_path
from src.utils.logging import logger
from src.analysis.article_analysis import analyze_article_coverage
from src.config.collection_goal import QualityRequirements
from src.services.question_monitor_service import QuestionMonitorService


router = APIRouter()


# Dependency for getting database
def get_database() -> GenericDatabase:
    """Dependency to get database instance."""
    return GenericDatabase(get_current_db_path())


class QuestionListItem(BaseModel):
    """Simplified question model for list views."""

    id: str
    question_text: str
    question_type: str
    domain: str
    difficulty: int
    source: str
    target_event_id: Optional[str]
    related_event_ids: List[str]
    quality_score: Optional[float] = None
    resolution_date: Optional[str] = None
    estimated_start_time: Optional[str] = None
    ground_truth: Optional[Any] = None
    causal_explanation: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    article_count: int = 0
    graph_built: bool = False
    forecast_count: int = 0
    forecast_modes: List[str] = Field(default_factory=list)
    evidence_satisfied: bool = False


class PolymarketSearchRequest(BaseModel):
    """Request parameters for searching Polymarket."""

    query: str = Field(description="Search query term")
    limit_per_type: int = Field(
        default=20, ge=1, le=100, description="Results limit per content type (1-100)"
    )
    events_tag: Optional[List[str]] = Field(
        default=None, description="Filter by event tags"
    )
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    type: Optional[str] = Field(
        default="events", description="Result type filter, e.g. 'events'"
    )
    events_status: Optional[str] = Field(
        default="resolved", description="Event status filter: 'active' or 'resolved'"
    )
    sort: Optional[str] = Field(
        default="closed_time", description="Sort key, e.g. 'closed_time'"
    )
    presets: Optional[List[str]] = Field(
        default_factory=lambda: ["EventsTitle", "Events"],
        description="Response presets",
    )


class PolymarketSearchResponse(BaseModel):
    """Response from Polymarket search."""

    success: bool
    page: int = 1
    limit_per_type: int = 20
    events: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[Dict[str, Any]] = Field(default_factory=list)
    profiles: List[Dict[str, Any]] = Field(default_factory=list)
    total_events: int
    total_tags: int
    total_profiles: int


class QuestionPreviewRequest(BaseModel):
    """Request parameters for previewing questions from sources."""

    source: str = Field(description="Source to collect from: 'polymarket' or 'news'")
    count: int = Field(
        default=20, ge=1, le=500, description="Number of questions to fetch (1-500)"
    )
    domains: Optional[List[str]] = Field(default=None, description="Filter by domains")
    question_types: Optional[List[str]] = Field(
        default=None, description="Filter by question types"
    )
    min_difficulty: Optional[int] = Field(
        default=None, ge=1, le=5, description="Minimum difficulty (1-5)"
    )
    max_difficulty: Optional[int] = Field(
        default=None, ge=1, le=5, description="Maximum difficulty (1-5)"
    )
    tags: Optional[List[str]] = Field(
        default=None, description="Polymarket tags (e.g., 'politics', 'crypto')"
    )
    include_resolved: Optional[bool] = Field(
        default=True, description="Include resolved markets (Polymarket only)"
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Search query for Polymarket markets (Polymarket only)",
    )
    lookback_days: Optional[int] = Field(
        default=730,
        ge=1,
        le=3650,
        description="Max age of markets in days (default: 2 years)",
    )


class QuestionPreviewResponse(BaseModel):
    """Response containing previewed questions."""

    success: bool
    questions: List[Dict[str, Any]]
    total: int
    source: str
    errors: List[str] = Field(default_factory=list)


class BatchSaveRequest(BaseModel):
    """Request to save selected questions to database."""

    question_ids: List[str] = Field(description="IDs of questions to save")
    questions: List[Dict[str, Any]] = Field(description="Full question data to save")


@router.post("/polymarket/search", response_model=PolymarketSearchResponse)
async def search_polymarket(request: PolymarketSearchRequest):
    """Search Polymarket markets, events, and profiles.

    This endpoint uses Polymarket's public search API to find markets
    matching a search query.

    Args:
        request: Search request with query and optional filters

    Returns:
        Search results including events, tags, and profiles
    """
    try:
        logger.info(f"Searching Polymarket for: '{request.query}'")

        from src.integrations.polymarket_client import PolymarketClient

        client = PolymarketClient()
        results = await client.search_markets(
            query=request.query,
            limit_per_type=request.limit_per_type,
            events_tag=request.events_tag,
            page=request.page,
            result_type=request.type,
            events_status=request.events_status,
            sort=request.sort,
            presets=request.presets,
        )

        events = results.get("events", [])
        tags = results.get("tags", [])
        profiles = results.get("profiles", [])

        return PolymarketSearchResponse(
            success=len(events) > 0 or len(tags) > 0 or len(profiles) > 0,
            page=request.page,
            limit_per_type=request.limit_per_type,
            events=events,
            tags=tags,
            profiles=profiles,
            total_events=len(events),
            total_tags=len(tags),
            total_profiles=len(profiles),
        )

    except Exception as e:
        logger.error(f"Failed to search Polymarket: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview", response_model=QuestionPreviewResponse)
async def preview_questions(request: QuestionPreviewRequest):
    """Preview questions from a source without saving to database.

    This endpoint allows fetching questions from Polymarket or news sources
    for manual review before adding them to the database.

    Args:
        request: Preview request with source and filtering parameters

    Returns:
        Preview response with questions and metadata
    """
    try:
        logger.info(
            f"Previewing questions from {request.source} (count={request.count})"
        )
        logger.info(
            f"Request details: search_query={request.search_query!r}, include_resolved={request.include_resolved}"
        )

        # Initialize the appropriate source runner
        from src.pipelines.collection import PolymarketRunner, NewsBasedRunner

        errors = []
        questions_list = []

        if request.source == "polymarket":
            # Create quality requirements
            quality = QualityRequirements()
            if request.min_difficulty:
                quality.min_difficulty = request.min_difficulty
            if request.max_difficulty:
                quality.max_difficulty = request.max_difficulty
            # Set lookback window (negative value indicates lookback from now)
            if request.lookback_days:
                quality.min_resolution_days = -request.lookback_days

            # Initialize runner with require_ground_truth based on include_resolved
            # require_ground_truth=True fetches resolved markets with ground truth
            # require_ground_truth=False fetches active prediction markets
            runner = PolymarketRunner(
                require_ground_truth=request.include_resolved
                if request.include_resolved is not None
                else True
            )

            # Map domains to tag-based category filter
            # If domains are specified, use them; otherwise if tags specified, map tags to domains
            category_filter = None
            if request.domains:
                category_filter = request.domains
            elif request.tags:
                # Map Polymarket tags to domains
                tag_to_domain = {
                    "politics": "politics",
                    "geopolitics": "politics",
                    "elections": "politics",
                    "crypto": "finance",
                    "finance": "finance",
                    "economy": "finance",
                    "sports": "sports",
                    "tech": "technology",
                    "ai": "technology",
                    "pop culture": "culture",
                    "entertainment": "culture",
                    "science": "science",
                    "business": "business",
                    "health": "health",
                    "pandemic": "health",
                }
                mapped_domains = []
                for tag in request.tags:
                    domain = tag_to_domain.get(tag.lower(), tag.lower())
                    if domain not in mapped_domains:
                        mapped_domains.append(domain)
                category_filter = mapped_domains if mapped_domains else None

            # Convert question type strings to enum values
            type_filter_enums = None
            if request.question_types:
                type_filter_enums = []
                for qt in request.question_types:
                    try:
                        # Handle both lowercase and uppercase enum values
                        type_filter_enums.append(QuestionType[qt.upper()])
                    except KeyError:
                        logger.warning(f"Unknown question type: {qt}")

            # Collect questions - use search if query provided, otherwise use standard collection
            if request.search_query:
                logger.info(f"Using search query: '{request.search_query}'")
                result = await runner.collect_from_search(
                    search_query=request.search_query,
                    count=request.count,
                    type_filter=type_filter_enums,
                    quality_requirements=quality,
                )
            else:
                logger.info("No search query provided, using standard collection")
                result = await runner.collect(
                    count=request.count,
                    type_filter=type_filter_enums,
                    category_filter=category_filter,
                    quality_requirements=quality,
                )

            if result.success:
                questions_list = result.questions
                logger.info(
                    f"Collected {len(questions_list)} questions from Polymarket"
                )
            else:
                error_msg = (
                    result.error_message
                    if hasattr(result, "error_message")
                    else str(result)
                )
                errors.append(f"Polymarket collection failed: {error_msg}")

        elif request.source == "news":
            # Initialize runner with required configurations
            from src.pipelines.collection import ArticleCollectionConfig, ArticleSource
            from src.config.pipeline import QuestionPipelineConfig
            from datetime import datetime, timedelta, timezone
            import yaml
            from pathlib import Path

            # Load article sources from config file
            sources_file = Path("config/sources.yaml")

            with open(sources_file, "r") as f:
                config_data = yaml.safe_load(f)
                article_sources = [
                    ArticleSource(**source_data)
                    for source_data in config_data.get("sources", [])
                ]

            logger.info(f"Loaded {len(article_sources)} article sources from config")

            # Filter sources by requested domains if specified
            if request.domains:
                filtered_sources = [
                    s for s in article_sources if s.domain in request.domains
                ]
                if filtered_sources:
                    article_sources = filtered_sources
                    logger.info(
                        f"Filtered to {len(article_sources)} sources matching domains: {request.domains}"
                    )

            if not article_sources:
                raise HTTPException(
                    status_code=400,
                    detail="No article sources available for the requested domains",
                )

            # Create default configurations
            # Collect articles from the past 7 days
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=7)

            article_config = ArticleCollectionConfig(
                sources=article_sources,
                start_date=start_date,
                end_date=end_date,
                max_articles_per_source=10,  # Limit for preview
            )

            question_config = QuestionPipelineConfig()

            # Get database path
            db_path = get_current_db_path()

            # Initialize runner
            runner = NewsBasedRunner(
                article_config=article_config,
                question_config=question_config,
                db_path=db_path,
            )

            # Create quality requirements
            quality = QualityRequirements()
            if request.min_difficulty:
                quality.min_difficulty = request.min_difficulty
            if request.max_difficulty:
                quality.max_difficulty = request.max_difficulty

            # Convert question type strings to enum values
            type_filter_enums = None
            if request.question_types:
                type_filter_enums = []
                for qt in request.question_types:
                    try:
                        type_filter_enums.append(QuestionType[qt.upper()])
                    except KeyError:
                        logger.warning(f"Unknown question type: {qt}")

            # Collect questions
            result = await runner.collect(
                count=request.count,
                type_filter=type_filter_enums,
                category_filter=request.domains,
                quality_requirements=quality,
            )

            if result.success:
                questions_list = result.questions
                logger.info(f"Collected {len(questions_list)} questions from news")
            else:
                error_msg = (
                    result.error_message
                    if hasattr(result, "error_message")
                    else str(result)
                )
                errors.append(f"News collection failed: {error_msg}")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {request.source}. Must be 'polymarket' or 'news'",
            )

        # Convert questions to dictionaries
        questions_dicts = []
        for q in questions_list:
            q_dict = {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type.value,
                "domain": q.domain.value,
                "difficulty": q.difficulty,
                "source": q.source,
                "target_event_id": q.target_event_id,
                "related_event_ids": q.related_event_ids,
                "quality_score": q.quality_score,
                "resolution_date": q.resolution_date.isoformat()
                if q.resolution_date
                else None,
                "resolution_criteria": q.resolution_criteria,
                "ground_truth": q.ground_truth,
                "metadata": q.metadata,
            }
            questions_dicts.append(q_dict)

        return QuestionPreviewResponse(
            success=len(questions_list) > 0,
            questions=questions_dicts,
            total=len(questions_list),
            source=request.source,
            errors=errors,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to preview questions: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-save")
async def batch_save_questions(
    request: BatchSaveRequest,
    db: GenericDatabase = Depends(get_database),
):
    """Save selected questions to database.

    Args:
        request: Batch save request with question IDs and data
        db: Database instance

    Returns:
        Save result with statistics
    """
    try:
        logger.info(f"Batch saving {len(request.questions)} questions")

        saved_count = 0
        skipped_count = 0
        errors = []

        for q_dict in request.questions:
            try:
                # Reconstruct Question object from dict
                question = Question(
                    id=q_dict["id"],
                    question_text=q_dict["question_text"],
                    question_type=QuestionType[q_dict["question_type"].upper()],
                    domain=Domain[q_dict["domain"].upper()],
                    difficulty=q_dict["difficulty"],
                    source=q_dict["source"],
                    target_event_id=q_dict.get("target_event_id"),
                    related_event_ids=q_dict.get("related_event_ids", []),
                    quality_score=q_dict.get("quality_score"),
                    resolution_date=q_dict.get("resolution_date"),
                    resolution_criteria=q_dict.get("resolution_criteria"),
                    ground_truth=q_dict.get("ground_truth"),
                    metadata=q_dict.get("metadata", {}),
                )

                # Check if question already exists
                existing = db.get(Question, question.id)
                if existing:
                    logger.info(f"Skipping duplicate: {question.id}")
                    skipped_count += 1
                    continue

                # Save to database
                db.save(Question, question)
                saved_count += 1

            except Exception as e:
                logger.error(f"Error saving question {q_dict.get('id')}: {e}")
                errors.append(f"Question {q_dict.get('id')}: {str(e)}")

        logger.info(
            f"Batch save complete: {saved_count} saved, {skipped_count} skipped, {len(errors)} errors"
        )

        return {
            "success": saved_count > 0,
            "saved_count": saved_count,
            "skipped_count": skipped_count,
            "total_requested": len(request.questions),
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Failed to batch save questions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[QuestionListItem])
async def get_questions(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    db: GenericDatabase = Depends(get_database),
):
    """Get all questions with optional filtering.

    Args:
        domain: Optional domain filter

    Returns:
        List of questions
    """
    try:
        # Get all questions
        filters = {}
        if domain:
            filters["domain"] = domain

        questions = db.get_many(Question, filters=filters if filters else None)

        # Get article counts efficiently
        from src.domain.models import Article

        article_counts = db.count_group_by(Article, "collected_for_question_id")

        # Evidence completion status via monitor service (single source of truth)
        monitor_service = QuestionMonitorService(db)
        processed_question_ids = monitor_service.get_processed_question_ids(questions)

        # Get all forecasts and aggregate by question
        from src.domain.models.forecast import Forecast

        all_forecasts = db.get_many(Forecast)
        forecast_stats = {}  # qid -> {'count': int, 'modes': set}

        for f in all_forecasts:
            if not f.question_id:
                continue

            if f.question_id not in forecast_stats:
                forecast_stats[f.question_id] = {"count": 0, "modes": set()}

            stats = forecast_stats[f.question_id]
            stats["count"] += 1
            if f.mode:
                # Handle enum or string mode
                mode_val = f.mode.value if hasattr(f.mode, "value") else str(f.mode)
                stats["modes"].add(mode_val)

        # Convert to simplified response model with article counts and forecast stats
        result = [
            QuestionListItem(
                id=q.id,
                question_text=q.question_text,
                question_type=q.question_type.value,
                domain=q.domain.value,
                difficulty=q.difficulty,
                source=q.source,
                target_event_id=q.target_event_id,
                related_event_ids=q.related_event_ids,
                quality_score=q.quality_score,
                resolution_date=q.resolution_date.isoformat()
                if q.resolution_date
                else None,
                estimated_start_time=q.estimated_start_time.isoformat()
                if q.estimated_start_time
                else None,
                ground_truth=q.ground_truth,
                causal_explanation=q.causal_explanation,
                metadata=q.metadata,
                article_count=article_counts.get(q.id, 0),
                graph_built=q.graph_built,
                forecast_count=forecast_stats.get(q.id, {}).get("count", 0),
                forecast_modes=list(forecast_stats.get(q.id, {}).get("modes", [])),
                evidence_satisfied=q.id in processed_question_ids,
            )
            for q in questions
        ]

        logger.info(f"Returning {len(result)} questions")
        return result

    except Exception as e:
        logger.error(f"Failed to fetch questions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}", response_model=QuestionListItem)
async def get_question(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get a single question by ID.

    Args:
        question_id: Question identifier

    Returns:
        Question data
    """
    try:
        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        return QuestionListItem(
            id=question.id,
            question_text=question.question_text,
            question_type=question.question_type.value,
            domain=question.domain.value,
            difficulty=question.difficulty,
            source=question.source,
            target_event_id=question.target_event_id,
            related_event_ids=question.related_event_ids,
            quality_score=question.quality_score,
            resolution_date=question.resolution_date.isoformat()
            if question.resolution_date
            else None,
            ground_truth=question.ground_truth,
            causal_explanation=question.causal_explanation,
            metadata=question.metadata,
            estimated_start_time=question.estimated_start_time.isoformat()
            if question.estimated_start_time
            else None,
            evidence_satisfied=QuestionMonitorService(db)
            .check_satisfaction(question.id)
            .is_satisfied,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch question: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/events")
async def get_question_events(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get all events related to a question.

    This includes:
    - target_event_id from the question
    - related_event_ids from the question
    - All events extracted during evidence collection (via metadata)
    - All events from causal hypotheses discovered by this question

    Args:
        question_id: Question identifier

    Returns:
        Event IDs and statistics
    """
    try:
        from src.domain.models import Event

        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Start with events directly referenced by question
        event_ids = set()
        if question.outcome_event_ids:
            event_ids.update(question.outcome_event_ids)
        if question.target_event_id:  # Legacy fallback
            event_ids.add(question.target_event_id)
        event_ids.update(question.related_event_ids)

        direct_event_count = len(event_ids)

        # Find all events extracted during evidence collection
        # Use explicit provenance field with fallback to metadata
        all_events = db.get_many(Event)
        extracted_events = set()
        for event in all_events:
            # Check explicit provenance field first
            if event.extracted_for_question_id == question_id:
                extracted_events.add(event.id)
                event_ids.add(event.id)
            # Fallback to metadata for pre-migration data
            elif (
                event.metadata.get("related_question_ids")
                and question_id in event.metadata["related_question_ids"]
            ):
                extracted_events.add(event.id)
                event_ids.add(event.id)

        # Find all causal hypotheses discovered by this question
        all_hypotheses = db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses if question_id in h.discovered_by_question_ids
        ]

        # Extract all source and target events from these hypotheses
        hypothesis_events = set()
        for hypothesis in question_hypotheses:
            hypothesis_events.add(hypothesis.source_event_id)
            hypothesis_events.add(hypothesis.target_event_id)
            event_ids.add(hypothesis.source_event_id)
            event_ids.add(hypothesis.target_event_id)

        # Calculate orphaned events (extracted but not in hypotheses)
        orphaned_events = extracted_events - hypothesis_events

        logger.info(
            f"Question {question_id}: "
            f"{direct_event_count} direct events, "
            f"{len(extracted_events)} extracted during evidence, "
            f"{len(hypothesis_events)} in hypotheses, "
            f"{len(orphaned_events)} orphaned, "
            f"{len(event_ids)} total events"
        )

        return {
            "question_id": question_id,
            "event_ids": list(event_ids),
            "total_events": len(event_ids),
            "direct_events": direct_event_count,
            "extracted_events": len(extracted_events),
            "hypothesis_events": len(hypothesis_events),
            "orphaned_events": len(orphaned_events),
            "hypotheses_count": len(question_hypotheses),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch question events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{question_id}/events/review")
async def review_question_events(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Review all events for a question using EventReviewService.
    
    Args:
        question_id: Question identifier
        
    Returns:
        EventReviewReport
    """
    try:
        from src.services.event_review_service import EventReviewService
        
        # Verify question exists
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        service = EventReviewService(db)
        report = await service.review_events_for_question(question_id)
        
        return report

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Review question events failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/forecasts")
async def get_question_forecasts(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get all forecasts for a question.

    Args:
        question_id: Question identifier

    Returns:
        List of forecasts for this question
    """
    try:
        from src.domain.models.forecast import Forecast

        # Verify question exists
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Get all forecasts for this question
        forecasts = db.get_many(Forecast, filters={"question_id": question_id})

        # Sort by timestamp (most recent first) - handle both timestamp and created_at
        forecasts.sort(
            key=lambda f: getattr(
                f, "timestamp", getattr(f, "created_at", datetime.min)
            ),
            reverse=True,
        )

        # Convert to dicts
        forecasts_data = []

        def _coerce_bool(value: Any) -> Optional[bool]:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"yes", "true", "1"}:
                    return True
                if normalized in {"no", "false", "0"}:
                    return False
            return None

        for f in forecasts:
            # Get timestamp - try timestamp first, fall back to created_at
            ts = getattr(f, "timestamp", getattr(f, "created_at", None))

            # Compute is_correct on the fly if not already evaluated
            is_correct = getattr(f, "is_correct", None)
            if is_correct is None and question.ground_truth is not None:
                prediction_bool = _coerce_bool(f.prediction)
                ground_truth_bool = _coerce_bool(question.ground_truth)

                if prediction_bool is not None and ground_truth_bool is not None:
                    is_correct = prediction_bool == ground_truth_bool
                elif f.prediction is not None:
                    is_correct = (
                        str(f.prediction).strip().lower()
                        == str(question.ground_truth).strip().lower()
                    )

            # Compute probability of "Yes/True" outcome
            raw_prob = getattr(f, "probability", None)
            if raw_prob is not None:
                probability = raw_prob
            elif isinstance(f.prediction, bool):
                # prediction=True means model says "Yes"; probability of Yes = confidence
                # prediction=False means model says "No"; probability of Yes = 1 - confidence
                probability = f.confidence if f.prediction else (1.0 - f.confidence)
            elif isinstance(f.prediction, (int, float)):
                probability = float(f.prediction)
            else:
                probability = None

            # Human-readable prediction label
            if isinstance(f.prediction, bool):
                expected_outcome = "Yes" if f.prediction else "No"
            else:
                expected_outcome = str(f.prediction) if f.prediction is not None else None

            # Extract reasoning metrics written back by evaluate_reasoning_graphs.py
            import json as _json
            eval_meta_raw = getattr(f, "evaluation_metadata", None)
            try:
                eval_meta = _json.loads(eval_meta_raw) if isinstance(eval_meta_raw, str) else (eval_meta_raw or {})
            except (ValueError, TypeError):
                eval_meta = {}
            reasoning_eval = eval_meta.get("reasoning_eval", {})

            forecast_dict = {
                "id": f.id,
                "question_id": f.question_id,
                "probability": probability,
                "confidence": f.confidence,
                "expected_outcome": expected_outcome,
                "reasoning": f.reasoning,
                "mode": f.mode.value
                if hasattr(f.mode, "value")
                else str(f.mode)
                if f.mode
                else "container",
                # Outcome metrics
                "is_correct": is_correct,
                "brier_score": getattr(f, "brier_score", None),
                "log_score": getattr(f, "log_score", None),
                # Reasoning graph metrics (present after evaluate_reasoning_graphs.py runs)
                "event_f1": reasoning_eval.get("event_f1"),
                "event_recall": reasoning_eval.get("event_recall"),
                "event_precision": reasoning_eval.get("event_precision"),
                "accessible_event_f1": reasoning_eval.get("accessible_event_f1"),
                "exact_source_precision": reasoning_eval.get("exact_source_precision"),
                "key_event_recall": reasoning_eval.get("key_event_recall"),
                "key_event_precision": reasoning_eval.get("key_event_precision"),
                "temporal_mae_days": reasoning_eval.get("temporal_mae_days"),
                "market_signal_recall": reasoning_eval.get("market_signal_recall"),
                "edge_recall": reasoning_eval.get("edge_recall"),
                "edge_precision": reasoning_eval.get("edge_precision"),
                # Context
                "simulated_date": f.simulated_date.isoformat() if getattr(f, "simulated_date", None) else None,
                "model_name": getattr(f, "model_name", None),
                "model_version": getattr(f, "model_version", None),
                "articles_accessed_count": len(getattr(f, "articles_accessed", []) or []),
                "enabled_tools": getattr(f, "enabled_tools", []),
                "db": getattr(f, "db", None),
                "session_id": f.session_id,
                "created_at": ts.isoformat() if ts else None,
            }
            forecasts_data.append(forecast_dict)

        logger.info(
            f"Returning {len(forecasts_data)} forecasts for question {question_id}"
        )

        return {
            "question_id": question_id,
            "forecasts": forecasts_data,
            "total": len(forecasts_data),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch forecasts: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/price_history")
async def get_question_price_history(
    question_id: str,
    interval: str = Query(
        "1d", description="Time interval: 1m, 1w, 1d, 6h, 1h, or max"
    ),
    include_turning_points: bool = Query(
        False, description="Include detected turning points in response"
    ),
    min_turning_point_change: float = Query(
        5.0,
        description="Minimum change (percentage points) for turning point detection",
    ),
    db: GenericDatabase = Depends(get_database),
):
    """Get price history for a Polymarket question.

    This endpoint fetches historical market prices from Polymarket's CLOB API
    for questions that originated from Polymarket.

    Args:
        question_id: Question identifier (must be a Polymarket question)
        interval: Time interval for price data (1m, 1w, 1d, 6h, 1h, or max)
        include_turning_points: If True, analyze and include turning points
        min_turning_point_change: Minimum change for turning point detection

    Returns:
        Dict with price history for each outcome token:
        {
            "question_id": str,
            "market_id": str,
            "interval": str,
            "price_history": {
                "token_id": [{"t": timestamp_ms, "p": price_0_to_1}, ...],
                ...
            },
            "outcomes": [str, ...],  # Outcome labels for each token
            "turning_points": [...],  # Only if include_turning_points=True
            "sharp_movements": [...],  # Only if include_turning_points=True
            "curve_summary": {...}    # Only if include_turning_points=True
        }
    """
    try:
        logger.info(f"Fetching question {question_id} for price history")
        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        logger.info(f"Question loaded, source={question.source}")

        # Check if this is a Polymarket question
        if question.source != "polymarket":
            raise HTTPException(
                status_code=400,
                detail=f"Price history only available for Polymarket questions (source={question.source})",
            )

        # Extract data from metadata
        metadata = question.metadata or {}
        clob_token_ids = metadata.get("clob_token_ids", [])

        if not clob_token_ids:
            raise HTTPException(
                status_code=404, detail="No CLOB token IDs available for this question"
            )

        logger.info(f"Found {len(clob_token_ids)} CLOB token IDs")

        # Calculate timestamp range from question metadata
        # Use estimated_start_time or start_date as start, and resolution_date as end
        start_ts = None
        end_ts = None

        if question.estimated_start_time:
            start_ts = int(question.estimated_start_time.timestamp())
        elif metadata.get("start_date"):
            from src.utils.date_utils import parse_iso_datetime

            start_dt = parse_iso_datetime(metadata["start_date"])
            start_ts = int(start_dt.timestamp())

        if question.resolution_date:
            end_ts = int(question.resolution_date.timestamp())

        logger.info(
            f"Calculated time range: start_ts={start_ts}, end_ts={end_ts}"
            f"{f' (start: {question.estimated_start_time})' if question.estimated_start_time else ''}"
            f" (end: {question.resolution_date})"
        )

        # Fetch price history for all tokens
        # Strategy:
        # - For 'all' or 'max': Use interval-based API to get full history
        # - For specific intervals ('1h', '6h', '1d', '1w'): Calculate appropriate time range

        if interval in ["all", "max"]:
            # Get full history using interval-based API
            from src.integrations.polymarket import get_price_history_for_market
            price_history = await get_price_history_for_market(
                clob_token_ids,
                interval=interval,
                fidelity=720,  # Higher fidelity for full history
            )
        else:
            # For specific intervals, calculate time range to display
            from datetime import datetime, timezone

            # Map intervals to days
            interval_to_days = {
                "1h": 1 / 24,  # Last 1 hour
                "6h": 0.25,  # Last 6 hours
                "1d": 1,  # Last 1 day
                "1w": 7,  # Last 1 week
            }

            days = interval_to_days.get(interval, 1)

            # Use resolution_date as the end time (or now for unresolved questions)
            if end_ts:
                interval_end_ts = end_ts
            else:
                interval_end_ts = int(datetime.now(timezone.utc).timestamp())

            # Calculate start time by subtracting the interval duration
            interval_start_ts = int(interval_end_ts - (days * 86400))

            # Clamp to question's start time if available
            if start_ts and interval_start_ts < start_ts:
                interval_start_ts = start_ts

            logger.info(
                f"Using custom interval '{interval}': "
                f"start={interval_start_ts}, end={interval_end_ts}, "
                f"range={(interval_end_ts - interval_start_ts) / 86400:.2f} days"
            )

            # Use timestamp-based API for custom intervals
            from src.integrations.polymarket import get_price_history_for_market
            price_history = await get_price_history_for_market(
                clob_token_ids,
                interval="all",  # Not used when timestamps provided
                start_ts=interval_start_ts,
                end_ts=interval_end_ts,
                fidelity=30,  # Lower fidelity for short ranges
            )

        if not price_history:
            logger.warning(f"No price history found for question {question_id}")

        # Get outcome labels and market ID from metadata
        options = metadata.get("options", ["Yes", "No"])
        market_id = metadata.get("market_id")

        # Map token IDs explicitly to their options
        token_outcomes = {}
        for i, token_id in enumerate(clob_token_ids):
            if i < len(options):
                token_outcomes[token_id] = options[i]
            else:
                token_outcomes[token_id] = f"Option {i+1}"

        logger.info(
            f"Fetched price history for question {question_id}: "
            f"{len(price_history)} tokens, {sum(len(h) for h in price_history.values())} total points"
        )

        response = {
            "question_id": question_id,
            "market_id": market_id,
            "interval": interval,
            "price_history": price_history,
            "outcomes": options,
            "token_outcomes": token_outcomes,
        }

        # Optionally include turning points analysis
        if include_turning_points and price_history:
            from src.integrations.polymarket import analyze_price_curve

            # Analyze the first token (primary outcome)
            first_token_id = clob_token_ids[0]
            primary_history = price_history.get(first_token_id, [])

            if primary_history:
                analysis = analyze_price_curve(
                    primary_history,
                    min_turning_point_change=min_turning_point_change,
                    min_sharp_movement_change=min_turning_point_change * 2,
                )
                response["turning_points"] = analysis["turning_points"]
                response["sharp_movements"] = analysis["sharp_movements"]
                response["lead_changes"] = analysis["lead_changes"]
                response["curve_summary"] = analysis["summary"]

                logger.info(
                    f"Included price analysis: "
                    f"{len(analysis['turning_points'])} turning points, "
                    f"{len(analysis['sharp_movements'])} sharp movements, "
                    f"{len(analysis['lead_changes'])} lead changes"
                )

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Failed to fetch price history: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/price_turning_points")
async def get_price_turning_points(
    question_id: str,
    min_change_pct: float = Query(
        5.0, description="Minimum price change for turning points (percentage points)"
    ),
    create_events: bool = Query(
        False, description="Create Event records from turning points"
    ),
    db: GenericDatabase = Depends(get_database),
):
    """Detect and return major turning points in the market price curve.

    Turning points are local maxima/minima where price reversed direction
    significantly. These often correspond to important market-moving events.

    Args:
        question_id: Question identifier (must be a Polymarket question)
        min_change_pct: Minimum price change to qualify as turning point (default: 5%)
        create_events: If True, creates Event records for each turning point

    Returns:
        {
            "question_id": str,
            "turning_points": [...],  # Detected turning points
            "sharp_movements": [...],  # Rapid price changes
            "summary": {...},  # Overall curve statistics
            "created_events": [...],  # Event IDs if create_events=True
        }
    """
    from src.integrations.polymarket import (
        analyze_price_curve,
        get_price_history_for_market,
    )
    from src.domain.models import Event

    try:
        logger.info(f"Analyzing price curve for question {question_id}")
        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        if question.source != "polymarket":
            raise HTTPException(
                status_code=400,
                detail=f"Price analysis only available for Polymarket questions (source={question.source})",
            )

        metadata = question.metadata or {}
        clob_token_ids = metadata.get("clob_token_ids", [])

        if not clob_token_ids:
            raise HTTPException(
                status_code=404, detail="No CLOB token IDs available for this question"
            )

        # Fetch full price history
        price_history = await get_price_history_for_market(
            clob_token_ids,
            interval="max",
            fidelity=720,
        )

        if not price_history:
            return {
                "question_id": question_id,
                "turning_points": [],
                "sharp_movements": [],
                "summary": None,
                "created_events": [],
            }

        # Analyze the first token (primary outcome, usually "Yes")
        first_token_id = clob_token_ids[0]
        primary_history = price_history.get(first_token_id, [])

        if not primary_history:
            return {
                "question_id": question_id,
                "turning_points": [],
                "sharp_movements": [],
                "summary": None,
                "created_events": [],
            }

        # Run analysis
        analysis = analyze_price_curve(
            primary_history,
            min_turning_point_change=min_change_pct,
            min_sharp_movement_change=min_change_pct
            * 2,  # Sharp movements need bigger change
        )

        created_event_ids = []

        # Optionally create Event records from turning points
        if create_events and analysis["turning_points"]:
            from datetime import datetime, timezone
            from src.domain.models.event import EventType, EventStatus
            import uuid

            options = metadata.get("options", ["Yes", "No"])
            primary_outcome = options[0] if options else "Yes"

            for tp in analysis["turning_points"][:10]:  # Limit to top 10
                event_time = datetime.fromtimestamp(tp["timestamp"], tz=timezone.utc)

                # Generate event title based on turning point type
                if tp["type"] == "peak":
                    title = f"Market peak: {primary_outcome} reached {tp['price'] * 100:.1f}%"
                    description = (
                        f"Market probability for '{primary_outcome}' peaked at {tp['price'] * 100:.1f}%, "
                        f"rising {tp['change_before']:.1f}pp before reversing down {abs(tp['change_after']):.1f}pp. "
                        f"This turning point suggests a shift in market sentiment."
                    )
                else:
                    title = f"Market trough: {primary_outcome} dropped to {tp['price'] * 100:.1f}%"
                    description = (
                        f"Market probability for '{primary_outcome}' reached a low of {tp['price'] * 100:.1f}%, "
                        f"dropping {abs(tp['change_before']):.1f}pp before recovering {tp['change_after']:.1f}pp. "
                        f"This turning point suggests a shift in market sentiment."
                    )

                event = Event(
                    id=str(uuid.uuid4()),
                    title=title,
                    description=description,
                    occurred_date=event_time,
                    event_type=EventType.INDICATOR,
                    domain=question.domain,
                    status=EventStatus.OCCURRED,
                    extracted_for_question_id=question_id,
                    metadata={
                        "turning_point_type": tp["type"],
                        "price": tp["price"],
                        "change_before": tp["change_before"],
                        "change_after": tp["change_after"],
                        "significance": tp["significance"],
                        "auto_detected": True,
                        "source": "polymarket_price_analysis",
                    },
                )

                db.save(Event, event)
                created_event_ids.append(event.id)
                logger.info(
                    f"Created turning point event: {event.id} ({tp['type']} at {event_time})"
                )

        logger.info(
            f"Price analysis complete for {question_id}: "
            f"{len(analysis['turning_points'])} turning points, "
            f"{len(analysis['sharp_movements'])} sharp movements"
        )

        return {
            "question_id": question_id,
            "turning_points": analysis["turning_points"],
            "sharp_movements": analysis["sharp_movements"],
            "summary": analysis["summary"],
            "created_events": created_event_ids,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Failed to analyze price curve: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/article_coverage")
async def get_article_coverage(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get article coverage analysis for a question.

    Analyzes the collected articles for this question, including:
    - Timeline distribution and gaps
    - Source diversity metrics
    - Coverage quality score
    - Recommendations for improvement

    Args:
        question_id: Question identifier

    Returns:
        Complete article coverage analysis with timeline, sources, gaps, and quality metrics
    """
    try:
        logger.info(f"Fetching article coverage for question {question_id}")

        # Get question for resolution date
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Get articles for this question and filter by time window
        from src.services.temporal_filter_service import TemporalFilterService
        from src.utils.date_utils import ensure_timezone_aware

        all_articles = db.get_many(Article)
        all_question_articles = [
            a for a in all_articles if a.collected_for_question_id == question_id
        ]

        # Track filtering stats for transparency
        q_resolution = ensure_timezone_aware(question.resolution_date)
        q_start = (
            ensure_timezone_aware(question.estimated_start_time)
            if question.estimated_start_time
            else None
        )

        excluded_before_start = []
        excluded_after_resolution = []

        for article in all_question_articles:
            if not article.published_date:
                continue
            apd = ensure_timezone_aware(article.published_date)

            if apd >= q_resolution:
                excluded_after_resolution.append(
                    {
                        "id": article.id,
                        "title": article.title,
                        "published_date": apd.isoformat(),
                        "source": article.source,
                        "reason": "after_resolution",
                    }
                )
            elif q_start and apd < q_start:
                excluded_before_start.append(
                    {
                        "id": article.id,
                        "title": article.title,
                        "published_date": apd.isoformat(),
                        "source": article.source,
                        "reason": "before_market_start",
                    }
                )

        # Filter by time window using shared utility
        window_start, window_end = TemporalFilterService.get_evidence_window(
            question.resolution_date,
            question.estimated_start_time,
        )
        question_articles = TemporalFilterService.filter_by_window(
            all_question_articles, window_start, window_end
        )

        logger.info(
            f"Found {len(question_articles)} valid articles for question {question_id} "
            f"({len(all_question_articles)} collected, "
            f"{len(excluded_before_start)} before start, "
            f"{len(excluded_after_resolution)} after resolution)"
        )

        if not question_articles:
            # Return empty analysis with filtering stats
            return {
                "question_id": question_id,
                "article_count": 0,  # Valid articles in range
                "total_articles_collected": len(all_question_articles),
                "articles_excluded_before_start": len(excluded_before_start),
                "articles_excluded_after_resolution": len(excluded_after_resolution),
                "excluded_articles": {
                    "before_start": excluded_before_start,
                    "after_resolution": excluded_after_resolution,
                },
                "timeline": {
                    "has_dates": False,
                    "resolution_date": question.resolution_date.isoformat(),
                },
                "sources": {
                    "unique_sources": 0,
                    "unique_domains": 0,
                    "source_counts": {},
                    "top_sources": [],
                },
                "gaps": [],
                "quality": {
                    "score": 0.0,
                    "volume_score": 0.0,
                    "diversity_score": 0.0,
                    "coverage_score": 0.0,
                    "distribution_score": 0.0,
                    "gap_severity": 0.0,
                },
                "recommendation": "No valid articles in time window. "
                + (
                    f"{len(all_question_articles)} articles collected but excluded (see excluded_articles)."
                    if all_question_articles
                    else "Start evidence collection with web_search and article_collector."
                ),
            }

        # Perform complete analysis using shared utilities
        analysis = analyze_article_coverage(
            question_articles, question.resolution_date, question.estimated_start_time
        )

        # Convert datetime objects to ISO format for JSON serialization
        if analysis["timeline"].get("has_dates"):
            analysis["timeline"]["earliest"] = analysis["timeline"][
                "earliest"
            ].isoformat()
            analysis["timeline"]["resolution_date"] = analysis["timeline"][
                "resolution_date"
            ].isoformat()
            # Convert dates in gaps
            for gap in analysis["gaps"]:
                gap["start"] = gap["start"].isoformat()
                gap["end"] = gap["end"].isoformat()
        else:
            analysis["timeline"]["resolution_date"] = analysis["timeline"][
                "resolution_date"
            ].isoformat()

        # Add question_id and filtering stats to response
        analysis["question_id"] = question_id
        analysis["total_articles_collected"] = len(all_question_articles)
        analysis["articles_excluded_before_start"] = len(excluded_before_start)
        analysis["articles_excluded_after_resolution"] = len(excluded_after_resolution)
        analysis["excluded_articles"] = {
            "before_start": excluded_before_start,
            "after_resolution": excluded_after_resolution,
        }

        logger.info(
            f"Article coverage for question {question_id}: "
            f"{analysis['article_count']} valid articles "
            f"({len(all_question_articles)} total collected, "
            f"{len(excluded_before_start)} excluded before start, "
            f"{len(excluded_after_resolution)} excluded after resolution), "
            f"quality score {analysis['quality']['score']:.2f}"
        )

        return analysis

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Failed to fetch article coverage: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/causal_path")
async def get_causal_path_analysis(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get causal path analysis for a question's target event.

    Analyzes all causal paths leading to the target event, including:
    - Path statistics (length, completion ratio)
    - Event status (confirmed vs predicted)
    - Path direction and strength
    - Per-event path information

    Args:
        question_id: Question identifier

    Returns:
        Causal path analysis with statistics and event-level details
    """
    try:
        from src.services.causal_path_analyzer import CausalPathAnalyzer

        logger.info(f"Analyzing causal paths for question {question_id}")

        # Get question
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Check if question has a target event
        from src.analysis.graph_analysis import resolve_target_event_id

        resolved = resolve_target_event_id(question, db)
        if not resolved:
            return {
                "question_id": question_id,
                "has_target_event": False,
                "message": "Question has no target event",
            }

        # Analyze paths to target
        analyzer = CausalPathAnalyzer(db)
        analysis = analyzer.analyze_paths_to_target(
            target_event_id=resolved, max_depth=10, max_paths=20
        )

        # Get path statistics
        stats = analysis.get_path_statistics()

        # Get all paths details
        all_paths_details = []
        for path in analysis.paths:
            path_events = []
            for node in path:
                path_events.append(
                    {
                        "event_id": node.event_id,
                        "title": node.event.title,
                        "status": node.event.status.value,
                        "occurred_date": node.event.occurred_date.isoformat()
                        if node.event.occurred_date
                        else None,
                        "depth": node.depth,
                        "edge_from_parent": {
                            "relation_type": node.edge_from_parent.relation_type.value
                            if node.edge_from_parent
                            else None,
                            "strength": node.edge_from_parent.strength
                            if node.edge_from_parent
                            else None,
                            "confidence": node.edge_from_parent.confidence
                            if node.edge_from_parent
                            else None,
                        }
                        if node.edge_from_parent
                        else None,
                    }
                )
            all_paths_details.append(path_events)

        # Get related event IDs for this question
        event_ids = list(analysis.all_events_in_paths)
        if question.related_event_ids:
            event_ids.extend(question.related_event_ids)
        event_ids = list(set(event_ids))  # Deduplicate

        # Get path information for each event
        event_path_info = analyzer.get_path_for_events(event_ids, resolved)

        logger.info(
            f"Found {stats['total_paths']} paths to target, "
            f"{stats['confirmed_events']}/{stats['total_events']} events confirmed"
        )

        return {
            "question_id": question_id,
            "target_event_id": resolved,
            "has_target_event": True,
            "statistics": stats,
            "paths": all_paths_details,
            "event_path_info": event_path_info,
            "all_events_in_paths": list(analysis.all_events_in_paths),
            "confirmed_events": list(analysis.confirmed_event_ids),
            "predicted_events": list(analysis.predicted_event_ids),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze causal paths: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


class QuestionUpdateRequest(BaseModel):
    """Request to update a question."""

    question_text: Optional[str] = None
    question_type: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    difficulty: Optional[int] = Field(None, ge=1, le=5)
    resolution_date: Optional[datetime] = None
    estimated_start_time: Optional[datetime] = None
    resolution_criteria: Optional[str] = None
    resolution_reasoning: Optional[str] = None
    context: Optional[str] = None
    ground_truth: Optional[Any] = None
    target_event_id: Optional[str] = None
    outcome_event_ids: Optional[List[str]] = None
    related_event_ids: Optional[List[str]] = None
    related_article_ids: Optional[List[str]] = None
    options: Optional[List[str]] = None
    quantity_unit: Optional[str] = None
    quantity_bounds: Optional[Dict[str, float]] = None
    metadata: Optional[Dict[str, Any]] = None


@router.put("/{question_id}")
async def update_question(
    question_id: str,
    request: QuestionUpdateRequest,
    db: GenericDatabase = Depends(get_database),
):
    """Update a question.

    Args:
        question_id: Question identifier
        request: Fields to update
        db: Database instance

    Returns:
        Updated question data
    """
    try:
        logger.info(f"Updating question {question_id}")

        # Get existing question
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Update fields if provided
        if request.question_text is not None:
            question.question_text = request.question_text
        if request.question_type is not None:
            qtype = request.question_type.lower()
            legacy_qtype_map = {
                "multiple_choice": "mcq",
                "numeric": "quantity",
                "date": "timeframe",
            }
            question.question_type = QuestionType(legacy_qtype_map.get(qtype, qtype))
        if request.domain is not None:
            domain_value = request.domain.lower()
            legacy_domain_map = {
                "technology": "tech",
            }
            question.domain = Domain(legacy_domain_map.get(domain_value, domain_value))
        if request.source is not None:
            question.source = request.source
        if request.difficulty is not None:
            question.difficulty = request.difficulty
        if request.resolution_date is not None:
            question.resolution_date = request.resolution_date
        if request.estimated_start_time is not None:
            question.estimated_start_time = request.estimated_start_time
        if request.resolution_criteria is not None:
            question.resolution_criteria = request.resolution_criteria
        if request.resolution_reasoning is not None:
            question.resolution_reasoning = request.resolution_reasoning
        if request.context is not None:
            question.context = request.context
        if request.ground_truth is not None:
            question.ground_truth = request.ground_truth
        if request.target_event_id is not None:
            question.target_event_id = request.target_event_id
        if request.outcome_event_ids is not None:
            question.outcome_event_ids = request.outcome_event_ids
        if request.related_event_ids is not None:
            question.related_event_ids = request.related_event_ids
        if request.related_article_ids is not None:
            question.related_article_ids = request.related_article_ids
        if request.options is not None:
            question.options = request.options
        if request.quantity_unit is not None:
            question.quantity_unit = request.quantity_unit
        if request.quantity_bounds is not None:
            question.quantity_bounds = request.quantity_bounds
        if request.metadata is not None:
            question.metadata = request.metadata

        # Save updated question
        db.save(Question, question)
        logger.info(f"Successfully updated question {question_id}")

        # Return updated question
        return QuestionListItem(
            id=question.id,
            question_text=question.question_text,
            question_type=question.question_type.value,
            domain=question.domain.value,
            difficulty=question.difficulty,
            source=question.source,
            target_event_id=question.target_event_id,
            related_event_ids=question.related_event_ids,
            quality_score=question.quality_score,
            resolution_date=question.resolution_date.isoformat()
            if question.resolution_date
            else None,
            estimated_start_time=question.estimated_start_time.isoformat()
            if question.estimated_start_time
            else None,
            causal_explanation=question.causal_explanation,
            metadata=question.metadata,
            evidence_satisfied=QuestionMonitorService(db)
            .check_satisfaction(question.id)
            .is_satisfied,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update question: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{question_id}")
async def delete_question(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Delete a question.

    Args:
        question_id: Question identifier
        db: Database instance

    Returns:
        Success confirmation
    """
    try:
        logger.info(f"Deleting question {question_id}")

        # Check if question exists
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Delete the question
        db.delete(Question, question_id)
        logger.info(f"Successfully deleted question {question_id}")

        return {
            "success": True,
            "message": f"Question {question_id} deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete question: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/articles")
async def get_question_articles(
    question_id: str,
    db: GenericDatabase = Depends(get_database),
):
    """Get all articles collected for a specific question.

    Args:
        question_id: Question identifier

    Returns:
        List of articles collected for this question, sorted by date
    """
    try:
        from src.domain.models import Article

        # Verify question exists
        question = db.get(Question, question_id)
        if not question:
            raise HTTPException(
                status_code=404, detail=f"Question {question_id} not found"
            )

        # Get all articles for this question
        articles = db.get_many(
            Article, filters={"collected_for_question_id": question_id}
        )

        # Sort by published_date
        from datetime import timezone

        aware_min = datetime.min.replace(tzinfo=timezone.utc)
        articles.sort(key=lambda a: a.published_date or aware_min)

        logger.info(f"Found {len(articles)} articles for question {question_id}")
        return articles

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch question articles: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}/slot_preview")
async def get_question_slot_preview(
    question_id: str,
    slot: str = "mid",
    db: GenericDatabase = Depends(get_database),
):
    """Return the simulated date and evidence availability for a forecast slot.

    Args:
        question_id: Question identifier
        slot: Forecast slot — 'early', 'mid', or 'late' (default 'mid')

    Returns:
        dict with window_start, window_end, simulated_date, horizon_days, slot,
        evidence_count_at_date (articles published before simulated_date),
        total_evidence (all articles collected for this question).
    """
    from src.domain.models.question_helpers import ForecastSlot, get_forecast_date_for_slot
    from datetime import timezone

    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

    try:
        forecast_slot = ForecastSlot(slot)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid slot '{slot}'. Must be 'early', 'mid', or 'late'.",
        )

    try:
        setup = get_forecast_date_for_slot(question, slot=forecast_slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    simulated_date = setup["simulated_date"]
    if simulated_date.tzinfo is None:
        simulated_date = simulated_date.replace(tzinfo=timezone.utc)

    # Count articles collected for this question, and how many were available by simulated_date
    articles = db.get_many(Article, filters={"collected_for_question_id": question_id})
    total_evidence = len(articles)
    evidence_count_at_date = sum(
        1 for a in articles
        if a.published_date is not None
        and (
            a.published_date.replace(tzinfo=timezone.utc)
            if a.published_date.tzinfo is None
            else a.published_date
        ) <= simulated_date
    )

    return {
        "window_start": setup["window_start"].isoformat(),
        "window_end": setup["window_end"].isoformat(),
        "simulated_date": simulated_date.isoformat(),
        "horizon_days": setup["horizon_days"],
        "slot": setup["slot"],
        "evidence_count_at_date": evidence_count_at_date,
        "total_evidence": total_evidence,
    }
