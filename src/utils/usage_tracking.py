"""Token and cost usage tracking utilities for LLM calls.

This module provides utilities for tracking token usage and estimated costs
when using LiteLLM through smolagents. It enables:
- Per-agent call tracking
- Pipeline-level aggregation
- Cost estimation using LiteLLM's pricing data
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone
from src.utils.logging import logger


@dataclass
class UsageMetrics:
    """Metrics for a single LLM API call or aggregation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def __add__(self, other: "UsageMetrics") -> "UsageMetrics":
        """Add two usage metrics together for aggregation."""
        return UsageMetrics(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            estimated_cost_usd=self.estimated_cost_usd + other.estimated_cost_usd,
            model=self.model or other.model,  # Keep first non-None model
            timestamp=self.timestamp,  # Keep original timestamp
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "model": self.model,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class UsageTracker:
    """Tracks token usage and costs across multiple LLM calls.

    This class accumulates usage metrics from multiple agent runs
    and provides aggregation and reporting capabilities.

    Usage:
        tracker = UsageTracker(model_name="gpt-4")

        # After each agent run
        metrics = extract_usage_from_agent(agent)
        tracker.add_usage(metrics)

        # Get summary
        summary = tracker.get_summary()
        logger.info(f"Total cost: ${summary.estimated_cost_usd:.4f}")
    """

    def __init__(self, model_name: Optional[str] = None):
        """Initialize usage tracker.

        Args:
            model_name: Optional model name for cost estimation fallback
        """
        self.model_name = model_name
        self.usage_records: List[UsageMetrics] = []
        self.total_calls = 0

    def add_usage(self, metrics: UsageMetrics) -> None:
        """Add usage metrics from a single LLM call.

        Args:
            metrics: Usage metrics to add
        """
        self.usage_records.append(metrics)
        self.total_calls += 1

    def get_summary(self) -> UsageMetrics:
        """Get aggregated usage summary.

        Returns:
            Aggregated usage metrics across all recorded calls
        """
        if not self.usage_records:
            return UsageMetrics(model=self.model_name)

        # Sum all metrics
        summary = UsageMetrics(model=self.model_name or self.usage_records[0].model)
        for record in self.usage_records:
            summary = summary + record

        return summary

    def log_summary(self, context: str = "") -> None:
        """Log usage summary with logger.

        Args:
            context: Optional context string (e.g., "Question Pipeline")
        """
        summary = self.get_summary()
        prefix = f"[{context}] " if context else ""

        logger.info(
            f"{prefix}Token usage: {summary.total_tokens:,} total "
            f"({summary.prompt_tokens:,} prompt + {summary.completion_tokens:,} completion) | "
            f"Estimated cost: ${summary.estimated_cost_usd:.4f} | "
            f"Calls: {self.total_calls}"
        )

    def reset(self) -> None:
        """Reset all tracked usage."""
        self.usage_records.clear()
        self.total_calls = 0


def extract_usage_from_agent(agent, model_name: Optional[str] = None) -> UsageMetrics:
    """Extract token usage metrics from a smolagents agent after execution.

    This function accesses the agent's internal monitor to retrieve token
    counts from the last execution, then estimates costs using LiteLLM.

    Args:
        agent: smolagents agent instance (after calling agent.run())
        model_name: Optional model name for cost estimation

    Returns:
        UsageMetrics with token counts and estimated cost

    Example:
        >>> agent = AgentFactory.create_web_agent(tools=[tool])
        >>> result = agent.run("Search for news")
        >>> metrics = extract_usage_from_agent(agent.agent, model_name="gemini/gemini-2.0-flash-exp")
        >>> logger.info(f"Used {metrics.total_tokens} tokens, cost: ${metrics.estimated_cost_usd:.4f}")
    """
    try:
        import litellm
        # Get token counts from monitor (returns TokenUsage object)
        token_counts = agent.monitor.get_total_token_counts()

        prompt_tokens = token_counts.input_tokens or 0
        completion_tokens = token_counts.output_tokens or 0
        total_tokens = prompt_tokens + completion_tokens

        # Estimate cost using LiteLLM's cost_per_token function
        estimated_cost = 0.0
        if model_name and total_tokens > 0:
            try:
                # Strip litellm_proxy/ prefix if present for cost lookup
                lookup_model = model_name.replace("litellm_proxy/", "")

                # LiteLLM's cost_per_token returns (prompt_cost, completion_cost) in USD
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=lookup_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                estimated_cost = prompt_cost + completion_cost
            except Exception as cost_err:
                logger.debug(
                    f"Could not estimate cost for model '{model_name}': {cost_err}"
                )

        metrics = UsageMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
            model=model_name,
        )

        # Recursively accumulate usage from managed sub-agents
        for sub_agent in getattr(agent, "managed_agents", {}).values():
            sub_model = getattr(sub_agent.model, "model_id", None) or model_name
            sub_metrics = extract_usage_from_agent(sub_agent, model_name=sub_model)
            metrics = metrics + sub_metrics

        return metrics

    except Exception as e:
        logger.error(f"Failed to extract usage from agent: {e}")
        return UsageMetrics(model=model_name)


def log_usage(metrics: UsageMetrics, context: str = "") -> None:
    """Log usage metrics with optional context.

    Args:
        metrics: Usage metrics to log
        context: Optional context string (e.g., "Article Collection")
    """
    prefix = f"[{context}] " if context else ""
    logger.info(
        f"{prefix}Tokens: {metrics.total_tokens:,} "
        f"({metrics.prompt_tokens:,} prompt + {metrics.completion_tokens:,} completion) | "
        f"Cost: ${metrics.estimated_cost_usd:.6f}"
    )
