"""Configuration management for WorldReasoner."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseModel):
    """Database configuration."""
    
    # Connection settings
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(default="worldreasoner", description="Database name")
    username: str = Field(default="postgres", description="Database user")
    password: str = Field(default="", description="Database password")
    
    # Connection pool settings
    min_connections: int = Field(default=1, description="Minimum pool connections")
    max_connections: int = Field(default=10, description="Maximum pool connections")
    
    # Optional settings
    ssl_mode: Optional[str] = Field(default=None, description="SSL mode (disable, require, verify-full)")
    db_schema: str = Field(default="public", description="Database schema")
    
    # Performance settings
    batch_size: int = Field(default=100, description="Batch insert size")
    
    def get_url(self) -> str:
        """Get database connection URL (sync).
        
        Returns:
            Connection string for psycopg or SQLAlchemy
        """
        conn_str = f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
        if self.ssl_mode:
            conn_str += f"?sslmode={self.ssl_mode}"
        return conn_str
    
    def get_async_url(self) -> str:
        """Get async database connection URL.
        
        Returns:
            Connection string for asyncpg or async SQLAlchemy
        """
        return self.get_url().replace("postgresql://", "postgresql+asyncpg://")
    
    # Aliases for compatibility
    def get_connection_string(self) -> str:
        """Alias for get_url()."""
        return self.get_url()
    
    def get_async_connection_string(self) -> str:
        """Alias for get_async_url()."""
        return self.get_async_url()


class RedisConfig(BaseModel):
    """Redis cache configuration."""
    
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class ServerConfig(BaseModel):
    """MCP server configuration."""
    
    host: str = "localhost"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


class LLMConfig(BaseModel):
    """LLM configuration."""
    
    model: str = "gemini/gemini-2.5-flash"
    temperature: float = 1.0
    max_tokens: Optional[int] = None


class Config(BaseSettings):
    """Main application configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore"  # Ignore extra fields in config files
    )
    
    # Application
    app_name: str = "worldreasoner"
    version: str = "0.1.0"
    debug: bool = False
    
    # Database
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    
    # Redis
    redis: RedisConfig = Field(default_factory=RedisConfig)
    
    # Server
    server: ServerConfig = Field(default_factory=ServerConfig)
    
    # LLM
    llm: LLMConfig = Field(default_factory=LLMConfig)
    
    # Paths
    data_dir: Path = Field(default_factory=lambda: Path("data"))


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file and environment.
    
    Args:
        config_path: Path to YAML config file. If None, uses default.yaml
        
    Returns:
        Loaded configuration
    """
    if config_path is None:
        config_path = "config/default.yaml"
    
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file) as f:
            config_dict = yaml.safe_load(f)
            return Config(**config_dict)
    
    # Return default config
    return Config()


# Global config instance (singleton pattern)
_config: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Get global configuration instance.
    
    Args:
        reload: If True, reload configuration from file even if already loaded
        
    Returns:
        Global configuration instance
        
    Note:
        This uses a singleton pattern for convenience. For better testability,
        consider using load_config() directly and passing config explicitly.
    """
    global _config
    if _config is None or reload:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset global config instance (useful for testing)."""
    global _config
    _config = None
