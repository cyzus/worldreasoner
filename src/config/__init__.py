"""Configuration management for WorldReasoner.

Centralized configuration system with:
- SQLite database configuration
- Application and server settings
- LLM configuration for agents
- Pipeline-specific settings
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .database import DatabaseConfig
from .app import ServerConfig, RedisConfig, LLMConfig
from .pipeline import QuestionPipelineConfig, QuestionConfig


class Config(BaseSettings):
    """Main application configuration.
    
    Loads from:
    1. YAML config files (config/default.yaml)
    2. Environment variables (prefix: WORLDREASONER__)
    3. .env file
    
    Example env var: WORLDREASONER__DATABASE__DB_PATH=/path/to/db.sqlite
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WORLDREASONER__",
        env_nested_delimiter="__",
        extra="ignore"  # Ignore extra fields in config files
    )
    
    # Application metadata
    app_name: str = Field(default="worldreasoner", description="Application name")
    version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    
    # Component configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    
    # Paths
    data_dir: Path = Field(
        default_factory=lambda: Path("data"),
        description="Data directory for storing artifacts"
    )
    
    # Pipeline configs (can be overridden)
    question_pipeline: QuestionPipelineConfig = Field(
        default_factory=QuestionPipelineConfig
    )


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file and environment.
    
    Args:
        config_path: Path to YAML config file. If None, uses config/default.yaml
        
    Returns:
        Loaded configuration with environment overrides applied
        
    Example:
        config = load_config("config/custom.yaml")
        db_path = config.database.db_path
    """
    if config_path is None:
        config_path = "config/default.yaml"
    
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file) as f:
            config_dict = yaml.safe_load(f) or {}
            return Config(**config_dict)
    
    # Return default config if file doesn't exist
    return Config()


# Global config instance (singleton pattern)
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
        db = Database(config.database.db_path)
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
    # Main config
    "Config",
    "load_config",
    "get_config",
    "reset_config",
    # Component configs
    "DatabaseConfig",
    "ServerConfig",
    "RedisConfig",
    "LLMConfig",
    "QuestionPipelineConfig",
    "QuestionConfig",  # Alias for backward compatibility
]
