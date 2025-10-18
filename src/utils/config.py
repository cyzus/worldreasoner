"""Configuration management for WorldReasoner."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseModel):
    """Database configuration."""
    
    host: str = "localhost"
    port: int = 5432
    database: str = "worldreasoner"
    username: str = "postgres"
    password: str = ""
    
    def get_url(self) -> str:
        """Get database connection URL."""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
    
    def get_async_url(self) -> str:
        """Get async database connection URL."""
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


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


class Config(BaseSettings):
    """Main application configuration."""
    
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
    
    # Paths
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"


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


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
