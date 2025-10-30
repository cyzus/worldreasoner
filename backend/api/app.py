"""FastAPI application factory for WorldReasoner.

This module creates the FastAPI app with all routes, middleware,
and WebSocket support for real-time graph updates.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.utils.logging import logger
from .routes import graph, events, websocket


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
    )

    # CORS middleware for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
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
