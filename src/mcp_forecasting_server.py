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
                    simulated_date = headers.get('x-simulated-date') or headers.get('X-Simulated-Date')
                    model_name = headers.get('x-model-name') or headers.get('X-Model-Name')

                    logger.debug(f"Extracted - question_id: {question_id}, knowledge_cutoff: {knowledge_cutoff}, simulated_date: {simulated_date}, model: {model_name}")

                    # If headers are present, store them globally
                    if question_id and simulated_date:
                        try:
                            # Parse simulated date
                            simulated_date_obj = parse_flexible_datetime(simulated_date)

                            # Parse knowledge cutoff (optional, but recommended)
                            knowledge_cutoff_obj = parse_flexible_datetime(knowledge_cutoff) if knowledge_cutoff else None

                            # Validate question exists
                            question = db.get(Question, question_id)
                            if question:
                                # Validate temporal constraints
                                if simulated_date_obj >= question.resolution_date:
                                    logger.error(
                                        f"Invalid simulated date: {simulated_date_obj.date()} is not before "
                                        f"resolution date {question.resolution_date.date()}"
                                    )
                                    raise ValueError(
                                        f"Simulated date ({simulated_date_obj.date()}) must be BEFORE "
                                        f"the question's resolution date ({question.resolution_date.date()}). "
                                        f"The simulated date represents 'today' in the forecasting scenario."
                                    )

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

                                _connection_context['question_id'] = question_id
                                _connection_context['knowledge_cutoff'] = knowledge_cutoff_obj.isoformat() if knowledge_cutoff_obj else None
                                _connection_context['knowledge_cutoff_obj'] = knowledge_cutoff_obj
                                _connection_context['simulated_date'] = simulated_date_obj.isoformat()
                                _connection_context['simulated_date_obj'] = simulated_date_obj
                                _connection_context['model_name'] = model_name or 'unknown'
                                _connection_context['question'] = question
                                logger.info(
                                    f"Context captured from headers: q={question_id}, "
                                    f"model={model_name or 'unknown'}, "
                                    f"knowledge_cutoff={knowledge_cutoff_obj.date() if knowledge_cutoff_obj else 'N/A'}, "
                                    f"simulated_date={simulated_date_obj.date()}, "
                                    f"resolution_date={question.resolution_date.date()}, "
                                    f"forecast_horizon={(question.resolution_date - simulated_date_obj).days} days"
                                )
                            else:
                                logger.warning(f"Question {question_id} not found in database")
                        except Exception as e:
                            logger.error(f"Error parsing context headers: {e}", exc_info=True)
                    else:
                        logger.debug("No question_id or simulated_date in headers")
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

    Returns TWO important dates:
        - knowledge_cutoff: The LLM's training data cutoff (optional)
        - simulated_date: The simulated "today" for forecasting (required)

    Args:
        ctx: MCP context object (not used, kept for compatibility)

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
    question_id = _connection_context.get('question_id')
    knowledge_cutoff_obj = _connection_context.get('knowledge_cutoff_obj')
    simulated_date_obj = _connection_context.get('simulated_date_obj')
    question = _connection_context.get('question')

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

    # Create session ID
    session_id = f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"

    return {
        "question_id": question_id,
        "knowledge_cutoff": knowledge_cutoff_obj,
        "simulated_date": simulated_date_obj,
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
    # Use the same database path as the global db instance
    return GenericDatabase(db.db_path, cutoff_date=cutoff_date)


# ============================================================================
# Pydantic Models for Parameters
# ============================================================================

class DomainFilter(BaseModel):
    """Domain filter parameter."""
    value: str | None = Field(None, description=f"Optional domain filter ({', '.join(enum_to_list(Domain))})")


class MaxResults(BaseModel):
    """Maximum results parameter."""
    value: int = Field(10, description="Maximum number of results to return", ge=1, le=100)


class Confidence(BaseModel):
    """Confidence parameter."""
    value: float = Field(..., description="Confidence level (0.0 to 1.0)", ge=0.0, le=1.0)


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
                "resolution_date": question.resolution_date.isoformat(),
                # "context": question.context, # The context might leak the answer
                "options": question.options,
                "quantity_unit": question.quantity_unit,
                "target_event_id": question.target_event_id
            },
            "temporal_context": {
                "knowledge_cutoff_date": knowledge_cutoff.isoformat() if knowledge_cutoff else None,
                "simulated_date": simulated_date.isoformat(),
                "resolution_date": question.resolution_date.isoformat(),
                "days_to_forecast": (question.resolution_date - simulated_date).days,
                "explanation": (
                    f"Simulated 'today' is {simulated_date.date()}. "
                    + (f"Your training data cutoff is {knowledge_cutoff.date()}. " if knowledge_cutoff else "")
                )
            },
            "instructions": (
                f"FORECASTING SCENARIO:\n"
                + (f"- Your training data includes information up to: {knowledge_cutoff.date()}\n" if knowledge_cutoff else "")
                + f"- Simulated 'today' date: {simulated_date.date()}\n"
                f"- Event resolution date: {question.resolution_date.date()}\n"
                f"- You must forecast: {(question.resolution_date - simulated_date).days} days into the future\n"
                f"- All article searches will only return information from BEFORE the simulated date\n"
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
    domain: DomainFilter = DomainFilter(),
    max_results: MaxResults = MaxResults()
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

        # Perform hybrid search with temporal filtering
        # Returns article IDs ranked by hybrid score (FTS5 + embeddings)
        article_ids = await hybrid_search.search(
            query=query,
            max_results=max_results.value,
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
                if domain.value and len(article_ids) > max_results.value * 10:
                    domain_filter = parse_domain(domain.value)
                    if domain_filter is not None and article.domain != domain_filter:
                        continue
                matches.append(article)

        # Limit results after domain filtering
        matches = matches[:max_results.value]

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

def graph_reasoning(ctx: Context,
                    source_event: str,
                    target_event: str,
                    relation: str,
                    reasoning: str) -> str:
    pass

def inspect_graph(ctx: Context) -> str:
    pass




@mcp.tool()
def submit_forecast(
    ctx: Context,
    prediction: str,
    confidence: Confidence,
    reasoning: str,
    articles_accessed: ArticlesAccessed = ArticlesAccessed()
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

        # Get model name from context
        model_name = _connection_context.get('model_name', 'unknown')

        forecast = Forecast(
            id=forecast_id,
            session_id=session_id,
            question_id=question_id,
            target_event_id=question.target_event_id,
            prediction=parsed_prediction,
            confidence=confidence.value,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
            simulated_date=simulated_date,
            articles_accessed=articles_accessed.value or [],
            searches_performed=[],  # Could track this if needed
            model_name=model_name,
        )

        # Save forecast to database
        db.save(Forecast, forecast)
        logger.info(f"Forecast saved to database: {forecast_id}")

        result = {
            "forecast_id": forecast_id,
            "question_id": question_id,
            "prediction": parsed_prediction,
            "confidence": confidence.value,
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
    global db, hybrid_search

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

    # Adjust logging level if provided
    try:
        from loguru import logger as _lg
        _lg.remove()
        import sys
        _lg.add(sys.stderr, level=args.log_level.upper())
    except Exception:
        pass

    logger.info(f"Starting MCP STREAMABLE HTTP server on http://{args.host}:{args.port}")
    logger.info("Endpoints: /mcp/tools, /mcp/prompts, SSE streaming available")
    logger.info("Context headers: X-Question-ID, X-Knowledge-Cutoff (optional), X-Simulated-Date (required)")
    import uvicorn
    uvicorn.run(mcp.streamable_http_app, host=args.host, port=args.port)


if __name__ == "__main__":
    import sys
    main()
