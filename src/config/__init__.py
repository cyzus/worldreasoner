"""Configuration management for WorldReasoner.

Quick Start:
    from src.config import get_config, PROJECT_ROOT, DEFAULT_DB_PATH

    config = get_config()
    db_path = config.database.db_path
"""

# Import constants
from .constants import (
    PROJECT_ROOT,
    LOGS_DIR,
    DEFAULT_DB_PATH,
    ENV_PREFIX,
)

# Import settings
from .settings import (
    Config,
    load_config,
    get_config,
    reset_config,
)

# Import component configs
from .database import DatabaseConfig
from .app import ServerConfig, LLMConfig
from .pipeline import QuestionPipelineConfig


__all__ = [
    # Constants
    "PROJECT_ROOT",
    "LOGS_DIR",
    "DEFAULT_DB_PATH",
    "ENV_PREFIX",
    # Settings
    "Config",
    "load_config",
    "get_config",
    "reset_config",
    # Component configs
    "DatabaseConfig",
    "ServerConfig",
    "LLMConfig",
    "QuestionPipelineConfig",
    "QuestionConfig",
]
