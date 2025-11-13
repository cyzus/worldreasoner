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

Server Modes:
    - stdio: MCP over stdin/stdout (default, for Claude Desktop)
    - http: REST-style HTTP endpoints
    - stream: Streamable HTTP with Server-Sent Events (SSE)

Usage:
    # Start server (any mode)
    python -m src.mcp_forecasting_server
    python -m src.mcp_forecasting_server --mode http --port 8100
    python -m src.mcp_forecasting_server --mode stream --port 8110
    
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
from typing import Optional, List, Dict, Any
from contextvars import ContextVar

from fastmcp import FastMCP
from fastmcp.server import Context

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


# ============================================================================
# Helper Functions
# ============================================================================

def _get_context_from_mcp(ctx: Context) -> Dict[str, Any]:
    """Extract forecasting context from MCP request metadata/headers.
    
    Expects client to provide:
        - X-Question-ID: Question identifier
        - X-Knowledge-Cutoff: ISO format datetime (LLM's knowledge cutoff)
    
    Args:
        ctx: MCP context object containing request metadata
        
    Returns:
        Dict with question_id, cutoff_date, session_id, and question object
        
    Raises:
        ValueError: If required headers missing or invalid
    """
    # Get metadata from context
    # FastMCP provides metadata via ctx.meta or similar
    # For HTTP: headers are in ctx.request.headers
    # For stdio: metadata comes from initialization params
    
    metadata = getattr(ctx, 'meta', {})
    
    # Try to get from headers if HTTP mode
    if hasattr(ctx, 'request') and hasattr(ctx.request, 'headers'):
        headers = ctx.request.headers
        question_id = headers.get('x-question-id') or headers.get('X-Question-ID')
        knowledge_cutoff = headers.get('x-knowledge-cutoff') or headers.get('X-Knowledge-Cutoff')
    else:
        # Stdio mode: get from metadata
        question_id = metadata.get('question_id')
        knowledge_cutoff = metadata.get('knowledge_cutoff')
    
    if not question_id:
        raise ValueError(
            "Missing question_id in request. "
            "Provide via X-Question-ID header (HTTP) or question_id metadata (stdio)"
        )
    
    if not knowledge_cutoff:
        raise ValueError(
            "Missing knowledge_cutoff in request. "
            "Provide via X-Knowledge-Cutoff header (HTTP) or knowledge_cutoff metadata (stdio)"
        )
    
    # Parse cutoff date
    try:
        cutoff_date = datetime.fromisoformat(knowledge_cutoff.replace('Z', '+00:00'))
        if cutoff_date.tzinfo is None:
            cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"Invalid knowledge_cutoff date format: {e}")
    
    # Get question
    question = db.get(Question, question_id)
    if not question:
        raise ValueError(f"Question not found: {question_id}")
    
    # Validate cutoff is before resolution
    if cutoff_date >= question.resolution_date:
        raise ValueError(
            f"Knowledge cutoff ({cutoff_date.date()}) must be before "
            f"resolution date ({question.resolution_date.date()})"
        )
    
    # Create session ID
    session_id = f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
    
    return {
        "question_id": question_id,
        "cutoff_date": cutoff_date,
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
    query: str,
    domain: Optional[str] = None,
    max_results: int = 10
) -> str:
    """Search for articles with temporal filtering.

    Only returns articles published BEFORE the LLM's knowledge cutoff date.
    This simulates searching through the LLM's training data.

    Args:
        query: Search query string
        domain: Optional domain filter
        max_results: Maximum number of results

    Returns:
        JSON string with article summaries (only from before knowledge cutoff)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        cutoff = forecast_ctx["cutoff_date"]
        
        logger.info(f"Searching articles with query='{query}', cutoff={cutoff.isoformat()}")

        # Get temporal database
        temporal_db = _get_temporal_db(cutoff)

        # Build filters
        filters = {}
        if domain:
            try:
                filters['domain'] = Domain(domain.lower())
            except ValueError:
                pass

        # Get all articles (temporal filtering applied automatically)
        all_articles = temporal_db.get_many(Article, filters=filters if filters else None)

        # Simple text search (you could enhance this with embeddings/FTS)
        query_lower = query.lower()
        matches = [
            article for article in all_articles
            if query_lower in article.title.lower() or query_lower in article.content.lower()
        ]

        # Sort by published date (most recent first)
        matches.sort(key=lambda a: a.published_date, reverse=True)
        matches = matches[:max_results]

        # Format response
        result = {
            "query": query,
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
def fetch_article(ctx: Context, article_id: str) -> str:
    """Fetch full article content with temporal validation.

    Only returns the article if it was published before the LLM's knowledge cutoff.
    This simulates accessing information from the LLM's training data.

    Args:
        article_id: ID of the article to fetch

    Returns:
        JSON string with full article content (only if before knowledge cutoff)
    """
    try:
        # Get context from MCP request
        forecast_ctx = _get_context_from_mcp(ctx)
        cutoff = forecast_ctx["cutoff_date"]
        
        logger.info(f"Fetching article {article_id} with cutoff {cutoff.isoformat()}")

        # Get article from temporal database
        temporal_db = _get_temporal_db(cutoff)
        article = temporal_db.get(Article, article_id)

        if not article:
            return json.dumps({
                "error": f"Article {article_id} not found or published after cutoff date"
            })

        # Validate temporal access
        gateway = TemporalGateway(cutoff)
        if not gateway.is_article_accessible(article):
            return json.dumps({
                "error": f"Article {article_id} was published after your knowledge cutoff",
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
    prediction: str,
    confidence: float,
    reasoning: str,
    articles_accessed: Optional[List[str]] = None
) -> str:
    """Submit a forecast for the current question.

    This records your prediction about a future event, based only on information
    available before your knowledge cutoff date.

    Args:
        prediction: Your prediction (format depends on question type)
                   - Boolean: "true" or "false"
                   - MCQ: One of the question's options
                   - Quantity: Numeric value
                   - Timeframe: Date or date range
        confidence: Confidence level (0.0 to 1.0)
        reasoning: Detailed explanation of your reasoning (min 50 chars)
                  Should explain how you used pre-cutoff information to forecast
        articles_accessed: Optional list of article IDs you reviewed

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

        # Validate confidence
        if not (0.0 <= confidence <= 1.0):
            return json.dumps({"error": "Confidence must be between 0.0 and 1.0"})

        # Validate reasoning length
        if len(reasoning) < 50:
            return json.dumps({"error": "Reasoning must be at least 50 characters"})

        # Create forecast
        forecast_id = f"fcst_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"

        forecast = Forecast(
            id=forecast_id,
            session_id=session_id,
            question_id=question_id,
            target_event_id=question.target_event_id,
            prediction=parsed_prediction,
            confidence=confidence,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
            simulated_date=cutoff_date,
            articles_accessed=articles_accessed or [],
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
            "confidence": confidence,
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
        default="info", 
        help="Logging level: debug|info|warning|error (default: info)"
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
        import uvicorn
        uvicorn.run(mcp.streamable_http_app, host=args.host, port=args.port)


if __name__ == "__main__":
    import sys
    main()
