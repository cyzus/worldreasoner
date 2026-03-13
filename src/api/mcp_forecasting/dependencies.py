"""Dependency builders for MCP forecasting handlers."""

from typing import Optional

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.services.article_operations_service import ArticleOperationsService
from src.services.forecast_context_service import ForecastContext
from src.tools.inspectors.forecast_graph_inspector import ForecastGraphInspectorTool
from src.tools.reasoning.forecast_causal_reasoner import ForecastCausalReasonerTool
from src.tools.reasoning.forecast_event_identifier import ForecastEventIdentifierTool
from src.utils.logging import logger


def get_db(global_db: GenericDatabase, db_path: Optional[str] = None) -> GenericDatabase:
    """Get a GenericDatabase instance for the given database path."""
    if db_path and db_path != global_db.db_path:
        logger.debug(f"Creating GenericDatabase for custom database: {db_path}")
        return GenericDatabase(db_path)
    return global_db


def get_hybrid_search(
    global_db: GenericDatabase,
    global_hybrid_search: HybridSearch,
    db_path: Optional[str] = None,
) -> HybridSearch:
    """Get a HybridSearch instance for the given database path."""
    if db_path and db_path != global_db.db_path:
        logger.debug(f"Creating HybridSearch for custom database: {db_path}")
        return HybridSearch(db_path)
    return global_hybrid_search


def get_article_service(
    db_instance: GenericDatabase,
    forecast_context: ForecastContext,
    global_db: GenericDatabase,
    global_hybrid_search: HybridSearch,
    article_service_cls=ArticleOperationsService,
) -> ArticleOperationsService:
    """Build ArticleOperationsService with context-aware search backend."""
    search_engine = get_hybrid_search(
        global_db,
        global_hybrid_search,
        forecast_context.db_path,
    )
    return article_service_cls(db_instance, search_engine)


def get_forecast_event_tool(
    db_instance: GenericDatabase,
    forecast_context: ForecastContext,
) -> ForecastEventIdentifierTool:
    """Build forecast event tool with context-aware database settings."""
    return ForecastEventIdentifierTool(
        question_db_path=db_instance.db_path,
        forecast_db_path=forecast_context.db_path or db_instance.db_path,
        session_id=forecast_context.session_id,
    )


def get_forecast_causal_tool(
    db_instance: GenericDatabase,
    forecast_context: ForecastContext,
) -> ForecastCausalReasonerTool:
    """Build forecast causal tool with context-aware database settings."""
    return ForecastCausalReasonerTool(
        forecast_db_path=forecast_context.db_path or db_instance.db_path,
        session_id=forecast_context.session_id,
    )


def get_forecast_graph_tool(
    db_instance: GenericDatabase,
    forecast_context: ForecastContext,
) -> ForecastGraphInspectorTool:
    """Build forecast graph inspector with context-aware database settings."""
    return ForecastGraphInspectorTool(
        forecast_db_path=forecast_context.db_path or db_instance.db_path,
        session_id=forecast_context.session_id,
    )
