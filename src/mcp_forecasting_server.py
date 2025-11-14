"""Temporal-aware MCP server for LLM forecasting.

This MCP server provides tools for LLMs to make forecasts while respecting
temporal constraints. All search and fetch operations are filtered based on
a cutoff date to simulate historical contexts.

The forecasting context (question ID and knowledge cutoff) is provided via
MCP connection metadata/headers when the client connects. This allows one
server instance to handle multiple forecasting sessions.

Exposed Tools (4 essential tools):
    1. get_question - Get the current forecast question details
    2. temporal_search_articles - Search articles before cutoff date
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
    # X-Knowledge-Cutoff: 2024-04-01T00:00:00Z

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
from src.domain.models import Article, Question, Forecast, Event
from src.domain.models.domain import Domain
from src.utils.logging import logger

# Initialize MCP server
mcp = FastMCP("worldreasoner-forecasting")

# Global database connection
DB_PATH = os.getenv("WORLDREASONER_DB", "worldreasoner.db")
db = GenericDatabase(DB_PATH)

# Connection-level context storage (populated from request headers)
# Captured by middleware during any request with the headers
_connection_context: Dict[str, Any] = {}


# ============================================================================
# Middleware to capture connection headers
# ============================================================================

class ForecastContextMiddleware(Middleware):
    """Middleware to capture and store forecasting context from request headers.
    
    This captures X-Question-ID and X-Knowledge-Cutoff headers from any request
    (tool listing, tool calls, etc.) and stores them globally for the session.
    """
    
    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages to capture headers."""
        logger.debug(f"Middleware triggered for method: {context.method}")
        
        # Try to extract headers from FastMCP context if available
        if context.fastmcp_context:
            try:
                # Use get_http_request() method to access the HTTP request
                request = context.fastmcp_context.get_http_request()
                logger.debug(f"Got HTTP request: {request is not None}")
                
                if request and hasattr(request, 'headers'):
                    headers = request.headers
                    logger.debug(f"Available headers: {list(headers.keys())}")
                    
                    question_id = headers.get('x-question-id') or headers.get('X-Question-ID')
                    knowledge_cutoff = headers.get('x-knowledge-cutoff') or headers.get('X-Knowledge-Cutoff')
                    
                    logger.debug(f"Extracted - question_id: {question_id}, knowledge_cutoff: {knowledge_cutoff}")
                    
                    # If headers are present, store them globally
                    if question_id and knowledge_cutoff:
                        try:
                            # Parse cutoff date
                            if 'T' in knowledge_cutoff:
                                cutoff_date = datetime.fromisoformat(knowledge_cutoff.replace('Z', '+00:00'))
                            else:
                                cutoff_date = datetime.fromisoformat(f"{knowledge_cutoff}T00:00:00+00:00")
                            
                            if cutoff_date.tzinfo is None:
                                cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
                            
                            # Validate question exists
                            question = db.get(Question, question_id)
                            if question:
                                _connection_context['question_id'] = question_id
                                _connection_context['knowledge_cutoff'] = cutoff_date.isoformat()
                                _connection_context['cutoff_date_obj'] = cutoff_date
                                _connection_context['question'] = question
                                logger.info(f"✓ Context captured from headers: q={question_id}, cutoff={cutoff_date.date()}")
                            else:
                                logger.warning(f"Question {question_id} not found in database")
                        except Exception as e:
                            logger.error(f"Error parsing context headers: {e}", exc_info=True)
                    else:
                        logger.debug("No question_id or knowledge_cutoff in headers")
                else:
                    logger.debug("No HTTP request or headers available")
            except Exception as e:
                logger.debug(f"Could not get HTTP request: {e}")
        
        return await call_next(context)


# Add middleware to capture headers
mcp.add_middleware(ForecastContextMiddleware())


# ============================================================================
# Helper Functions
# ============================================================================

def _get_context_from_mcp(ctx: Context) -> Dict[str, Any]:
    """Extract forecasting context from MCP request metadata/headers.
    
    The context is automatically captured by middleware from request headers
    and stored in _connection_context. This function retrieves it.
    
    Args:
        ctx: MCP context object (not used, kept for compatibility)
        
    Returns:
        Dict with question_id, cutoff_date, session_id, and question object
        
    Raises:
        ValueError: If required context not found
    """
    question_id = _connection_context.get('question_id')
    cutoff_date_obj = _connection_context.get('cutoff_date_obj')
    question = _connection_context.get('question')
    
    if not question_id:
        raise ValueError(
            "Forecasting context not initialized. "
            "Client must provide X-Question-ID and X-Knowledge-Cutoff headers when connecting."
        )
    
    if not cutoff_date_obj:
        raise ValueError(
            "Knowledge cutoff date not initialized. "
            "Client must provide X-Knowledge-Cutoff header when connecting."
        )
    
    if not question:
        raise ValueError(f"Question not found: {question_id}")
    
    # Create session ID
    session_id = f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
    
    return {
        "question_id": question_id,
        "cutoff_date": cutoff_date_obj,
        "session_id": session_id,
        "question": question
    }


def _get_temporal_db(cutoff_date: datetime) -> GenericDatabase:
    """Get a database instance with temporal filtering applied.
    
    Args:
        cutoff_date: Cutoff date for temporal filtering
        
    Returns:
        GenericDatabase instance with temporal filtering
    """
    return GenericDatabase(DB_PATH, cutoff_date=cutoff_date)


# ============================================================================
# Pydantic Models for Parameters
# ============================================================================

class SearchQuery(BaseModel):
    """Search query parameter."""
    value: str = Field(..., description="Search query string")


class DomainFilter(BaseModel):
    """Domain filter parameter."""
    value: str | None = Field(None, description="Optional domain filter (e.g., 'technology', 'politics')")


class MaxResults(BaseModel):
    """Maximum results parameter."""
    value: int = Field(10, description="Maximum number of results to return", ge=1, le=100)


class ArticleId(BaseModel):
    """Article ID parameter."""
    value: str = Field(..., description="ID of the article to fetch")


class Prediction(BaseModel):
    """Prediction parameter."""
    value: str = Field(..., description="Your prediction (Boolean: 'true'/'false', MCQ: option text, Quantity: numeric value, Timeframe: date/range)")


class Confidence(BaseModel):
    """Confidence parameter."""
    value: float = Field(..., description="Confidence level (0.0 to 1.0)", ge=0.0, le=1.0)


class Reasoning(BaseModel):
    """Reasoning parameter."""
    value: str = Field(..., description="Detailed explanation of your reasoning", min_length=50)


class ArticlesAccessed(BaseModel):
    """Articles accessed parameter."""
    value: List[str] | None = Field(None, description="Optional list of article IDs you reviewed")


# ============================================================================
# MCP Tools
# ============================================================================


@mcp.tool()
def get_question(ctx: Context) -> str:
    """Get details about the current forecasting question.
    
    This returns the question you need to forecast, along with temporal context
    showing your knowledge cutoff date and how far into the future you're forecasting.
    
    The question ID and knowledge cutoff are provided via MCP connection metadata:
        - X-Question-ID header (HTTP mode)
        - question_id metadata (stdio mode)

    Returns:
        JSON string with question details and temporal context
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        question = forecast_ctx["question"]
        cutoff = forecast_ctx["cutoff_date"]
        
        result = {
            "question": {
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type.value,
                "domain": question.domain.value if hasattr(question.domain, 'value') else question.domain,
                "difficulty": question.difficulty,
                "resolution_date": question.resolution_date.isoformat(),
                "context": question.context,
                "options": question.options,
                "quantity_unit": question.quantity_unit,
                "target_event_id": question.target_event_id
            },
            "temporal_context": {
                "knowledge_cutoff_date": cutoff.isoformat(),
                "resolution_date": question.resolution_date.isoformat(),
                "days_to_forecast": (question.resolution_date - cutoff).days,
                "explanation": (
                    f"Your knowledge cutoff is {cutoff.date()}. "
                    f"You must forecast an event that resolves on {question.resolution_date.date()} "
                    f"({(question.resolution_date - cutoff).days} days in the future)."
                )
            },
            "instructions": (
                f"FORECASTING SCENARIO:\n"
                f"- Your training data includes information up to: {cutoff.date()}\n"
                f"- Event resolution date: {question.resolution_date.date()}\n"
                f"- You must forecast: {(question.resolution_date - cutoff).days} days into the future\n"
                f"- All article searches will only return information from BEFORE your knowledge cutoff\n"
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
def temporal_search_articles(
    ctx: Context,
    query: SearchQuery,
    domain: DomainFilter = DomainFilter(),
    max_results: MaxResults = MaxResults()
) -> str:
    """Search for articles with temporal filtering.

    Only returns articles published BEFORE the LLM's knowledge cutoff date.
    This simulates searching through the LLM's training data.

    Returns:
        JSON string with article summaries (only from before knowledge cutoff)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        cutoff = forecast_ctx["cutoff_date"]

        logger.info(f"Searching articles with query='{query.value}', cutoff={cutoff.isoformat()}")

        # Get temporal database
        temporal_db = _get_temporal_db(cutoff)

        # Build filters
        filters = {}
        if domain.value:
            try:
                filters['domain'] = Domain(domain.value.lower())
            except ValueError:
                pass

        # Get all articles (temporal filtering applied automatically)
        all_articles = temporal_db.get_many(Article, filters=filters if filters else None)

        # Simple text search (you could enhance this with embeddings/FTS)
        query_lower = query.value.lower()
        matches = [
            article for article in all_articles
            if query_lower in article.title.lower() or query_lower in article.content.lower()
        ]

        # Sort by published date (most recent first)
        matches.sort(key=lambda a: a.published_date, reverse=True)
        matches = matches[:max_results.value]

        # Format response
        result = {
            "query": query.value,
            "knowledge_cutoff_date": cutoff.isoformat(),
            "note": f"Only showing articles from BEFORE knowledge cutoff ({cutoff.date()})",
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
    article_id: ArticleId
) -> str:
    """Fetch full article content with temporal validation.

    Only returns the article if it was published before the LLM's knowledge cutoff.
    This simulates accessing information from the LLM's training data.

    Returns:
        JSON string with full article content (only if before knowledge cutoff)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        cutoff = forecast_ctx["cutoff_date"]

        logger.info(f"Fetching article {article_id.value} with cutoff {cutoff.isoformat()}")

        # Get article from temporal database
        temporal_db = _get_temporal_db(cutoff)
        article = temporal_db.get(Article, article_id.value)

        if not article:
            return json.dumps({
                "error": f"Article {article_id.value} not found or published after cutoff date"
            })

        # Validate temporal access
        gateway = TemporalGateway(cutoff)
        if not gateway.is_article_accessible(article):
            return json.dumps({
                "error": f"Article {article_id.value} was published after your knowledge cutoff",
                "published": article.published_date.isoformat(),
                "knowledge_cutoff": cutoff.isoformat(),
                "note": "You can only access articles from your training data (before knowledge cutoff)"
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
            "content": article.content,
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
def submit_forecast(
    ctx: Context,
    prediction: Prediction,
    confidence: Confidence,
    reasoning: Reasoning,
    articles_accessed: ArticlesAccessed = ArticlesAccessed()
) -> str:
    """Submit a forecast for the current question.

    This records your prediction about a future event, based only on information
    available before your knowledge cutoff date.

    Returns:
        JSON string with forecast ID and confirmation
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        question_id = forecast_ctx["question_id"]
        session_id = forecast_ctx["session_id"]
        cutoff_date = forecast_ctx["cutoff_date"]
        question = forecast_ctx["question"]

        logger.info(f"Submitting forecast for question {question_id}")

        # Parse prediction based on question type
        from src.domain.models.question import QuestionType

        try:
            if question.question_type == QuestionType.BOOLEAN:
                parsed_prediction = prediction.value.lower() in ['true', 'yes', '1']
            elif question.question_type == QuestionType.MCQ:
                parsed_prediction = prediction.value
            elif question.question_type == QuestionType.QUANTITY:
                parsed_prediction = float(prediction.value)
            else:
                parsed_prediction = prediction.value
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

        forecast = Forecast(
            id=forecast_id,
            session_id=session_id,
            question_id=question_id,
            target_event_id=question.target_event_id,
            prediction=parsed_prediction,
            confidence=confidence.value,
            reasoning=reasoning.value,
            timestamp=datetime.now(timezone.utc),
            simulated_date=cutoff_date,
            articles_accessed=articles_accessed.value or [],
            searches_performed=[],  # Could track this if needed
            model_name="mcp_client",  # Will be updated by client
        )

        # TODO: Save forecast to database (need to register Forecast model)
        # For now, just return confirmation

        logger.info(f"Forecast submitted: {forecast_id}")

        result = {
            "forecast_id": forecast_id,
            "question_id": question_id,
            "prediction": parsed_prediction,
            "confidence": confidence.value,
            "knowledge_cutoff_date": cutoff_date.isoformat(),
            "submitted_at": forecast.timestamp.isoformat(),
            "status": "submitted",
            "note": (
                f"Forecast submitted! You predicted based on information from before {cutoff_date.date()}. "
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
    """CLI entry point that supports stdio, basic HTTP, and streamable HTTP modes.

    The server accepts forecasting context (question_id and knowledge_cutoff) 
    from the MCP client via connection metadata/headers, not from CLI args.

    Modes:
        stdio   - (default) MCP over stdio (ideal for local tool integration)
        http    - REST-style MCP HTTP endpoints (FastAPI app)
        stream  - Streamable HTTP (Server-Sent Events) for incremental tool output

    Example:
        # Start server (context comes from client)
        python -m src.mcp_forecasting_server
        python -m src.mcp_forecasting_server --mode http --port 8100
        python -m src.mcp_forecasting_server --mode stream --port 8110
    """
    parser = argparse.ArgumentParser(
        description="WorldReasoner Forecasting MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard stdio mode (for Claude Desktop)
  python -m src.mcp_forecasting_server
  
  # HTTP REST mode
  python -m src.mcp_forecasting_server --mode http --port 8100
  
  # Streaming mode with SSE
  python -m src.mcp_forecasting_server --mode stream --port 8110
  
  # Custom host and log level
  python -m src.mcp_forecasting_server --mode http --host 0.0.0.0 --port 8100 --log-level debug

Connection Metadata (provided by MCP client):
  X-Question-ID: Question identifier to forecast
  X-Knowledge-Cutoff: LLM's knowledge cutoff date (ISO format)
        """
    )
    parser.add_argument(
        "--mode", 
        choices=["stdio", "http", "stream"], 
        default="stdio",
        help="Run mode: stdio | http | stream (streamable HTTP/SSE)"
    )
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Bind host for HTTP/stream modes (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8100, 
        help="Port for HTTP/stream modes (default: 8100)"
    )
    parser.add_argument(
        "--log-level", 
        default="debug",  # Changed to debug for troubleshooting
        help="Logging level: debug|info|warning|error (default: debug)"
    )
    args = parser.parse_args()

    logger.info(f"Launching MCP server mode={args.mode} db={DB_PATH}")
    logger.info("Forecasting context (question_id, knowledge_cutoff) will be provided by MCP client")

    # Adjust logging level if provided
    try:
        from loguru import logger as _lg
        _lg.remove()
        import sys
        _lg.add(sys.stderr, level=args.log_level.upper())
    except Exception:
        pass

    if args.mode == "stdio":
        logger.info("Starting MCP server (stdio mode)")
        mcp.run()
    elif args.mode == "http":
        logger.info(f"Starting MCP HTTP server on http://{args.host}:{args.port}")
        logger.info("API docs available at /docs")
        import uvicorn
        uvicorn.run(mcp.http_app, host=args.host, port=args.port)
    else:  # stream
        logger.info(f"Starting MCP STREAMABLE HTTP server on http://{args.host}:{args.port}")
        logger.info("Endpoints: /mcp/tools, /mcp/prompts, SSE streaming available")
        logger.info("Context will be captured from X-Question-ID and X-Knowledge-Cutoff headers")
        import uvicorn
        uvicorn.run(mcp.streamable_http_app, host=args.host, port=args.port)


if __name__ == "__main__":
    import sys
    main()
