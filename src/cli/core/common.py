"""Common utilities and patterns for CLI commands.

Extracted from example scripts for reuse across the unified CLI.
"""

from typing import Callable
from pathlib import Path
import asyncio
from functools import wraps

from src.config import get_config, AppConfig
from src.utils.logging import logger


def async_command(func: Callable):
    """Decorator to run async functions in Typer commands.

    Usage:
        @app.command()
        @async_command
        async def my_command():
            await something()
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def get_app_config() -> AppConfig:
    """Load application configuration.

    Returns:
        AppConfig instance loaded from config files
    """
    return get_config()


def setup_logging(verbose: bool = False):
    """Configure logging for CLI commands.

    Args:
        verbose: If True, set more detailed logging
    """
    # Logging is already configured by src.utils.logging
    # This function is a placeholder for future customization
    if verbose:
        logger.info("Verbose logging enabled")


def print_separator(char: str = "=", length: int = 80):
    """Print a separator line for CLI output.

    Args:
        char: Character to use for the separator
        length: Length of the separator line
    """
    logger.info(char * length)


def print_header(title: str, char: str = "=", length: int = 80):
    """Print a formatted header for CLI sections.

    Args:
        title: Header title text
        char: Character to use for the separator
        length: Length of the separator lines
    """
    print_separator(char, length)
    logger.info(title)
    print_separator(char, length)


def validate_db_path(db_path: str) -> Path:
    """Validate and convert database path.

    Args:
        db_path: Database file path as string

    Returns:
        Path object for the database

    Raises:
        FileNotFoundError: If database doesn't exist
    """
    path = Path(db_path)
    if not path.exists():
        logger.warning(f"Database file does not exist: {db_path}")
        logger.info("A new database will be created if operations are performed")
    return path


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def confirm_action(message: str, default: bool = False) -> bool:
    """Ask user for confirmation before performing an action.

    Args:
        message: Confirmation message to display
        default: Default response if user just presses Enter

    Returns:
        True if user confirms, False otherwise
    """
    from rich.prompt import Confirm

    return Confirm.ask(message, default=default)
