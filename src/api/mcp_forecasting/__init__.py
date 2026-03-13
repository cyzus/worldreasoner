"""Shared modules for the MCP forecasting server."""

from .context import ForecastContextMiddleware, get_context_from_mcp
from .dependencies import (
    get_article_service,
    get_db,
    get_forecast_causal_tool,
    get_forecast_event_tool,
    get_forecast_graph_tool,
    get_hybrid_search,
)
from .runtime import run_server

__all__ = [
    "ForecastContextMiddleware",
    "get_context_from_mcp",
    "get_article_service",
    "get_db",
    "get_forecast_causal_tool",
    "get_forecast_event_tool",
    "get_forecast_graph_tool",
    "get_hybrid_search",
    "run_server",
]
