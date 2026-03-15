"""Unit tests for MCP forecasting context helpers."""

from contextvars import ContextVar
from datetime import datetime, timezone
from unittest.mock import Mock

from src.api.mcp_forecasting.context import _extract_http_request, get_context_from_mcp
from src.services.forecast_context_service import ForecastContext


def test_extract_http_request_falls_back_to_context_method(monkeypatch):
    """If dependency-based getter is unavailable, fallback to context method."""

    def _raise_runtime_error():
        raise RuntimeError("dependency getter unavailable")

    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_http_request",
        _raise_runtime_error,
        raising=True,
    )

    request = Mock()
    fastmcp_context = Mock()
    fastmcp_context.get_http_request.return_value = request

    assert _extract_http_request(fastmcp_context) is request


def test_get_context_from_mcp_extracts_headers_and_caches_result():
    """Should parse headers from request and cache context in ContextVar."""
    current_context: ContextVar[ForecastContext | None] = ContextVar(
        "forecast_context_test", default=None
    )

    request = Mock()
    request.headers = {
        "X-Question-ID": "q_123",
        "X-Simulated-Date": "2025-03-08",
        "X-Knowledge-Cutoff": "2024-01-01",
    }

    fastmcp_context = Mock()
    fastmcp_context.get_http_request.return_value = request

    ctx = Mock()
    ctx.fastmcp_context = fastmcp_context

    context_service = Mock()
    parsed_context = ForecastContext(
        question_id="q_123",
        simulated_date=datetime(2025, 3, 8, tzinfo=timezone.utc),
        knowledge_cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
        session_id="session_123",
    )
    context_service.parse_context_from_headers.return_value = parsed_context

    result = get_context_from_mcp(
        ctx,
        current_context=current_context,
        context_service=context_service,
    )

    assert result.question_id == "q_123"
    assert current_context.get() is parsed_context
    context_service.parse_context_from_headers.assert_called_once()
    context_service.validate_context.assert_called_once_with(parsed_context)
