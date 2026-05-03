"""Runtime helpers for starting the MCP forecasting server."""

import argparse

from fastapi.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from src.utils.logging import logger


def run_server_stdio(mcp) -> None:
    """Run MCP server over stdio (no HTTP, no separate process needed).

    Context is read from environment variables set by the caller:
        WR_QUESTION_ID, WR_SIMULATED_DATE, WR_KNOWLEDGE_CUTOFF,
        WR_SESSION_ID, WR_MODEL_NAME, WR_FORECAST_MODE, WR_DATABASE_PATH
    """
    import asyncio
    mcp.run(transport="stdio")


def run_server(mcp, args: argparse.Namespace) -> None:
    """Create HTTP app, add health route, and run uvicorn."""

    async def health_check(request):
        """Health check endpoint for monitoring server availability."""
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "database": args.db,
                "server_type": "mcp_forecasting",
                "mode": "streamable_http",
            },
        )

    logger.info("Creating FastMCP HTTP app...")
    try:
        app = mcp.http_app(transport="streamable-http")
        logger.info("FastMCP app created successfully")
    except Exception as e:
        logger.error(f"Failed to create FastMCP app: {e}", exc_info=True)
        raise

    logger.info("Adding health check route...")
    app.routes.append(Route("/health", health_check, methods=["GET"]))
    logger.info(f"MCP server app created with {len(app.routes)} routes")

    logger.info(f"Starting uvicorn server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
