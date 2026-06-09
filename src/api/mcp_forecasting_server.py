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

Exposed Tools (7 tools):
    1. get_question - Get the current forecast question details
    2. temporal_search_articles - Search articles before simulated date
    3. fetch_article - Fetch full article content (temporally filtered)
    4. identify_forecast_event - Identify/reuse forecast graph events
    5. create_forecast_causal_link - Create forecast causal hypotheses
    6. inspect_forecast_graph - Inspect forecast graph quality/structure
    7. submit_forecast - Submit prediction for the question

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
from typing import Optional, Union
from contextvars import ContextVar

from fastmcp import FastMCP
from fastmcp.server import Context

# Import WorldReasoner components
from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.domain.models import Forecast
from src.utils.logging import logger
from src.utils.enums import serialize_domain
from src.analysis.graph_analysis import resolve_target_event_id

# Import services
from src.services.forecast_context_service import (
    ForecastContextService,
    ForecastContext,
)
from src.services.article_operations_service import ArticleOperationsService
from src.services.forecast_submission_service import ForecastSubmissionService
from src.api.mcp_forecasting.context import (
    ForecastContextMiddleware,
    get_context_from_mcp,
)
from src.api.mcp_forecasting.dependencies import (
    get_article_service,
    get_db,
    get_forecast_causal_tool,
    get_forecast_event_tool,
    get_forecast_graph_tool,
    get_hybrid_search,
)
from src.core.alias_registry import AliasRegistry
from src.api.mcp_forecasting.runtime import run_server, run_server_stdio
from src.tools.base.output_models import (
    ErrorResponse,
    FetchArticleResponse,
    ForecastEventOutput,
    ForecastHypothesisOutput,
    GetQuestionResponse,
    QuestionInfo,
    SearchArticleItem,
    SubmitForecastResponse,
    TemporalContextInfo,
    TemporalSearchArticlesResponse,
)

# Initialize MCP server
mcp = FastMCP("worldreasoner-forecasting")

# Global database connection and search engine
DB_PATH = os.getenv("WORLDREASONER_DB", "worldreasoner.db")
db: GenericDatabase = None  # Will be initialized in main()
hybrid_search: HybridSearch = None  # Will be initialized in main()

# Global services (initialized in main())
context_service: ForecastContextService = None
article_service: ArticleOperationsService = None
forecast_service: ForecastSubmissionService = None

# Context variable for storing forecast context (replaces global dict)
_current_context: ContextVar[Optional[ForecastContext]] = ContextVar(
    "forecast_context", default=None
)

# Per-session alias registries for propose_forecast_subgraph (keyed by session_id)
_alias_registries: dict[str, AliasRegistry] = {}


# ============================================================================
# Middleware to capture connection headers
# ============================================================================


# Add middleware to capture headers
mcp.add_middleware(
    ForecastContextMiddleware(
        context_service_getter=lambda: context_service,
        current_context=_current_context,
    )
)


# ============================================================================
# Helper Functions
# ============================================================================


def _get_context_from_mcp(ctx: Context) -> ForecastContext:
    """Extract forecasting context from MCP request metadata/headers.

    First checks ContextVar for cached context, then tries to extract
    directly from request headers if not found.

    Args:
        ctx: MCP context object

    Returns:
        ForecastContext object

    Raises:
        ValueError: If required context not found or invalid
    """
    return get_context_from_mcp(
        ctx,
        current_context=_current_context,
        context_service=context_service,
    )


def _get_db(db_path: Optional[str] = None) -> GenericDatabase:
    """Get a GenericDatabase instance for the given database."""
    return get_db(db, db_path)


def _get_hybrid_search(db_path: Optional[str] = None) -> HybridSearch:
    """Get a HybridSearch instance for the given database."""
    return get_hybrid_search(db, hybrid_search, db_path)


def _get_article_service(
    db_instance: GenericDatabase, forecast_context: ForecastContext
) -> ArticleOperationsService:
    """Get an ArticleOperationsService instance for the given database and context.

    Args:
        db_instance: Database instance
        forecast_context: Forecast context

    Returns:
        ArticleOperationsService instance
    """
    return get_article_service(
        db_instance=db_instance,
        forecast_context=forecast_context,
        global_db=db,
        global_hybrid_search=hybrid_search,
        article_service_cls=ArticleOperationsService,
    )


def _get_forecast_event_tool(
    db_instance: GenericDatabase, forecast_context: ForecastContext
) -> object:
    """Build forecast event tool with context-aware database settings."""
    return get_forecast_event_tool(db_instance, forecast_context)


def _get_forecast_causal_tool(
    db_instance: GenericDatabase, forecast_context: ForecastContext
) -> object:
    """Build forecast causal tool with context-aware database settings."""
    return get_forecast_causal_tool(db_instance, forecast_context)


def _get_forecast_graph_tool(
    db_instance: GenericDatabase, forecast_context: ForecastContext
) -> object:
    """Build forecast graph inspector with context-aware database settings."""
    return get_forecast_graph_tool(db_instance, forecast_context)


# ============================================================================
# MCP Tools
# ============================================================================


@mcp.tool()
def get_question(ctx: Context) -> GetQuestionResponse | ErrorResponse:
    """Get details about the current forecasting question.

    This returns the question you need to forecast, along with temporal context
    showing your knowledge cutoff date, the simulated "today" date, and how far
    into the future you're forecasting.

    Returns:
        Structured question details and temporal context
    """
    try:
        # Get context
        forecast_context = _get_context_from_mcp(ctx)

        # Load question using service (optionally passing db)
        question = context_service.get_question_for_context(forecast_context)
        question_metadata = question.metadata or {}
        response_options = question.options
        if response_options is None:
            metadata_options = question_metadata.get("options")
            if isinstance(metadata_options, list):
                response_options = metadata_options

        response_quantity_unit = question.quantity_unit
        if response_quantity_unit is None:
            metadata_quantity_unit = question_metadata.get("quantity_unit")
            if isinstance(metadata_quantity_unit, str):
                response_quantity_unit = metadata_quantity_unit

        return GetQuestionResponse(
            question=QuestionInfo(
                id=question.id,
                question_text=question.question_text,
                question_type=question.question_type.value,
                domain=serialize_domain(question.domain),
                difficulty=question.difficulty,
                options=response_options,
                quantity_unit=response_quantity_unit,
            ),
            temporal_context=TemporalContextInfo(
                knowledge_cutoff_date=forecast_context.knowledge_cutoff.isoformat()
                if forecast_context.knowledge_cutoff
                else None,
                **{"today's date": forecast_context.simulated_date.isoformat()},
                explanation=(
                    f"'today' is {forecast_context.simulated_date.date()}. "
                    + (
                        f"Your training data cutoff is {forecast_context.knowledge_cutoff.date()}. "
                        if forecast_context.knowledge_cutoff
                        else ""
                    )
                ),
            ),
            instructions=(
                "FORECASTING SCENARIO:\n"
                + (
                    f"- Your training data includes information up to: {forecast_context.knowledge_cutoff.date()}\n"
                    if forecast_context.knowledge_cutoff
                    else ""
                )
                + f"- 'today' date: {forecast_context.simulated_date.date()}\n"
                f"- Approximate event resolution date: {question.resolution_date.date()}\n"
                f"- You must forecast: around {(question.resolution_date - forecast_context.simulated_date).days} days into the future\n"
                f"- All article searches will only return information from BEFORE today\n"
                f"- This tests your ability to make genuine predictions about future events"
            ),
        )

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return ErrorResponse(error=str(e))
    except Exception as e:
        logger.error(f"Error getting question: {e}")
        return ErrorResponse(error=str(e))


@mcp.tool()
async def temporal_search_articles(
    ctx: Context, query: str, domain: str = None, max_results: int = 10
) -> TemporalSearchArticlesResponse | ErrorResponse:
    """Search for articles with temporal filtering using hybrid search.

    Find the most relevant articles published BEFORE the simulated date.

    Returns:
        Structured article summaries from before the simulated date
    """
    try:
        # Get context
        forecast_context = _get_context_from_mcp(ctx)

        # Get appropriate database
        db_instance = _get_db(forecast_context.db_path)

        # Create article service with appropriate database and search engine
        article_ops = _get_article_service(db_instance, forecast_context)

        # Perform search
        articles = await article_ops.search_articles(
            query=query,
            simulated_date=forecast_context.simulated_date,
            domain=domain,
            max_results=max_results,
            question_id=forecast_context.question_id,
        )

        # Format response
        return TemporalSearchArticlesResponse(
            query=query,
            simulated_date=forecast_context.simulated_date.isoformat(),
            note=(
                "Only showing articles from BEFORE the simulated date "
                f"({forecast_context.simulated_date.date()})"
            ),
            count=len(articles),
            articles=[
                SearchArticleItem(
                    id=article.id,
                    title=article.title,
                    url=article.url,
                    source=article.source,
                    domain=serialize_domain(article.domain),
                    published_date=article.published_date.isoformat(),
                    word_count=article.word_count,
                    excerpt=article.content[:300] + "..."
                    if len(article.content) > 300
                    else article.content,
                )
                for article in articles
            ],
        )

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return ErrorResponse(error=str(e))
    except Exception as e:
        logger.error(f"Error searching articles: {e}")
        return ErrorResponse(error=str(e))


@mcp.tool()
def fetch_article(ctx: Context, article_id: str) -> FetchArticleResponse | ErrorResponse:
    """Fetch full article content with temporal validation.

    Only returns the article if it was published before the simulated date.

    Returns:
        Structured full article content (only if before simulated date)
    """
    try:
        # Get context
        forecast_context = _get_context_from_mcp(ctx)

        # Get appropriate database
        db_instance = _get_db(forecast_context.db_path)

        # Create article service with appropriate database
        article_ops = _get_article_service(db_instance, forecast_context)

        # Fetch article using service
        try:
            article = article_ops.fetch_article(
                article_id, forecast_context.simulated_date
            )
        except ValueError as e:
            return ErrorResponse(error=str(e))

        if not article:
            return ErrorResponse(
                error=(
                    f"Article {article_id} not found or published after simulated date"
                )
            )

        # Return full article
        return FetchArticleResponse(
            id=article.id,
            title=article.title,
            url=article.url,
            source=article.source,
            domain=serialize_domain(article.domain),
            published_date=article.published_date.isoformat(),
            author=article.author,
            word_count=article.word_count,
            tags=article.tags,
            content=article.content[:2000] + "..."
            if len(article.content) > 2000
            else article.content,
            event_ids=article.event_ids,
        )

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return ErrorResponse(error=str(e))
    except Exception as e:
        logger.error(f"Error fetching article: {e}")
        return ErrorResponse(error=str(e))


@mcp.tool()
def identify_forecast_event(
    ctx: Context,
    title: str,
    description: str,
    occurred_date: str,
    domain: str = None,
    event_type: str = None,
    source_article_ids: str = None,
) -> ForecastEventOutput | ErrorResponse:
    """Identify event for forecast reasoning.

    Use this tool to identify and record events that are relevant to your forecast.

    Args:
        title: Short event title
        description: Detailed event description
        occurred_date: When event occurred (ISO format with timezone)
        domain: Event domain (optional, defaults to 'general')
        event_type: Optional event type
        source_article_ids: Optional comma-separated article IDs

    Returns:
        Event details with status (created or reused)
    """
    try:
        forecast_context = _get_context_from_mcp(ctx)
        db_instance = _get_db(forecast_context.db_path)
        tool = _get_forecast_event_tool(db_instance, forecast_context)

        return tool.forward(
            title, description, occurred_date, domain, event_type, source_article_ids
        )
    except Exception as e:
        logger.error(f"Error identifying forecast event: {e}")
        return ErrorResponse(error=str(e))


@mcp.tool()
def create_forecast_causal_link(
    ctx: Context,
    source_event_id: str,
    target_event_id: str,
    relation_type: str,
    strength: float,
    confidence: float,
    reasoning: str,
    evidence_article_ids: str = "",
) -> ForecastHypothesisOutput | ErrorResponse:
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
        Hypothesis details with ID and relation
    """
    try:
        forecast_context = _get_context_from_mcp(ctx)
        db_instance = _get_db(forecast_context.db_path)
        tool = _get_forecast_causal_tool(db_instance, forecast_context)

        return tool.forward(
            source_event_id,
            target_event_id,
            relation_type,
            strength,
            confidence,
            reasoning,
            evidence_article_ids,
        )
    except Exception as e:
        logger.error(f"Error creating forecast causal link: {e}")
        return ErrorResponse(error=str(e))


@mcp.tool()
def inspect_forecast_graph(ctx: Context) -> str:
    """Inspect forecast's causal reasoning graph.

    Use this tool to check the quality and structure of your causal reasoning graph.

    Returns:
        JSON with graph statistics and quality feedback
    """
    try:
        forecast_context = _get_context_from_mcp(ctx)
        db_instance = _get_db(forecast_context.db_path)
        tool = _get_forecast_graph_tool(db_instance, forecast_context)

        return tool.forward()
    except Exception as e:
        logger.error(f"Error inspecting forecast graph: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def delete_forecast_event(ctx: Context, event_id: str) -> str:
    """Delete a forecast event and all its causal links.

    Use this to correct mistakes such as duplicated events, wrong date, or
    misidentified events. All causal links referencing this event are also removed.

    Args:
        ctx: MCP context
        event_id: ID of the forecast event to delete

    Returns:
        JSON confirmation with deleted event and hypothesis counts
    """
    try:
        from src.tools.reasoning.forecast_delete_event import ForecastDeleteEventTool
        forecast_context = _get_context_from_mcp(ctx)
        tool = ForecastDeleteEventTool(
            forecast_db_path=forecast_context.db_path or db.db_path,
            session_id=forecast_context.session_id,
        )
        return tool.forward(event_id)
    except Exception as e:
        logger.error(f"Error deleting forecast event: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def delete_forecast_hypothesis(ctx: Context, source_event_id: str, target_event_id: str) -> str:
    """Delete a causal link between two forecast events.

    Use this to correct mistakes such as wrong direction, incorrect relation type,
    or accidental duplicate links.

    Args:
        ctx: MCP context
        source_event_id: ID of the causing event
        target_event_id: ID of the caused event

    Returns:
        JSON confirmation with deleted hypothesis ID
    """
    try:
        from src.tools.reasoning.forecast_delete_hypothesis import ForecastDeleteHypothesisTool
        forecast_context = _get_context_from_mcp(ctx)
        tool = ForecastDeleteHypothesisTool(
            forecast_db_path=forecast_context.db_path or db.db_path,
            session_id=forecast_context.session_id,
        )
        return tool.forward(source_event_id, target_event_id)
    except Exception as e:
        logger.error(f"Error deleting forecast hypothesis: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def propose_forecast_subgraph(ctx: Context, subgraph_json: str) -> str:
    """Batch-create forecast events and causal links in a single call.

    More efficient than calling identify_forecast_event and
    create_forecast_causal_link separately for each node/edge.

    Args:
        subgraph_json: JSON string with schema:
            {
              "events": [
                {
                  "alias": "E1",           // short alias used in edges below
                  "title": "Event title",
                  "description": "What happened",
                  "domain": "politics",    // politics/economics/technology/science/sports/culture
                  "occurred_date": "2024-03-15",  // ISO date or datetime
                  "event_type": "development"     // optional
                }
              ],
              "edges": [
                {
                  "source": "E1",          // alias or existing event UUID
                  "target": "E2",
                  "relation": "causes",    // causes/enables/amplifies/triggers/prevents/inhibits
                  "strength": 0.8,         // 0-1
                  "confidence": 0.7,       // 0-1
                  "reasoning": "Because..."
                }
              ]
            }

    Returns:
        JSON with events_created, edges_created, failed_items, and alias_map
        (alias_map maps each alias to the created UUID for reference)
    """
    try:
        from src.tools.reasoning.propose_subgraph import ProposeSubgraphTool
        forecast_context = _get_context_from_mcp(ctx)
        db_instance = _get_db(forecast_context.db_path)

        session_id = forecast_context.session_id
        if session_id not in _alias_registries:
            _alias_registries[session_id] = AliasRegistry()
        alias_registry = _alias_registries[session_id]

        event_tool = _get_forecast_event_tool(db_instance, forecast_context)
        causal_tool = _get_forecast_causal_tool(db_instance, forecast_context)

        tool = ProposeSubgraphTool(
            event_identifier_tool=event_tool,
            causal_reasoner_tool=causal_tool,
            alias_registry=alias_registry,
            db_path=forecast_context.db_path or db_instance.db_path,
        )
        result = tool.forward(subgraph_json)
        import json as _json
        if hasattr(result, "model_dump"):
            return _json.dumps(result.model_dump())
        return str(result)
    except Exception as e:
        logger.error(f"Error in propose_forecast_subgraph: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def submit_forecast(
    ctx: Context,
    prediction: Union[str, float, int],
    confidence: float,
    reasoning: str,
    articles_accessed: list[str],
) -> SubmitForecastResponse | ErrorResponse:
    """Submit a forecast for the current question.

    This records your prediction about a future event, based only on information
    available before the simulated date.

    Args:
        ctx: MCP context
        prediction: Predicted outcome (string, number, or boolean "True"/"False")
        confidence: Confidence level as a float between 0.0 and 1.0 (e.g., 0.85).
                   Values > 1.0 will be automatically normalized (divided by 100).
        reasoning: Detailed explanation of the prediction
        articles_accessed: List of article IDs used as evidence

    Returns:
        Structured forecast submission confirmation with forecast_id.

    Note on evaluation:
        Scoring (is_correct, brier_score, log_score) happens separately after
        the question resolves and ground_truth is set. To score:
          CLI:  uv run wr benchmark evaluate --db <db>
          API:  POST /api/evaluation/run
          View: GET  /api/questions/<question_id>/forecasts
    """
    try:
        # Get context
        forecast_context = _get_context_from_mcp(ctx)
        db_instance = _get_db(forecast_context.db_path)
        question = context_service.get_question_for_context(forecast_context)

        logger.info(f"Submitting forecast for question {forecast_context.question_id}")

        # Auto-normalize confidence if agent provided a percentage (0-100) instead of 0-1
        if confidence > 1.0:
            original_conf = confidence
            confidence = confidence / 100.0
            logger.warning(f"Normalizing confidence from {original_conf} to {confidence}")

        # Ensure prediction is a string
        prediction_str = str(prediction)

        # Validate prediction
        valid, parsed_prediction, error = forecast_service.validate_prediction(
            question, prediction_str
        )
        if not valid:
            return ErrorResponse(error=error)

        # Build evaluation metadata (benchmark tagging) before saving
        eval_meta = None
        benchmark_condition = os.environ.get("WR_BENCHMARK_CONDITION")
        if benchmark_condition:
            eval_meta = {
                "benchmark_condition": benchmark_condition,
                "benchmark_model": forecast_context.model_name,
            }

        # Create and save forecast (with metadata in a single write)
        forecast = forecast_service.create_forecast(
            question_id=forecast_context.question_id,
            session_id=forecast_context.session_id,
            prediction=parsed_prediction,
            confidence=confidence,
            reasoning=reasoning,
            articles_accessed=articles_accessed or [],
            simulated_date=forecast_context.simulated_date,
            target_event_id=resolve_target_event_id(question, db_instance),
            model_name=forecast_context.model_name,
            mode=forecast_context.forecast_mode,
            db_path=forecast_context.db_path,
            evaluation_metadata=eval_meta,
        )

        # Link graph elements
        graph_counts = forecast_service.link_forecast_graph(
            forecast.id, forecast_context.session_id, forecast_context.db_path
        )

        return SubmitForecastResponse(
            forecast_id=forecast.id,
            question_id=forecast_context.question_id,
            prediction=parsed_prediction,
            confidence=confidence,
            simulated_date=forecast_context.simulated_date.isoformat(),
            submitted_at=forecast.timestamp.isoformat(),
            status="submitted",
            graph_links=graph_counts,
            note=(
                "Forecast submitted! You predicted based on information from before "
                f"the simulated date ({forecast_context.simulated_date.date()}). "
                f"The actual outcome will be known on {question.resolution_date.date()}."
            ),
        )

    except ValueError as e:
        logger.error(f"Context error: {e}")
        return ErrorResponse(error=str(e))
    except Exception as e:
        logger.error(f"Error submitting forecast: {e}")
        return ErrorResponse(error=str(e))


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
        """,
    )
    parser.add_argument(
        "--db",
        default=DB_PATH,
        help="Path to WorldReasoner database (default: worldreasoner.db)",
    )
    parser.add_argument(
        "--transport",
        default="http",
        choices=["http", "stdio"],
        help="Transport: 'http' (default, streamable-http) or 'stdio' (no server needed)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)"
    )
    parser.add_argument("--port", type=int, default=8110, help="Port (default: 8110)")
    parser.add_argument(
        "--log-level",
        default="debug",
        help="Logging level: debug|info|warning|error (default: debug)",
    )
    global db, hybrid_search, context_service, article_service, forecast_service

    args = parser.parse_args()
    db = GenericDatabase(args.db)
    # Ensure forecasts table exists (idempotent)
    db.create_table(Forecast)

    # HybridSearch loads embedding_model from config.yaml by default
    hybrid_search = HybridSearch(args.db)

    # Initialize services
    context_service = ForecastContextService(db)
    article_service = ArticleOperationsService(db, hybrid_search)
    forecast_service = ForecastSubmissionService(db)
    logger.info("Initialized forecasting services")

    if args.transport == "stdio":
        logger.info(f"Launching MCP server (stdio mode) db={args.db}")
        logger.info("Forecasting context read from env vars: WR_QUESTION_ID, WR_SIMULATED_DATE, ...")
        run_server_stdio(mcp=mcp)
    else:
        logger.info(f"Launching MCP server (stream mode) db={args.db}")
        logger.info("Forecasting context will be provided by MCP client via headers:")
        logger.info("  - X-Question-ID (required)")
        logger.info("  - X-Knowledge-Cutoff (optional)")
        logger.info("  - X-Simulated-Date (required)")
        logger.info(
            f"Starting MCP STREAMABLE HTTP server on http://{args.host}:{args.port}"
        )
        run_server(mcp=mcp, args=args)


if __name__ == "__main__":
    main()
