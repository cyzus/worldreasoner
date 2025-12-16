"""Questions API endpoints.

Provides REST API for querying forecast questions.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends, Body
from pydantic import BaseModel, Field

from src.core.database import GenericDatabase
from src.domain.models import Question, CausalHypothesis
from src.domain.models.domain import Domain
from src.domain.models.question import QuestionType
from backend.api.routes.database import get_current_db_path
from src.utils.logging import logger
from src.utils.polymarket import get_price_history_for_market
from src.config.collection_goal import CollectionGoal, QualityRequirements
from src.config.pipeline import QuestionQualityConfig
from src.pipelines.question.orchestrator import (
    QuestionCollectionOrchestrator,
    OrchestratorConfig,
)


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
    metadata: Optional[Dict[str, Any]] = None


class PolymarketSearchRequest(BaseModel):
    """Request parameters for searching Polymarket."""
    query: str = Field(description="Search query term")
    limit_per_type: int = Field(default=20, ge=1, le=100, description="Results limit per content type (1-100)")
    events_tag: Optional[List[str]] = Field(default=None, description="Filter by event tags")
    keep_closed_markets: bool = Field(default=True, description="Include closed markets in results")


class PolymarketSearchResponse(BaseModel):
    """Response from Polymarket search."""
    success: bool
    events: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[Dict[str, Any]] = Field(default_factory=list)
    profiles: List[Dict[str, Any]] = Field(default_factory=list)
    total_events: int
    total_tags: int
    total_profiles: int


class QuestionPreviewRequest(BaseModel):
    """Request parameters for previewing questions from sources."""
    source: str = Field(description="Source to collect from: 'polymarket' or 'news'")
    count: int = Field(default=20, ge=1, le=100, description="Number of questions to fetch (1-100)")
    domains: Optional[List[str]] = Field(default=None, description="Filter by domains")
    question_types: Optional[List[str]] = Field(default=None, description="Filter by question types")
    min_difficulty: Optional[int] = Field(default=None, ge=1, le=5, description="Minimum difficulty (1-5)")
    max_difficulty: Optional[int] = Field(default=None, ge=1, le=5, description="Maximum difficulty (1-5)")
    tags: Optional[List[str]] = Field(default=None, description="Polymarket tags (e.g., 'politics', 'crypto')")
    include_resolved: Optional[bool] = Field(default=True, description="Include resolved markets (Polymarket only)")
    search_query: Optional[str] = Field(default=None, description="Search query for Polymarket markets (Polymarket only)")


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

        from src.pipelines.question.sources.polymarket_client import PolymarketClient

        client = PolymarketClient()
        results = await client.search_markets(
            query=request.query,
            limit_per_type=request.limit_per_type,
            events_tag=request.events_tag,
            keep_closed_markets=request.keep_closed_markets,
        )

        events = results.get("events", [])
        tags = results.get("tags", [])
        profiles = results.get("profiles", [])

        return PolymarketSearchResponse(
            success=len(events) > 0 or len(tags) > 0 or len(profiles) > 0,
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
        logger.info(f"Previewing questions from {request.source} (count={request.count})")

        # Initialize the appropriate source runner
        from src.pipelines.question.sources.markets import PolymarketRunner
        from src.pipelines.question.sources.news import NewsBasedRunner

        errors = []
        questions_list = []

        if request.source == "polymarket":
            # Create quality requirements
            quality = QualityRequirements()
            if request.min_difficulty:
                quality.min_difficulty = request.min_difficulty
            if request.max_difficulty:
                quality.max_difficulty = request.max_difficulty

            # Initialize runner with require_ground_truth based on include_resolved
            # require_ground_truth=True fetches resolved markets with ground truth
            # require_ground_truth=False fetches active prediction markets
            runner = PolymarketRunner(
                require_ground_truth=request.include_resolved if request.include_resolved is not None else True
            )

            # Map domains to tag-based category filter
            # If domains are specified, use them; otherwise if tags specified, map tags to domains
            category_filter = None
            if request.domains:
                category_filter = request.domains
            elif request.tags:
                # Map Polymarket tags to domains
                tag_to_domain = {
                    'politics': 'politics',
                    'geopolitics': 'politics',
                    'elections': 'politics',
                    'crypto': 'finance',
                    'finance': 'finance',
                    'economy': 'finance',
                    'sports': 'sports',
                    'tech': 'technology',
                    'ai': 'technology',
                    'pop culture': 'culture',
                    'entertainment': 'culture',
                    'science': 'science',
                    'business': 'business',
                    'health': 'health',
                    'pandemic': 'health',
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
                result = await runner.collect(
                    count=request.count,
                    type_filter=type_filter_enums,
                    category_filter=category_filter,
                    quality_requirements=quality,
                )

            if result.success:
                questions_list = result.questions
                logger.info(f"Collected {len(questions_list)} questions from Polymarket")
            else:
                error_msg = result.error_message if hasattr(result, 'error_message') else str(result)
                errors.append(f"Polymarket collection failed: {error_msg}")

        elif request.source == "news":
            # Initialize runner with required configurations
            from src.pipelines.stages import ArticleCollectionConfig, EventIdentificationConfig, ArticleSource
            from src.config.pipeline import QuestionPipelineConfig
            from datetime import datetime, timedelta, timezone
            import yaml
            from pathlib import Path

            # Load article sources from config file
            sources_file = Path("config/sources.yaml")

            with open(sources_file, 'r') as f:
                config_data = yaml.safe_load(f)
                article_sources = [ArticleSource(**source_data) for source_data in config_data.get('sources', [])]

            logger.info(f"Loaded {len(article_sources)} article sources from config")

            # Filter sources by requested domains if specified
            if request.domains:
                filtered_sources = [s for s in article_sources if s.domain in request.domains]
                if filtered_sources:
                    article_sources = filtered_sources
                    logger.info(f"Filtered to {len(article_sources)} sources matching domains: {request.domains}")

            if not article_sources:
                raise HTTPException(
                    status_code=400,
                    detail="No article sources available for the requested domains"
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

            event_config = EventIdentificationConfig(
                max_events_per_article=5,
            )

            question_config = QuestionPipelineConfig()

            # Get database path
            db_path = get_current_db_path()

            # Initialize runner
            runner = NewsBasedRunner(
                article_config=article_config,
                event_config=event_config,
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
                error_msg = result.error_message if hasattr(result, 'error_message') else str(result)
                errors.append(f"News collection failed: {error_msg}")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {request.source}. Must be 'polymarket' or 'news'"
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
                "resolution_date": q.resolution_date.isoformat() if q.resolution_date else None,
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

        logger.info(f"Batch save complete: {saved_count} saved, {skipped_count} skipped, {len(errors)} errors")

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
            filters['domain'] = domain

        questions = db.get_many(Question, filters=filters if filters else None)

        # Convert to simplified response model
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
                resolution_date=q.resolution_date.isoformat() if q.resolution_date else None,
                metadata=q.metadata,
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
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

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
            resolution_date=question.resolution_date.isoformat() if question.resolution_date else None,
            metadata=question.metadata,
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
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

        # Start with events directly referenced by question
        event_ids = set()
        if question.target_event_id:
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
            elif event.metadata.get('related_question_ids') and question_id in event.metadata['related_question_ids']:
                extracted_events.add(event.id)
                event_ids.add(event.id)

        # Find all causal hypotheses discovered by this question
        all_hypotheses = db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses
            if question_id in h.discovered_by_question_ids
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
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

        # Get all forecasts for this question
        forecasts = db.get_many(Forecast, filters={'question_id': question_id})

        # Sort by timestamp (most recent first) - handle both timestamp and created_at
        forecasts.sort(key=lambda f: getattr(f, 'timestamp', getattr(f, 'created_at', datetime.min)), reverse=True)

        # Convert to dicts
        forecasts_data = []
        for f in forecasts:
            # Get timestamp - try timestamp first, fall back to created_at
            ts = getattr(f, 'timestamp', getattr(f, 'created_at', None))
            forecast_dict = {
                'id': f.id,
                'question_id': f.question_id,
                'probability': getattr(f, 'probability', getattr(f, 'prediction', None)),
                'confidence': f.confidence,
                'reasoning': f.reasoning,
                'mode': f.mode.value if hasattr(f.mode, 'value') else str(f.mode) if f.mode else 'container',
                'db': getattr(f, 'db', None),
                'session_id': f.session_id,
                'created_at': ts.isoformat() if ts else None
            }
            forecasts_data.append(forecast_dict)

        logger.info(f"Returning {len(forecasts_data)} forecasts for question {question_id}")

        return {
            "question_id": question_id,
            "forecasts": forecasts_data,
            "total": len(forecasts_data)
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
    interval: str = Query("1d", description="Time interval: 1m, 1w, 1d, 6h, 1h, or max"),
    db: GenericDatabase = Depends(get_database),
):
    """Get price history for a Polymarket question.

    This endpoint fetches historical market prices from Polymarket's CLOB API
    for questions that originated from Polymarket.

    Args:
        question_id: Question identifier (must be a Polymarket question)
        interval: Time interval for price data (1m, 1w, 1d, 6h, 1h, or max)

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
            "outcomes": [str, ...]  # Outcome labels for each token
        }
    """
    try:
        logger.info(f"Fetching question {question_id} for price history")
        question = db.get(Question, question_id)

        if not question:
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

        logger.info(f"Question loaded, source={question.source}")

        # Check if this is a Polymarket question
        if question.source != "polymarket":
            raise HTTPException(
                status_code=400,
                detail=f"Price history only available for Polymarket questions (source={question.source})"
            )

        # Extract data from metadata
        metadata = question.metadata or {}
        clob_token_ids = metadata.get("clob_token_ids", [])

        if not clob_token_ids:
            raise HTTPException(
                status_code=404,
                detail="No CLOB token IDs available for this question"
            )

        logger.info(f"Found {len(clob_token_ids)} CLOB token IDs")

        # Fetch price history for all tokens
        price_history = await get_price_history_for_market(clob_token_ids, interval)

        if not price_history:
            logger.warning(f"No price history found for question {question_id}")

        # Get outcome labels and market ID from metadata
        options = metadata.get("options", ["Yes", "No"])
        market_id = metadata.get("market_id")

        logger.info(
            f"Fetched price history for question {question_id}: "
            f"{len(price_history)} tokens, {sum(len(h) for h in price_history.values())} total points"
        )

        return {
            "question_id": question_id,
            "market_id": market_id,
            "interval": interval,
            "price_history": price_history,
            "outcomes": options,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Failed to fetch price history: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
