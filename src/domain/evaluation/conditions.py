"""Experiment condition definitions for auto-benchmark ablation study.

Defines the 5 experimental conditions used to evaluate forecasting quality
across different agent configurations. Each condition specifies a unique
combination of mode, causal tools, oracle access, and step limits.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional


class ConditionName(str, Enum):
    """Names for the 5 experimental conditions."""

    VANILLA_LLM = "vanilla_llm"
    STRUCTURED_SCENARIO = "structured_scenario"
    SEARCH_ENABLED = "search_enabled"
    WORLDREASONER = "worldreasoner"
    ORACLE = "oracle"
    REAL_TIME = "real_time"


@dataclass(frozen=True)
class ExperimentCondition:
    """Configuration for a single experimental condition.

    Attributes:
        name: Unique condition identifier
        display_name: Human-readable name for reports
        mode: Forecasting mode ('knowledge_only' or 'container')
        enable_causal_tools: Whether causal reasoning tools are available
        is_oracle: Whether to use oracle timing (resolution_date - 1 day)
        max_steps: Maximum agent steps allowed
        description: Brief description for documentation
    """

    name: ConditionName
    display_name: str
    mode: str
    enable_causal_tools: bool
    is_oracle: bool
    max_steps: int
    description: str


EXPERIMENT_CONDITIONS: Dict[ConditionName, ExperimentCondition] = {
    ConditionName.VANILLA_LLM: ExperimentCondition(
        name=ConditionName.VANILLA_LLM,
        display_name="Vanilla LLM",
        mode="knowledge_only",
        enable_causal_tools=False,
        is_oracle=False,
        max_steps=10,
        description="Baseline: LLM forecasts using only training knowledge, no tools",
    ),
    ConditionName.STRUCTURED_SCENARIO: ExperimentCondition(
        name=ConditionName.STRUCTURED_SCENARIO,
        display_name="Structured Scenario",
        mode="knowledge_only",
        enable_causal_tools=True,
        is_oracle=False,
        max_steps=25,
        description="LLM with causal reasoning tools but no external search",
    ),
    ConditionName.SEARCH_ENABLED: ExperimentCondition(
        name=ConditionName.SEARCH_ENABLED,
        display_name="Search-Enabled Agent",
        mode="container",
        enable_causal_tools=False,
        is_oracle=False,
        max_steps=15,
        description="LLM with web search but no causal reasoning structure",
    ),
    ConditionName.WORLDREASONER: ExperimentCondition(
        name=ConditionName.WORLDREASONER,
        display_name="WorldReasoner Agent",
        mode="container",
        enable_causal_tools=True,
        is_oracle=False,
        max_steps=25,
        description="Full system: search + causal reasoning tools",
    ),
    ConditionName.ORACLE: ExperimentCondition(
        name=ConditionName.ORACLE,
        display_name="Oracle Agent",
        mode="container",
        enable_causal_tools=True,
        is_oracle=True,
        max_steps=25,
        description="Full system with near-resolution-date information access",
    ),
    ConditionName.REAL_TIME: ExperimentCondition(
        name=ConditionName.REAL_TIME,
        display_name="Real-Time Search Agent",
        mode="real_time",
        enable_causal_tools=True,
        is_oracle=False,  # We use the live internet instead of MCP temporally restricted internet
        max_steps=25,
        description="Full system using real-time live internet search tools",
    ),
}


def get_conditions(
    filter_names: Optional[List[str]] = None,
) -> List[ExperimentCondition]:
    """Get experiment conditions, optionally filtered by name.

    Args:
        filter_names: If provided, only return conditions with these names.
            Accepts both ConditionName enum values and plain strings.

    Returns:
        List of ExperimentCondition objects in canonical order.

    Raises:
        ValueError: If any filter name is not a valid condition.
    """
    if filter_names is None:
        return list(EXPERIMENT_CONDITIONS.values())

    conditions = []
    for name in filter_names:
        try:
            condition_name = ConditionName(name)
        except ValueError:
            valid = [c.value for c in ConditionName]
            raise ValueError(f"Unknown condition: '{name}'. Valid conditions: {valid}")
        conditions.append(EXPERIMENT_CONDITIONS[condition_name])

    return conditions
