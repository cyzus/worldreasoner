"""Centralized logging configuration using loguru.

Simple, elegant logging setup for WorldReasoner.
All modules can just import logger and use it.
"""

import sys
from loguru import logger
from pathlib import Path


def _shorten_name(record):
    """Filter to shorten module names in logs."""
    record["extra"]["short_name"] = record["name"].split(".")[-1]
    return record


def setup_logging(
    level: str = "INFO",
    log_file: str = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
) -> None:
    """Configure loguru logger with sensible defaults.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file. If None, uses default from constants
        rotation: When to rotate log file
        retention: How long to keep old logs
    """
    # Use default log file pattern if not specified
    if log_file is None:
        from src.config import LOGS_DIR

        log_file = str(LOGS_DIR / "worldreasoner_{time}.log")

    # Remove default handler
    logger.remove()

    # Add console handler with nice formatting
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[short_name]:<20}</cyan> - <level>{message}</level>",
        level=level,
        colorize=True,
        filter=_shorten_name,
    )

    # Add file handler with rotation
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=level,
        rotation=rotation,
        retention=retention,
        compression="zip",
    )

    logger.info(f"Logging initialized at level {level}")


# Auto-configure on import with defaults
setup_logging()


__all__ = ["logger", "setup_logging"]
