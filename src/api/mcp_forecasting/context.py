"""Context helpers and middleware for MCP forecasting requests."""

from contextvars import ContextVar
from typing import Callable, Optional

from fastmcp.server import Context
from fastmcp.server.middleware import Middleware, MiddlewareContext

from src.services.forecast_context_service import ForecastContext, ForecastContextService
from src.utils.logging import logger


def _extract_http_request(fastmcp_context):
    """Extract HTTP request from FastMCP context across API versions."""
    # New FastMCP API: dependency getter with no args inside request scope.
    try:
        from fastmcp.server.dependencies import get_http_request

        return get_http_request()
    except Exception:
        pass

    # Backward-compatible fallback for older FastMCP versions.
    if hasattr(fastmcp_context, "get_http_request"):
        return fastmcp_context.get_http_request()

    return None


class ForecastContextMiddleware(Middleware):
    """Capture and cache forecasting context from request headers."""

    def __init__(
        self,
        context_service_getter: Callable[[], Optional[ForecastContextService]],
        current_context: ContextVar[Optional[ForecastContext]],
    ):
        self._context_service_getter = context_service_getter
        self._current_context = current_context

    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages to capture headers."""
        logger.debug(f"Middleware processing: {context.method}")

        context_service = self._context_service_getter()
        if context_service is None:
            return await call_next(context)

        if context.fastmcp_context:
            try:
                request = _extract_http_request(context.fastmcp_context)
                if request and hasattr(request, "headers"):
                    headers = {
                        k: v
                        for k, v in request.headers.items()
                        if k.lower().startswith("x-")
                    }
                    logger.debug(
                        f"Request headers available: {list(headers.keys())[:5]}..."
                    )

                    try:
                        forecast_context = context_service.parse_context_from_headers(
                            headers
                        )
                        context_service.validate_context(forecast_context)
                        self._current_context.set(forecast_context)
                        logger.info(
                            f"Context captured: q={forecast_context.question_id}, "
                            f"mode={forecast_context.forecast_mode}, "
                            f"session={forecast_context.session_id[:8]}..., "
                            f"simulated_date={forecast_context.simulated_date.date()}"
                        )
                    except ValueError as e:
                        logger.warning(f"Context parsing/validation failed: {e}")
            except Exception as e:
                logger.debug(f"Could not get HTTP request: {e}")

        return await call_next(context)


def get_context_from_mcp(
    ctx: Context,
    current_context: ContextVar[Optional[ForecastContext]],
    context_service: Optional[ForecastContextService],
) -> ForecastContext:
    """Extract forecasting context from MCP request metadata/headers or env vars."""
    forecast_context = current_context.get()
    if forecast_context:
        return forecast_context

    if context_service is not None:
        # Try HTTP headers first (streamable-http transport)
        try:
            if hasattr(ctx, "fastmcp_context") and ctx.fastmcp_context:
                request = _extract_http_request(ctx.fastmcp_context)
                if request and hasattr(request, "headers"):
                    headers = {
                        k: v
                        for k, v in request.headers.items()
                        if k.lower().startswith("x-")
                    }
                    forecast_context = context_service.parse_context_from_headers(headers)
                    context_service.validate_context(forecast_context)
                    current_context.set(forecast_context)
                    return forecast_context
        except Exception as e:
            logger.debug(f"Could not extract headers from context: {e}")

        # Fallback: environment variables (stdio transport)
        try:
            forecast_context = context_service.parse_context_from_env()
            try:
                context_service.validate_context(forecast_context)
            except ValueError as e:
                logger.warning(f"Context validation warning (proceeding anyway): {e}")
            current_context.set(forecast_context)
            return forecast_context
        except ValueError as e:
            logger.debug(f"Could not extract context from env vars: {e}")

    raise ValueError(
        "Forecasting context not initialized. "
        "Provide X-Question-ID and X-Simulated-Date via HTTP headers (streamable-http) "
        "or WR_QUESTION_ID and WR_SIMULATED_DATE env vars (stdio)."
    )
