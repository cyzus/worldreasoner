"""Temporal-aware MCP server for LLM forecasting.

This MCP server provides tools for LLMs to make forecasts while respecting
temporal constraints. All search and fetch operations are filtered based on
a simulated date to create realistic forecasting scenarios.

FORECASTING SIMULATION CONCEPT:
    The server uses TWO important dates to simulate realistic forecasting:

    1. X-Knowledge-Cutoff: The LLM's training data cutoff date
       - Represents when the LLM's training data ends
       - Example: 2024-01-01 for models trained in early 2024

    2. X-Simulated-Date: The simulated "today" date for the forecast
       - This is the date we're pretending "today" is
       - Must be AFTER the knowledge cutoff (LLM has been "deployed")
       - Must be BEFORE the question's resolution date
       - The LLM can access articles from before this date

    Timeline:
        Knowledge Cutoff → Simulated Date → Resolution Date
        (training ends)    (forecast "today") (answer known)

Example Scenario:
    - LLM's knowledge cutoff: 2024-01-01 (training data ends)
    - Simulated date: 2024-04-01 (we're pretending today is April 1st)
    - Question resolves on: 2024-06-01
    - LLM can access articles from: before 2024-04-01
    - LLM must forecast: 61 days into the future

The forecasting context is provided via MCP connection metadata/headers
when the client connects. This allows one server instance to handle
multiple forecasting sessions.

Exposed Tools (4 essential tools):
    1. get_question - Get the current forecast question details
    2. temporal_search_articles - Search articles before simulated date
    3. fetch_article - Fetch full article content (temporally filtered)
    4. submit_forecast - Submit prediction for the question

Server Mode:
    - stream: Streamable HTTP with Server-Sent Events (SSE)

Usage:
    # Start server
    python -m src.mcp_forecasting_server
    python -m src.mcp_forecasting_server --port 8110
    python -m src.mcp_forecasting_server --host 0.0.0.0 --port 8110

    # Client provides context via connection metadata:
    # X-Question-ID: q_123
    # X-Knowledge-Cutoff: 2024-01-01T00:00:00Z  (LLM's training cutoff)
    # X-Simulated-Date: 2024-04-01T00:00:00Z   (simulated "today")

Configuration:
    WORLDREASONER_DB: Path to database (default: worldreasoner.db)
"""

import os
import json
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any
from contextvars import ContextVar

from pydantic import BaseModel, Field
from fastmcp import FastMCP
from fastmcp.server import Context
from fastmcp.server.middleware import Middleware, MiddlewareContext

# Import WorldReasoner components
from src.core.database import GenericDatabase
from src.core.temporal_gateway import TemporalGateway, TemporalContext
from src.core.hybrid_search import HybridSearch
from src.domain.models import Article, Question, Forecast, Event, Domain
from src.utils.logging import logger
from src.utils.enums import parse_domain, enum_to_list
from src.utils.date_utils import parse_flexible_datetime

# Initialize MCP server
mcp = FastMCP("worldreasoner-forecasting")

# Global database connection and search engine
DB_PATH = os.getenv("WORLDREASONER_DB", "worldreasoner.db")
db: GenericDatabase = None  # Will be initialized in main()
hybrid_search: HybridSearch = None  # Will be initialized in main()

# Connection-level context storage (populated from request headers)
# Captured by middleware during any request with the headers
_connection_context: Dict[str, Any] = {}


# ============================================================================
# Middleware to capture connection headers
# ============================================================================

class ForecastContextMiddleware(Middleware):
    """Middleware to capture and store forecasting context from request headers.

    This captures forecasting context headers from any request:
        - X-Question-ID: Question to forecast
        - X-Knowledge-Cutoff: LLM's training data cutoff date
        - X-Simulated-Date: Simulated "today" date for forecasting

    Stores them globally for the session.
    """
    
    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages to capture headers."""
        logger.debug(f"Middleware processing: {context.method}")

        # Try to extract headers from FastMCP context if available
        if context.fastmcp_context:
            try:
                # Use get_http_request() method to access the HTTP request
                request = context.fastmcp_context.get_http_request()
                logger.debug(f"Got HTTP request: {request is not None}")
                
                if request and hasattr(request, 'headers'):
                    headers = request.headers
                    logger.debug(f"Request headers available: {list(headers.keys())[:5]}...")  # Only first 5

                    question_id = headers.get('x-question-id') or headers.get('X-Question-ID')
                    knowledge_cutoff = headers.get('x-knowledge-cutoff') or headers.get('X-Knowledge-Cutoff')
                    simulated_date = headers.get('x-simulated-date') or headers.get('X-Simulated-Date')
                    model_name = headers.get('x-model-name') or headers.get('X-Model-Name')
                    forecast_mode = headers.get('x-forecast-mode') or headers.get('X-Forecast-Mode')
                    session_id = headers.get('x-session-id') or headers.get('X-Session-ID')
                    db_path = headers.get('x-database-path') or headers.get('X-Database-Path')

                    logger.debug(f"Extracted - question_id: {question_id}, knowledge_cutoff: {knowledge_cutoff}, simulated_date: {simulated_date}, model: {model_name}, mode: {forecast_mode}, session_id: {session_id}, db_path: {db_path}")

                    # If headers are present, store them globally
                    if question_id and simulated_date:
                        try:
                            # IMPORTANT: Do NOT do any database operations here!
                            # Database queries are SYNCHRONOUS and will block the async event loop
                            # Just capture the raw header values - validation happens in tool functions

                            # Parse dates (fast, doesn't block)
                            simulated_date_obj = parse_flexible_datetime(simulated_date)
                            knowledge_cutoff_obj = parse_flexible_datetime(knowledge_cutoff) if knowledge_cutoff else None

                            # Validate knowledge cutoff < simulated date if provided
                            if knowledge_cutoff_obj and knowledge_cutoff_obj >= simulated_date_obj:
                                logger.error(
                                    f"Invalid dates: knowledge_cutoff {knowledge_cutoff_obj.date()} "
                                    f"must be before simulated_date {simulated_date_obj.date()}"
                                )
                                raise ValueError(
                                    f"Knowledge cutoff ({knowledge_cutoff_obj.date()}) must be BEFORE "
                                    f"simulated date ({simulated_date_obj.date()}). "
                                    f"The LLM must be 'deployed' after its training ends."
                                )

                            # Store raw values in context (no DB queries!)
                            _connection_context['question_id'] = question_id
                            _connection_context['knowledge_cutoff'] = knowledge_cutoff_obj.isoformat() if knowledge_cutoff_obj else None
                            _connection_context['knowledge_cutoff_obj'] = knowledge_cutoff_obj
                            _connection_context['simulated_date'] = simulated_date_obj.isoformat()
                            _connection_context['simulated_date_obj'] = simulated_date_obj
                            _connection_context['model_name'] = model_name or 'unknown'
                            _connection_context['forecast_mode'] = forecast_mode or 'container'
                            _connection_context['session_id'] = session_id
                            _connection_context['db_path'] = db_path

                            logger.info(
                                f"Context captured from headers: q={question_id}, "
                                f"mode={forecast_mode or 'container'}, "
                                f"session={session_id[:8] if session_id else 'N/A'}..., "
                                f"simulated_date={simulated_date_obj.date()}"
                            )
                        except Exception as e:
                            logger.error(f"Error parsing context headers: {e}")
                    else:
                        logger.debug("Headers missing required fields")
                else:
                    logger.debug("No HTTP request or headers available")
            except Exception as e:
                logger.debug(f"Could not get HTTP request: {e}")
        else:
            logger.debug("No fastmcp_context available")

        return await call_next(context)


# Add middleware to capture headers
mcp.add_middleware(ForecastContextMiddleware())


# ============================================================================
# Helper Functions
# ============================================================================

def _get_context_from_mcp(ctx: Context) -> Dict[str, Any]:
    """Extract forecasting context from MCP request metadata/headers.

    WORKAROUND: The middleware doesn't update the global cache for persistent connections,
    so we try to extract headers directly from the context object.

    Returns TWO important dates:
        - knowledge_cutoff: The LLM's training data cutoff (optional)
        - simulated_date: The simulated "today" for forecasting (required)

    Args:
        ctx: MCP context object

    Returns:
        Dict with:
            - question_id: The question to forecast
            - knowledge_cutoff: The LLM's training data cutoff (optional)
            - simulated_date: The simulated "today" (must be before resolution_date)
            - session_id: Unique session identifier
            - question: Full Question object

    Raises:
        ValueError: If required context not found or invalid
    """
    # Try to extract headers directly from ctx if possible
    question_id = None
    knowledge_cutoff_str = None
    simulated_date_str = None
    db_path_str = None

    try:
        # Try accessing the HTTP request from FastMCP context
        if hasattr(ctx, 'fastmcp_context') and ctx.fastmcp_context:
            request = ctx.fastmcp_context.get_http_request()
            if request and hasattr(request, 'headers'):
                headers = request.headers
                question_id = headers.get('x-question-id') or headers.get('X-Question-ID')
                knowledge_cutoff_str = headers.get('x-knowledge-cutoff') or headers.get('X-Knowledge-Cutoff')
                simulated_date_str = headers.get('x-simulated-date') or headers.get('X-Simulated-Date')
                db_path_str = headers.get('x-database-path') or headers.get('X-Database-Path')
                logger.debug(f"Extracted from context: q={question_id}, date={simulated_date_str}")
    except Exception as e:
        logger.debug(f"Could not extract headers from context: {e}")

    # Fall back to cached values if direct extraction failed
    if not question_id:
        logger.debug("Using cached _connection_context")
        question_id = _connection_context.get('question_id')
        knowledge_cutoff_obj = _connection_context.get('knowledge_cutoff_obj')
        simulated_date_obj = _connection_context.get('simulated_date_obj')
        db_path_str = _connection_context.get('db_path')
    else:
        # Parse the extracted headers
        simulated_date_obj = parse_flexible_datetime(simulated_date_str)
        knowledge_cutoff_obj = parse_flexible_datetime(knowledge_cutoff_str) if knowledge_cutoff_str else None

    # Always fetch the question from the database (middleware no longer does this)
    # Use database from header if provided, otherwise use global db
    request_db = GenericDatabase(db_path_str) if db_path_str else db
    question = request_db.get(Question, question_id)

    if not question_id:
        raise ValueError(
            "Forecasting context not initialized. "
            "Client must provide X-Question-ID and X-Simulated-Date headers when connecting."
        )

    if not simulated_date_obj:
        raise ValueError(
            "Simulated date not initialized. "
            "Client must provide X-Simulated-Date header when connecting. "
            "This header represents the simulated 'today' date (must be before the question's resolution date)."
        )

    if not question:
        raise ValueError(f"Question not found: {question_id}")

    # Get session ID from context (passed via headers) or create new one as fallback
    session_id = _connection_context.get('session_id')
    if not session_id:
        session_id = f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
        logger.warning(f"No session_id in headers, generated new one: {session_id}")

    return {
        "question_id": question_id,
        "knowledge_cutoff": knowledge_cutoff_obj,
        "simulated_date": simulated_date_obj,
        "session_id": session_id,
        "question": question,
        "db_path": db_path_str  # Include database path for per-request DB switching
    }


def _get_temporal_db(cutoff_date: datetime) -> GenericDatabase:
    """Get a database instance with temporal filtering applied.

    Args:
        cutoff_date: Cutoff date for temporal filtering

    Returns:
        GenericDatabase instance with temporal filtering
    """
    # Use database path from connection context if available (per-request switching)
    # Otherwise fall back to global db path
    db_path = _connection_context.get('db_path')
    database_path = db_path if db_path else db.db_path

    return GenericDatabase(database_path, cutoff_date=cutoff_date)


def _get_hybrid_search() -> HybridSearch:
    """Get a HybridSearch instance for the current request's database.

    Uses the database path from connection context if available (per-request switching),
    otherwise uses the global hybrid_search instance.

    Returns:
        HybridSearch instance for the appropriate database
    """
    # Use database path from connection context if available
    db_path = _connection_context.get('db_path')
    
    if db_path and db_path != db.db_path:
        # Different database requested - create new HybridSearch instance
        logger.debug(f"Creating HybridSearch for custom database: {db_path}")
        return HybridSearch(db_path)
    else:
        # Use global hybrid_search instance
        return hybrid_search



# ============================================================================
# MCP Tools
# ============================================================================


@mcp.tool()
def get_question(ctx: Context) -> str:
    """Get details about the current forecasting question.

    This returns the question you need to forecast, along with temporal context
    showing your knowledge cutoff date, the simulated "today" date, and how far
    into the future you're forecasting.

    The question ID, knowledge cutoff, and simulated date are provided via MCP
    connection metadata headers.

    Returns:
        JSON string with question details and temporal context
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        question = forecast_ctx["question"]
        knowledge_cutoff = forecast_ctx["knowledge_cutoff"]
        simulated_date = forecast_ctx["simulated_date"]

        result = {
            "question": {
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type.value,
                "domain": question.domain.value if hasattr(question.domain, 'value') else question.domain,
                "difficulty": question.difficulty,
                # "resolution_date": question.resolution_date.isoformat(),
                # "context": question.context, # The context might leak the answer
                "options": question.options,
                "quantity_unit": question.quantity_unit,
                # "target_event_id": question.target_event_id # Avoid leaking answer
            },
            "temporal_context": {
                "knowledge_cutoff_date": knowledge_cutoff.isoformat() if knowledge_cutoff else None,
                "today's date": simulated_date.isoformat(),
                # "resolution_date": question.resolution_date.isoformat(),
                "explanation": (
                    f"'today' is {simulated_date.date()}. "
                    + (f"Your training data cutoff is {knowledge_cutoff.date()}. " if knowledge_cutoff else "")
                )
            },
            "instructions": (
                f"FORECASTING SCENARIO:\n"
                + (f"- Your training data includes information up to: {knowledge_cutoff.date()}\n" if knowledge_cutoff else "")
                + f"- 'today' date: {simulated_date.date()}\n"
                f"- Approximate event resolution date: {question.resolution_date.date()}\n"
                f"- You must forecast: around {(question.resolution_date - simulated_date).days} days into the future\n"
                f"- All article searches will only return information from BEFORE today\n"
                f"- This tests your ability to make genuine predictions about future events"
            )
        }

        return json.dumps(result, indent=2)
        
    except ValueError as e:
        logger.error(f"Context error: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"Error getting question: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def temporal_search_articles(
    ctx: Context,
    query: str,
    domain: str,
    max_results: int = 10
) -> str:
    """Search for articles with temporal filtering using hybrid search.

    Uses a combination of keyword search (FTS5/BM25) and semantic search
    (embeddings) to find the most relevant articles published BEFORE the
    simulated date.

    The hybrid approach provides:
    - Fast keyword matching for exact terms
    - Semantic understanding for related concepts
    - BM25 + embedding fusion for best relevance

    Returns:
        JSON string with article summaries (only from before simulated date)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        simulated_date = forecast_ctx["simulated_date"]

        logger.info(f"Hybrid search: query='{query}', simulated_date={simulated_date.isoformat()}")

        # Get appropriate HybridSearch instance (handles per-request database switching)
        search_engine = _get_hybrid_search()

        # Perform hybrid search with temporal filtering
        # Returns article IDs ranked by hybrid score (FTS5 + embeddings)
        article_ids = await search_engine.search(
            query=query,
            max_results=max_results,
            cutoff_date=simulated_date,
            method="hybrid",
            alpha=0.5  # Equal weight to keyword and semantic search
        )

        logger.info(f"Hybrid search found {len(article_ids)} results")

        # Get temporal database for fetching full articles
        temporal_db = _get_temporal_db(simulated_date)

        # Fetch full article objects
        # Note: temporal_db.get() already applies temporal filtering
        matches = []
        for article_id in article_ids:
            article = temporal_db.get(Article, article_id)
            if article:
                # Apply domain filter if specified
                if domain and len(article_ids) > max_results * 10:
                    domain_filter = parse_domain(domain)
                    if domain_filter is not None and article.domain != domain_filter:
                        continue
                matches.append(article)

        # Limit results after domain filtering
        matches = matches[:max_results]

        # Format response
        result = {
            "query": query,
            "search_method": "hybrid (FTS5 + embeddings)",
            "simulated_date": simulated_date.isoformat(),
            "note": f"Only showing articles from BEFORE the simulated date ({simulated_date.date()})",
            "count": len(matches),
            "articles": [
                {
                    "id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source": article.source,
                    "domain": article.domain.value if hasattr(article.domain, 'value') else article.domain,
                    "published_date": article.published_date.isoformat(),
                    "word_count": article.word_count,
                    "excerpt": article.content[:300] + "..." if len(article.content) > 300 else article.content
                }
                for article in matches
            ]
        }

        return json.dumps(result, indent=2)

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"Error searching articles: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def fetch_article(
    ctx: Context,
    article_id: str
) -> str:
    """Fetch full article content with temporal validation.

    Only returns the article if it was published before the simulated date.
    This simulates accessing information available at the simulated "today" date.

    Returns:
        JSON string with full article content (only if before simulated date)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        simulated_date = forecast_ctx["simulated_date"]

        logger.info(f"Fetching article {article_id} with simulated_date {simulated_date.isoformat()}")

        # Get article from temporal database
        temporal_db = _get_temporal_db(simulated_date)
        article = temporal_db.get(Article, article_id)

        if not article:
            return json.dumps({
                "error": f"Article {article_id} not found or published after simulated date"
            })

        # Validate temporal access
        gateway = TemporalGateway(simulated_date)
        if not gateway.is_article_accessible(article):
            return json.dumps({
                "error": f"Article {article_id} was published after the simulated date",
                "published": article.published_date.isoformat(),
                "simulated_date": simulated_date.isoformat(),
                "note": "You can only access articles from before the simulated 'today' date"
            })

        # Return full article
        result = {
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "source": article.source,
            "domain": article.domain.value if hasattr(article.domain, 'value') else article.domain,
            "published_date": article.published_date.isoformat(),
            "author": article.author,
            "word_count": article.word_count,
            "tags": article.tags,
            "content": article.content[:2000] + "..." if len(article.content) > 2000 else article.content,
            "event_ids": article.event_ids
        }

        return json.dumps(result, indent=2)

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"Error fetching article: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def identify_forecast_event(ctx: Context, title: str, description: str, domain: str,
                           occurred_date: str, event_type: str = None,
                           source_article_ids: str = None) -> str:
    """Identify event for forecast reasoning.

    Use this tool to identify and record events that are relevant to your forecast.
    The tool checks for existing events and either reuses them or creates new ones.

    Args:
        title: Short event title
        description: Detailed event description
        domain: Event domain
        occurred_date: When event occurred (ISO format with timezone)
        event_type: Optional event type
        source_article_ids: Optional comma-separated article IDs

    Returns:
        JSON string with event details
    """
    try:
        session_id = _connection_context.get('session_id')
        if not session_id:
            return json.dumps({"error": "No session_id. Send X-Session-ID header."})

        from src.tools.forecast_event_identifier import ForecastEventIdentifierTool

        tool = ForecastEventIdentifierTool(
            question_db_path=db.db_path,
            forecast_db_path=_connection_context.get('db_path') or db.db_path,
            session_id=session_id
        )

        return tool.forward(title, description, domain, occurred_date, event_type, source_article_ids)
    except Exception as e:
        logger.error(f"Error identifying forecast event: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def create_forecast_causal_link(ctx: Context, source_event_id: str, target_event_id: str,
                               relation_type: str, strength: float, confidence: float,
                               reasoning: str, evidence_article_ids: str = "") -> str:
    """Create causal link for forecast reasoning.

    Use this tool to record causal relationships between events during forecasting.

    Args:
        source_event_id: Event ID of the cause
        target_event_id: Event ID of the effect
        relation_type: Type of causation
        strength: Causal strength (0-1)
        confidence: Confidence in link (0-1)
        reasoning: Explanation of mechanism
        evidence_article_ids: Optional comma-separated article IDs

    Returns:
        JSON confirmation with hypothesis ID
    """
    try:
        session_id = _connection_context.get('session_id')
        if not session_id:
            return json.dumps({"error": "No session_id. Send X-Session-ID header."})

        from src.tools.forecast_causal_reasoner import ForecastCausalReasonerTool

        tool = ForecastCausalReasonerTool(
            forecast_db_path=_connection_context.get('db_path') or db.db_path,
            session_id=session_id
        )

        return tool.forward(source_event_id, target_event_id, relation_type,
                          strength, confidence, reasoning, evidence_article_ids)
    except Exception as e:
        logger.error(f"Error creating forecast causal link: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def inspect_forecast_graph(ctx: Context) -> str:
    """Inspect forecast's causal reasoning graph.

    Use this tool to check the quality and structure of your causal reasoning graph.

    Returns:
        JSON with graph statistics and quality feedback
    """
    try:
        session_id = _connection_context.get('session_id')
        if not session_id:
            return json.dumps({"error": "No session_id. Send X-Session-ID header."})

        from src.tools.forecast_graph_inspector import ForecastGraphInspectorTool

        tool = ForecastGraphInspectorTool(
            forecast_db_path=_connection_context.get('db_path') or db.db_path,
            session_id=session_id
        )

        return tool.forward()
    except Exception as e:
        logger.error(f"Error inspecting forecast graph: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def submit_forecast(
    ctx: Context,
    prediction: str,
    confidence: float,
    reasoning: str,
    articles_accessed: list[str]
) -> str:
    """Submit a forecast for the current question.

    This records your prediction about a future event, based only on information
    available before the simulated date.

    Returns:
        JSON string with forecast ID and confirmation
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        question_id = forecast_ctx["question_id"]
        session_id = forecast_ctx["session_id"]
        simulated_date = forecast_ctx["simulated_date"]
        question = forecast_ctx["question"]

        logger.info(f"Submitting forecast for question {question_id}")

        # Parse prediction based on question type
        from src.domain.models.question import QuestionType

        try:
            if question.question_type == QuestionType.BINARY:
                parsed_prediction = prediction.lower() in ['true', 'yes', '1']
            elif question.question_type == QuestionType.MCQ:
                parsed_prediction = prediction
            elif question.question_type == QuestionType.QUANTITY:
                parsed_prediction = float(prediction)
            else:
                parsed_prediction = prediction
        except ValueError as e:
            return json.dumps({
                "error": f"Invalid prediction format for {question.question_type.value}: {e}"
            })

        # Validate prediction
        if not question.validate_prediction(parsed_prediction):
            return json.dumps({
                "error": f"Invalid prediction format for question type {question.question_type.value}",
                "expected_format": question.question_type.value
            })

        # Note: Confidence and reasoning validation is handled by Pydantic BaseModel

        # Create forecast
        forecast_id = f"fcst_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"

        # Get model name, mode, and db_path from context
        model_name = _connection_context.get('model_name', 'unknown')
        mode = _connection_context.get('forecast_mode', 'container')
        db_path = _connection_context.get('db_path')

        # Import ForecastMode enum
        from src.domain.models.forecast import ForecastMode

        forecast = Forecast(
            id=forecast_id,
            session_id=session_id,
            question_id=question_id,
            target_event_id=question.target_event_id,
            prediction=parsed_prediction,
            confidence=confidence,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
            simulated_date=simulated_date,
            articles_accessed=articles_accessed or [],
            searches_performed=[],  # Could track this if needed
            model_name=model_name,
            mode=ForecastMode(mode),
            db=db_path
        )

        # Save forecast to appropriate database
        forecast_db = GenericDatabase(db_path) if db_path else db
        forecast_db.save(Forecast, forecast)
        logger.info(f"Forecast saved to database: {forecast_id}")

        # Link events and hypotheses to forecast_id
        from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis

        try:
            # Get all forecast events for this session
            events = forecast_db.get_many(ForecastEvent, filters={'session_id': session_id})
            for event in events:
                event.forecast_id = forecast_id
                forecast_db.save(ForecastEvent, event)

            # Get all forecast hypotheses for this session
            hypotheses = forecast_db.get_many(ForecastHypothesis, filters={'session_id': session_id})
            for hyp in hypotheses:
                hyp.forecast_id = forecast_id
                forecast_db.save(ForecastHypothesis, hyp)

            logger.info(f"Linked {len(events)} events and {len(hypotheses)} hypotheses to forecast {forecast_id}")
        except Exception as e:
            logger.warning(f"Could not link forecast graph to forecast_id: {e}")

        result = {
            "forecast_id": forecast_id,
            "question_id": question_id,
            "prediction": parsed_prediction,
            "confidence": confidence,
            "simulated_date": simulated_date.isoformat(),
            "submitted_at": forecast.timestamp.isoformat(),
            "status": "submitted",
            "note": (
                f"Forecast submitted! You predicted based on information from before the simulated date ({simulated_date.date()}). "
                f"The actual outcome will be known on {question.resolution_date.date()}."
            )
        }

        return json.dumps(result, indent=2)

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"Error submitting forecast: {e}")
        return json.dumps({"error": str(e)})




# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for streamable HTTP MCP server.

    The server accepts forecasting context from the MCP client via connection
    metadata/headers, not from CLI args:
        - question_id: The question to forecast
        - knowledge_cutoff: The LLM's training data cutoff (optional)
        - simulated_date: The simulated "today" date (required)

    Mode:
        stream  - Streamable HTTP (Server-Sent Events) for incremental tool output

    Example:
        # Start server (context comes from client)
        python -m src.mcp_forecasting_server
        python -m src.mcp_forecasting_server --port 8110
        python -m src.mcp_forecasting_server --host 0.0.0.0 --port 8110 --log-level info
    """
    parser = argparse.ArgumentParser(
        description="WorldReasoner Forecasting MCP Server (Streamable HTTP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start server with default settings
  python -m src.mcp_forecasting_server

  # Custom port
  python -m src.mcp_forecasting_server --port 8110

  # Custom host and log level
  python -m src.mcp_forecasting_server --host 0.0.0.0 --port 8110 --log-level info

Connection Metadata (provided by MCP client):
  X-Question-ID: Question identifier to forecast
  X-Knowledge-Cutoff: LLM's training data cutoff date (ISO format, optional)
  X-Simulated-Date: Simulated "today" date (ISO format, required)
                    Must be AFTER knowledge cutoff and BEFORE resolution date
        """
    )
    parser.add_argument(
        "--db",
        default=DB_PATH,
        help="Path to WorldReasoner database (default: worldreasoner.db)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8110,
        help="Port (default: 8110)"
    )
    parser.add_argument(
        "--log-level",
        default="debug",
        help="Logging level: debug|info|warning|error (default: debug)"
    )
    global db, hybrid_search, _connection_context

    # Clear cached connection context from any previous server instance
    _connection_context.clear()
    logger.info("Cleared _connection_context cache on server startup")

    args = parser.parse_args()
    db = GenericDatabase(args.db)
    # Ensure forecasts table exists (idempotent)
    db.create_table(Forecast)

    # HybridSearch loads embedding_model from config.yaml by default
    hybrid_search = HybridSearch(args.db)

    logger.info(f"Launching MCP server (stream mode) db={args.db}")
    logger.info("Forecasting context will be provided by MCP client via headers:")
    logger.info("  - X-Question-ID (required)")
    logger.info("  - X-Knowledge-Cutoff (optional)")
    logger.info("  - X-Simulated-Date (required)")

    logger.info(f"Starting MCP STREAMABLE HTTP server on http://{args.host}:{args.port}")
    logger.info("Endpoints: /mcp/tools, /mcp/prompts, SSE streaming available")
    logger.info("Context headers: X-Question-ID, X-Knowledge-Cutoff (optional), X-Simulated-Date (required)")

    # Add health check endpoint
    from fastapi.responses import JSONResponse
    from starlette.routing import Route

    # Define health check function
    async def health_check(request):
        """Health check endpoint for monitoring server availability."""
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "database": args.db,
                "server_type": "mcp_forecasting",
                "mode": "streamable_http"
            }
        )

    # Get the app instance using http_app() with streamable-http transport
    logger.info("Creating FastMCP HTTP app...")
    try:
        app = mcp.http_app(transport="streamable-http")
        logger.info("FastMCP app created successfully")
    except Exception as e:
        logger.error(f"Failed to create FastMCP app: {e}", exc_info=True)
        raise

    # Add health check route to the Starlette app
    logger.info("Adding health check route...")
    app.routes.append(Route("/health", health_check, methods=["GET"]))
    logger.info(f"MCP server app created with {len(app.routes)} routes")

    logger.info(f"Starting uvicorn server on {args.host}:{args.port}")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    import sys
    main()
