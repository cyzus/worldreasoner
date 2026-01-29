"""Main configuration settings and loading logic.

This module provides the main Config class and singleton pattern for
accessing configuration throughout the application.
"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import PROJECT_ROOT, ENV_PREFIX
from .database import DatabaseConfig
from .app import ServerConfig, LLMConfig
from .pipeline import QuestionPipelineConfig


class Config(BaseSettings):
    """Main application configuration.

    Loads from (in order of precedence):
    1. Environment variables (prefix: WORLDREASONER__)
    2. .env file
    3. YAML config files (config.example.yaml + config.yaml overrides)
    4. Default values

    Note: App name and version are defined in pyproject.toml, not here.

    Example env var: WORLDREASONER__DATABASE__DB_PATH=/path/to/db.sqlite
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        extra="ignore",  # Ignore extra fields in config files
    )

    # Application settings
    debug: bool = Field(default=False, description="Debug mode")

    # Component configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    # Pipeline configs (can be overridden)
    question_pipeline: QuestionPipelineConfig = Field(
        default_factory=QuestionPipelineConfig
    )


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML files with override pattern.

    Loads config in this order (later overrides earlier):
    1. config.example.yaml (template with defaults)
    2. config.yaml (gitignored, actual config overrides example)
    3. Environment variables (WORLDREASONER__ prefix)

    Args:
        config_path: Path to YAML config file. If provided, only loads this file.
                     If None, uses the config.example.yaml + config.yaml pattern.

    Returns:
        Loaded configuration with overrides applied

    Example:
        # Load with standard pattern:
        config = load_config()

        # Load custom config:
        config = load_config("config/custom.yaml")
    """
    if config_path is not None:
        # User specified a custom config file
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file) as f:
                config_dict = yaml.safe_load(f) or {}
                return Config(**config_dict)
        return Config()

    # Standard pattern: config.example.yaml + config.yaml (overrides)
    example_config = PROJECT_ROOT / "config" / "config.example.yaml"
    actual_config = PROJECT_ROOT / "config" / "config.yaml"

    # Start with example (template)
    config_dict = {}
    if example_config.exists():
        with open(example_config) as f:
            config_dict = yaml.safe_load(f) or {}

    # Override with actual config (if exists)
    if actual_config.exists():
        with open(actual_config) as f:
            overrides = yaml.safe_load(f) or {}
            # Deep merge: override example values with actual values
            config_dict = _deep_merge(config_dict, overrides)

    return Config(**config_dict)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries.

    Args:
        base: Base dictionary
        override: Override dictionary (takes precedence)

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

# Global config instance (singleton)
_config: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Get global configuration instance (singleton).

    Args:
        reload: If True, reload configuration from file even if already loaded

    Returns:
        Global configuration instance

    Note:
        This uses a singleton pattern for convenience throughout the app.
        For better testability in unit tests, consider using load_config()
        directly and passing config explicitly to components.

    Example:
        config = get_config()
        db = GenericDatabase(config.database.db_path)
    """
    global _config
    if _config is None or reload:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset global config instance.

    Useful for testing to ensure clean state between tests.

    Example:
        def setup_function():
            reset_config()
            # Load test-specific config
            config = load_config("tests/fixtures/test_config.yaml")
    """
    global _config
    _config = None


__all__ = [
    "Config",
    "load_config",
    "get_config",
    "reset_config",
]
