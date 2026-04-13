"""CLI command to start the WorldReasoner API server."""

import argparse
import uvicorn

from src.utils.logging import logger
from src.config import get_config


def main():
    """Start the WorldReasoner API server."""
    config = get_config()

    parser = argparse.ArgumentParser(description="WorldReasoner API Server")
    parser.add_argument(
        "--host",
        default=config.server.host,
        help=f"Host to bind to (default: {config.server.host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.server.port,
        help=f"Port to bind to (default: {config.server.port})",
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
        "src.api.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
