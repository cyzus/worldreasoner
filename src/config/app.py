"""Application-level configuration for WorldReasoner."""

from typing import Optional
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """MCP server configuration."""
    
    host: str = Field(default="localhost", description="Server host")
    port: int = Field(default=8018, description="Server port")
    reload: bool = Field(default=False, description="Auto-reload on code changes")
    log_level: str = Field(default="info", description="Logging level")


class LLMConfig(BaseModel):
    """LLM configuration for agent interactions."""
    
    model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="LiteLLM model identifier"
    )
    temperature: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Maximum tokens to generate"
    )
    timeout: int = Field(
        default=60,
        description="Request timeout in seconds"
    )
