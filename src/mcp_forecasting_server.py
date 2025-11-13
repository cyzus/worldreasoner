"""Temporal-aware MCP server for LLM forecasting.

This MCP server provides tools for LLMs to make forecasts while respecting
temporal constraints. All search and fetch operations are filtered based on
a cutoff date to simulate historical contexts.

Server Modes:
    - stdio: MCP over stdin/stdout (default, for Claude Desktop)
    - http: REST-style HTTP endpoints
    - stream: Streamable HTTP with Server-Sent Events (SSE)

Usage:
    # Default stdio mode
    python -m src.mcp_forecasting_server
    
    # HTTP mode
    python -m src.mcp_forecasting_server --mode http --port 8100
    
    # Streaming mode
    python -m src.mcp_forecasting_server --mode stream --port 8110

Configuration:
    WORLDREASONER_DB: Path to database (default: worldreasoner.db)
"""

import os
import json
import argparse
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastmcp import FastMCP

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

# Session state for tracking current forecasting context
# This is stored in module scope to persist across tool calls
_current_context: Dict[str, Any] = {
    "question_id": None,
    "cutoff_date": None,
    "forecast_session_id": None
}


# ============================================================================
# Helper Functions
# ============================================================================

def _get_temporal_db() -> GenericDatabase:
    """Get a database instance with temporal filtering applied.
    
    Returns a database that automatically filters Articles and Events
    based on the current session's cutoff date.
    
    Returns:
        GenericDatabase instance with temporal filtering (if cutoff set)
    """
    cutoff = _current_context.get("cutoff_date")
    if cutoff:
        return GenericDatabase(DB_PATH, cutoff_date=cutoff)
    return db


# ============================================================================
# MCP Tools
# ============================================================================


@mcp.tool()
def list_questions(
    domain: Optional[str] = None,
    difficulty: Optional[int] = None,
    limit: int = 20
) -> str:
    """List available forecast questions.

    Args:
        domain: Filter by domain (politics, tech, finance, etc.)
        difficulty: Filter by difficulty (1-5)
        limit: Maximum number of questions to return

    Returns:
        JSON string with list of questions
    """
    try:
        logger.info(f"Listing questions: domain={domain}, difficulty={difficulty}, limit={limit}")

        # Build filters
        filters = {}
        if domain:
            try:
                filters['domain'] = Domain(domain.lower())
            except ValueError:
                return json.dumps({
                    "error": f"Invalid domain: {domain}",
                    "valid_domains": [d.value for d in Domain]
                })

        if difficulty:
            if not (1 <= difficulty <= 5):
                return json.dumps({"error": "Difficulty must be between 1 and 5"})
            filters['difficulty'] = difficulty

        # Get questions
        questions = db.get_many(Question, filters=filters if filters else None)
        questions = questions[:limit]

        # Format response
        result = {
            "count": len(questions),
            "questions": [
                {
                    "id": q.id,
                    "question_text": q.question_text,
                    "question_type": q.question_type.value,
                    "domain": q.domain.value if hasattr(q.domain, 'value') else q.domain,
                    "difficulty": q.difficulty,
                    "resolution_date": q.resolution_date.isoformat(),
                    "is_resolved": q.ground_truth is not None,
                    "created_at": q.created_at.isoformat()
                }
                for q in questions
            ]
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error listing questions: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def start_forecast_session(
    question_id: str,
    knowledge_cutoff_date: Optional[str] = None
) -> str:
    """Start a new forecasting session for a specific question.

    This sets the temporal context based on the LLM's knowledge cutoff date.
    The LLM will only have access to information from before its knowledge cutoff,
    and must forecast events that happen AFTER this cutoff.

    Args:
        question_id: ID of the question to forecast
        knowledge_cutoff_date: LLM's knowledge cutoff date (ISO format).
                              This represents what the LLM knows from training.
                              If not provided, uses question creation date.

    Returns:
        JSON string with question details and temporal context
    """
    try:
        logger.info(f"Starting forecast session for question: {question_id}")

        # Get question
        question = db.get(Question, question_id)
        if not question:
            return json.dumps({"error": f"Question not found: {question_id}"})

        # Determine knowledge cutoff date
        if knowledge_cutoff_date:
            try:
                cutoff_date = datetime.fromisoformat(knowledge_cutoff_date.replace('Z', '+00:00'))
                if cutoff_date.tzinfo is None:
                    cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            except ValueError as e:
                return json.dumps({"error": f"Invalid date format: {e}"})
        else:
            # Use question creation date as default cutoff
            cutoff_date = question.created_at

        # Validate cutoff is before resolution (LLM must forecast the future!)
        if cutoff_date >= question.resolution_date:
            return json.dumps({
                "error": "Knowledge cutoff must be before resolution date (can't forecast the past!)",
                "knowledge_cutoff": cutoff_date.isoformat(),
                "resolution": question.resolution_date.isoformat(),
                "note": "The LLM must forecast events that happen AFTER its knowledge cutoff"
            })

        # Set session context
        session_id = f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
        _current_context["question_id"] = question_id
        _current_context["cutoff_date"] = cutoff_date
        _current_context["forecast_session_id"] = session_id

        logger.info(f"Session started: {session_id} with cutoff {cutoff_date.isoformat()}")

        # Return question details
        result = {
            "session_id": session_id,
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
                "knowledge_cutoff_date": cutoff_date.isoformat(),
                "resolution_date": question.resolution_date.isoformat(),
                "days_to_forecast": (question.resolution_date - cutoff_date).days,
                "explanation": (
                    f"Your knowledge cutoff is {cutoff_date.date()}. "
                    f"You must forecast an event that resolves on {question.resolution_date.date()} "
                    f"({(question.resolution_date - cutoff_date).days} days in the future)."
                )
            },
            "instructions": (
                f"FORECASTING SCENARIO:\n"
                f"- Your training data includes information up to: {cutoff_date.date()}\n"
                f"- Event resolution date: {question.resolution_date.date()}\n"
                f"- You must forecast: {(question.resolution_date - cutoff_date).days} days into the future\n"
                f"- All article searches will only return information from BEFORE your knowledge cutoff\n"
                f"- This tests your ability to make genuine predictions about future events"
            )
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error starting session: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def temporal_search_articles(
    query: str,
    domain: Optional[str] = None,
    max_results: int = 10
) -> str:
    """Search for articles with temporal filtering.

    Only returns articles published BEFORE the LLM's knowledge cutoff date.
    This simulates searching through the LLM's training data.

    You must call start_forecast_session first to set the knowledge cutoff.

    Args:
        query: Search query string
        domain: Optional domain filter
        max_results: Maximum number of results

    Returns:
        JSON string with article summaries (only from before knowledge cutoff)
    """
    try:
        # Check session context
        if not _current_context.get("cutoff_date"):
            return json.dumps({
                "error": "No active forecast session. Call start_forecast_session first."
            })

        cutoff = _current_context["cutoff_date"]
        logger.info(f"Searching articles with query='{query}', cutoff={cutoff.isoformat()}")

        # Get temporal database
        temporal_db = _get_temporal_db()

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

    except Exception as e:
        logger.error(f"Error searching articles: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def fetch_article(article_id: str) -> str:
    """Fetch full article content with temporal validation.

    Only returns the article if it was published before the LLM's knowledge cutoff.
    This simulates accessing information from the LLM's training data.

    You must call start_forecast_session first.

    Args:
        article_id: ID of the article to fetch

    Returns:
        JSON string with full article content (only if before knowledge cutoff)
    """
    try:
        # Check session context
        if not _current_context.get("cutoff_date"):
            return json.dumps({
                "error": "No active forecast session. Call start_forecast_session first."
            })

        cutoff = _current_context["cutoff_date"]
        logger.info(f"Fetching article {article_id} with cutoff {cutoff.isoformat()}")

        # Get article from temporal database
        temporal_db = _get_temporal_db()
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

    except Exception as e:
        logger.error(f"Error fetching article: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def submit_forecast(
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
        # Check session context
        if not _current_context.get("question_id"):
            return json.dumps({
                "error": "No active forecast session. Call start_forecast_session first."
            })

        question_id = _current_context["question_id"]
        session_id = _current_context["forecast_session_id"]
        cutoff_date = _current_context["cutoff_date"]

        logger.info(f"Submitting forecast for question {question_id}")

        # Get question to validate prediction
        question = db.get(Question, question_id)
        if not question:
            return json.dumps({"error": "Question not found"})

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

    except Exception as e:
        logger.error(f"Error submitting forecast: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_session_info() -> str:
    """Get information about the current forecast session.

    Returns:
        JSON string with session details including knowledge cutoff
    """
    if not _current_context.get("question_id"):
        return json.dumps({
            "active": False,
            "message": "No active forecast session. Call start_forecast_session to begin."
        })

    cutoff = _current_context.get("cutoff_date")
    result = {
        "active": True,
        "session_id": _current_context.get("forecast_session_id"),
        "question_id": _current_context.get("question_id"),
        "knowledge_cutoff_date": cutoff.isoformat() if cutoff else None,
        "note": f"All information is filtered to BEFORE {cutoff.date() if cutoff else 'N/A'}"
    }

    return json.dumps(result, indent=2)




# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point that supports stdio, basic HTTP, and streamable HTTP modes.

    Modes:
        stdio   - (default) MCP over stdio (ideal for local tool integration)
        http    - REST-style MCP HTTP endpoints (FastAPI app)
        stream  - Streamable HTTP (Server-Sent Events) for incremental tool output

    Example:
        python -m src.mcp_forecasting_server --mode stream --host 0.0.0.0 --port 8110
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

    # Adjust logging level if provided
    try:
        from loguru import logger as _lg
        _lg.remove()
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
