"""Application-level configuration for WorldReasoner."""

from typing import Optional
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Server configuration for both FastAPI backend and MCP server."""

    # Backend API server (FastAPI)
    host: str = Field(default="localhost", description="Backend API server host")
    port: int = Field(default=8300, description="Backend API server port")

    # MCP forecasting server (used by agents)
    mcp_host: str = Field(default="localhost", description="MCP server host")
    mcp_port: int = Field(default=8301, description="MCP server port")

    reload: bool = Field(default=False, description="Auto-reload on code changes")
    log_level: str = Field(default="info", description="Logging level")


class LLMConfig(BaseModel):
    """LLM configuration for agent interactions."""

    model: str = Field(
        default="gemini/gemini-2.5-flash", description="LiteLLM model identifier"
    )
    embedding_model: str = Field(
        default="gemini/gemini-embedding-001",
        description="LiteLLM embedding model identifier",
    )
    review_model: Optional[str] = Field(
        default=None,
        description="LiteLLM model identifier for event review (optional)",
    )
    temperature: float = Field(
        default=1.0, ge=0.0, le=2.0, description="Sampling temperature"
    )
    frequency_penalty: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Penalizes repeated tokens to reduce repetitive text (0.0=off, 2.0=max). Not supported by all models.",
    )
    presence_penalty: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Penalizes tokens that have appeared at all, encouraging topic diversity",
    )
    max_tokens: Optional[int] = Field(
        default=None, description="Maximum tokens to generate"
    )
    timeout: int = Field(default=60, description="Request timeout in seconds")
