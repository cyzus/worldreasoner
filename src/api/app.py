"""FastAPI application factory for WorldReasoner.

This module creates the FastAPI app with all routes, middleware,
and WebSocket support for real-time graph updates.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.utils.logging import logger
from .routes import (
    graph,
    events,
    websocket,
    questions,
    database,
    pipelines,
    forecast_graphs,
    search,
    evaluation,
    monitor,
    outcomes,
    benchmark,
)
from src.core.database import GenericDatabase
from src.config import get_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events.

    This handles:
    - Starting the MCP forecasting server on backend startup
    - Stopping the MCP forecasting server on backend shutdown
    """
    # Startup: Initialize MCP server with current database
    logger.info("Backend starting up...")

    try:
        # Ensure all database tables exist at startup
        try:
            cfg = get_config()
            db = GenericDatabase(cfg.database.db_path)
            tables = db.initialize_all_tables()
            logger.info(f"Database initialized. Ensured {tables} tables exist.")

            # Migrate: ensure new columns exist on older databases
            from src.domain.models import Forecast, Question

            db.ensure_column(Forecast, "enabled_tools", "TEXT")
            db.ensure_column(Question, "causal_explanation", "TEXT")
            db.ensure_column(Question, "graph_built", "INTEGER")
            db.ensure_column(Question, "graph_build_error", "TEXT")
        except Exception as e:
            logger.warning(f"Failed to initialize database tables on startup: {e}")

        import os

        # Backfill ground truth for Polymarket questions that have resolved since
        # ingestion. Non-fatal; skip with POLYMARKET_REFRESH_ON_STARTUP=false.
        refresh_enabled = os.getenv(
            "POLYMARKET_REFRESH_ON_STARTUP", "true"
        ).lower() in ("true", "1", "yes")
        if refresh_enabled:
            try:
                from src.pipelines.collection import refresh_polymarket_ground_truth
                from .routes.database import get_current_db_path

                refresh_db = GenericDatabase(get_current_db_path())
                logger.info("Refreshing Polymarket ground truth on startup...")
                refresh_result = await refresh_polymarket_ground_truth(refresh_db)
                logger.info(
                    f"Polymarket refresh: {refresh_result.updated} resolved, "
                    f"{refresh_result.still_unresolved} still open "
                    f"(of {refresh_result.candidates} unresolved)."
                )
            except Exception as e:
                logger.warning(f"Polymarket ground-truth refresh on startup failed: {e}")
        else:
            logger.info("Polymarket startup refresh disabled (POLYMARKET_REFRESH_ON_STARTUP=false)")

        from .routes.database import mcp_manager, get_current_db_path

        # Check if auto-start is enabled (default: True)
        auto_start = os.getenv("MCP_AUTO_START", "true").lower() in ("true", "1", "yes")

        if auto_start:
            current_db = get_current_db_path()
            logger.info(f"Initializing MCP server with database: {current_db}")

            try:
                # start_server will check health and skip restart if already healthy
                mcp_manager.start_server(current_db, auto_restart=True)
                logger.info("MCP server initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to start MCP server on startup: {e}")
                logger.warning(
                    "MCP server can be started manually or will auto-start on database switch"
                )
        else:
            logger.info("MCP auto-start disabled (MCP_AUTO_START=false)")
            logger.info("MCP server will auto-start on first database switch")
    except Exception as e:
        logger.error(f"Error during startup: {e}")

    yield  # App is running

    # Shutdown: Stop MCP server
    logger.info("Backend shutting down...")

    try:
        from .routes.database import mcp_manager

        if mcp_manager.is_running:
            logger.info("Stopping MCP server...")
            mcp_manager.stop_server()
            logger.info("MCP server stopped")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    logger.info("Creating WorldReasoner API application...")

    app = FastAPI(
        title="WorldReasoner API",
        description="API for causal graph visualization and forecasting benchmarks",
        version="0.1.0",
        lifespan=lifespan,
    )

    frontend_port = os.getenv("FRONTEND_PORT", "5173")
    frontend_host = os.getenv("FRONTEND_HOST", "localhost")
    cors_origins = {
        f"http://{frontend_host}:{frontend_port}",
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
    }

    # CORS middleware for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(cors_origins),  # React dev servers
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(database.router, prefix="/api/database", tags=["database"])
    app.include_router(search.router, prefix="/api/search", tags=["search"])
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(questions.router, prefix="/api/questions", tags=["questions"])
    app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
    app.include_router(forecast_graphs.router, prefix="/api", tags=["forecast-graphs"])
    app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
    app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])
    app.include_router(outcomes.router, prefix="/api/outcomes", tags=["outcomes"])
    app.include_router(benchmark.router, prefix="/api/benchmark", tags=["benchmark"])
    app.include_router(websocket.router, prefix="/ws", tags=["websocket"])

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "WorldReasoner API",
            "version": "0.1.0",
            "docs": "/docs",
        }

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    return app
