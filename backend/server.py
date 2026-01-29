"""CLI command to start the WorldReasoner API server."""

import argparse
import uvicorn

from src.utils.logging import logger


def main():
    """Start the WorldReasoner API server."""
    parser = argparse.ArgumentParser(description="WorldReasoner API Server")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8018, help="Port to bind to (default: 8018)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level (default: info)",
    )

    args = parser.parse_args()

    logger.info(f"Starting WorldReasoner API server on {args.host}:{args.port}")

    uvicorn.run(
        "backend.api.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
