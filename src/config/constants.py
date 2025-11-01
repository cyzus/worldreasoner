"""Project-wide constants.

Essential path constants to avoid hardcoded paths.
"""

from pathlib import Path

# Project root directory (parent of 'src' folder)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Commonly used directories
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Default database path
DEFAULT_DB_PATH = str(PROJECT_ROOT / "worldreasoner.db")

# Environment variable prefix
ENV_PREFIX = "WORLDREASONER__"


__all__ = [
    "PROJECT_ROOT",
    "LOGS_DIR",
    "DEFAULT_DB_PATH",
    "ENV_PREFIX",
]
