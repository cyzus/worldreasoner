from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
import json

from smolagents import CodeAgent, ToolCallingAgent, LiteLLMModel, ActionStep, TaskStep
from src.config import Config, get_config
from src.utils.usage_tracking import UsageMetrics, extract_usage_from_agent
from src.utils.logging import logger


def _uses_structured_outputs(model_id: str) -> bool:
    lowered = model_id.lower()
    return "gemini" in lowered


def create_llm_model(
    config: Config,
    model_id: str = None,
    temperature: float = None,
) -> LiteLLMModel:
    """Create a LiteLLMModel from config. Single source of truth for model construction."""
    extra = config.llm.model_dump(
        exclude={"model", "embedding_model", "review_model", "temperature"},
        exclude_none=True,
    )
    if temperature is not None:
        extra["temperature"] = temperature
    return LiteLLMModel(model_id=model_id or config.llm.model, num_retries=3, **extra)


class BaseAgent:
    """Base class for all agents in the SmolAgents framework.

    Provides automatic execution logging to independent JSON files for debugging
    and analysis. Each agent run is saved with complete execution history.
    """

    def __init__(
        self,
        config: Config = None,
        tools: list = None,
        max_steps: int = 10,
        is_code: bool = False,
        save_runs: bool = True,
        runs_dir: Optional[str] = None,
        **kwargs,
    ):
        """Initialize the base agent.

        Args:
            config: Configuration object (uses default if None)
            tools: List of tools available to the agent
            max_steps: Maximum steps the agent can take
            is_code: Whether to use CodeAgent (True) or ToolCallingAgent (False)
            save_runs: Whether to save agent runs to files (default: True)
            runs_dir: Directory for saving runs (default: logs/agent_runs)
            **kwargs: Additional arguments passed to the underlying agent
        """
        self.config = config or get_config()
        self.save_runs = save_runs
        self.runs_dir = Path(runs_dir) if runs_dir else Path("logs/agent_runs")
        self._last_usage: Optional[UsageMetrics] = None

        self.llm_model = create_llm_model(self.config)

        # Create appropriate agent type
        agent_class = CodeAgent if is_code else ToolCallingAgent
        agent_kwargs = {
            "model": self.llm_model,
            "tools": tools or [],
            "max_steps": max_steps,
            "stream_outputs": False,  # Disabled: streaming causes code block termination loops (smolagents #1872)
            **kwargs,
        }

        # Ensure agent has a name (use class name if not provided)
        if "name" not in agent_kwargs or not agent_kwargs["name"]:
            agent_kwargs["name"] = self.__class__.__name__

        # Add code-specific parameters
        if is_code:
            agent_kwargs["additional_authorized_imports"] = ["json", "datetime", "typing"]
            if _uses_structured_outputs(self.llm_model.model_id):
                agent_kwargs["use_structured_outputs_internally"] = True

        self.agent = agent_class(**agent_kwargs)

        # Create runs directory if saving is enabled
        if self.save_runs:
            self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prompt: str, run_id: Optional[str] = None) -> str:
        """Run the agent with the given prompt.

        Agent execution is automatically saved to an independent JSON file
        containing the complete execution history if save_runs is enabled.

        Args:
            prompt: The prompt to run the agent with
            run_id: Optional identifier for this run (e.g., question_id).
                   Used in the filename for easy correlation.

        Returns:
            Agent response string
        """
        response = self.agent.run(prompt)

        # Extract and store usage metrics
        self._last_usage = extract_usage_from_agent(
            self.agent, model_name=self.config.llm.model
        )

        # Save execution to independent file
        if self.save_runs:
            self._save_agent_run(prompt, response, run_id)

        return response

    def get_last_usage(self) -> Optional[UsageMetrics]:
        """Get usage metrics from the last agent run.

        Returns:
            UsageMetrics from the last run, or None if no run has occurred
        """
        return self._last_usage

    def _save_agent_run(
        self, prompt: str, response: str, run_id: Optional[str] = None
    ) -> None:
        """Save agent execution to an independent JSON file.

        Args:
            prompt: The prompt that was given to the agent
            response: The agent's final response
            run_id: Optional identifier for this run
        """
        try:
            filepath = self._get_run_filepath(run_id)
            run_data = self._build_run_data(prompt, response, run_id)

            self._write_run_file(filepath, run_data)
            logger.info(f"[{run_data['agent_name']}] Agent run saved to: {filepath}")

        except Exception as e:
            logger.warning(f"Failed to save agent run to file: {e}")

    def _get_run_filepath(self, run_id: Optional[str] = None) -> Path:
        """Generate filepath for agent run file.

        Args:
            run_id: Optional identifier for this run

        Returns:
            Path object for the run file
        """
        agent_name = self.agent.name or "agent"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if run_id:
            filename = f"{agent_name}_{run_id}_{timestamp}.json"
        else:
            filename = f"{agent_name}_{timestamp}.json"

        return self.runs_dir / filename

    def _build_run_data(
        self, prompt: str, response: str, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build the complete run data dictionary.

        Args:
            prompt: The prompt given to the agent
            response: The agent's response
            run_id: Optional run identifier

        Returns:
            Dictionary containing all run data
        """
        run_data = {
            "agent_name": self.agent.name or "agent",
            "run_id": run_id,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "prompt": prompt,
            "response": response,
            "model": self.config.llm.model,
            "max_steps": self.agent.max_steps,
        }

        # Add execution steps from memory
        self._add_memory_data(run_data)

        # Add managed agents info
        self._add_managed_agents(run_data)

        # Add usage metrics
        self._add_usage_metrics(run_data)

        return run_data

    def _add_memory_data(self, run_data: Dict[str, Any]) -> None:
        """Add execution memory data to run data.

        Args:
            run_data: Dictionary to add memory data to (modified in place)
        """
        if not self.agent.memory.steps:
            run_data["steps"] = []
            return

        # Add system prompt if available
        if self.agent.memory.system_prompt:
            run_data["system_prompt"] = self.agent.memory.system_prompt.system_prompt

        # Extract execution steps
        run_data["steps"] = [
            self._extract_step_data(i, step)
            for i, step in enumerate(self.agent.memory.steps, 1)
        ]

    def _extract_step_data(self, step_num: int, step: Any) -> Dict[str, Any]:
        """Extract data from a single execution step.

        Args:
            step_num: Step number
            step: Step object from agent memory

        Returns:
            Dictionary containing step data
        """
        step_data = {"step_number": step_num, "type": type(step).__name__}

        if isinstance(step, TaskStep):
            step_data["task"] = step.task
            if step.task_images:
                step_data["has_images"] = True

        elif isinstance(step, ActionStep):
            if step.tool_calls:
                step_data["tool_calls"] = self._serialize_tool_calls(step.tool_calls)

            if step.observations:
                step_data["observations"] = str(step.observations)

            if step.error:
                step_data["error"] = str(step.error)

            step_data["step_number"] = step.step_number

        return step_data

    def _add_managed_agents(self, run_data: Dict[str, Any]) -> None:
        """Add managed agents information to run data.

        Args:
            run_data: Dictionary to add managed agents to (modified in place)
        """
        managed_agents = getattr(self.agent, "managed_agents", None)
        if not managed_agents:
            return

        managed_names = []
        for agent in managed_agents:
            if isinstance(agent, str):
                managed_names.append(agent)
            else:
                managed_names.append(agent.name or type(agent).__name__)

        run_data["managed_agents"] = managed_names

    def _add_usage_metrics(self, run_data: Dict[str, Any]) -> None:
        """Add usage metrics to run data.

        Args:
            run_data: Dictionary to add usage metrics to (modified in place)
        """
        if not self._last_usage:
            return

        run_data["usage"] = {
            "total_tokens": self._last_usage.total_tokens,
            "prompt_tokens": self._last_usage.prompt_tokens,
            "completion_tokens": self._last_usage.completion_tokens,
            "estimated_cost_usd": self._last_usage.estimated_cost_usd,
        }

    def _serialize_tool_calls(self, tool_calls: Any) -> List[Dict[str, Any]]:
        """Serialize tool calls to JSON-compatible format.

        Args:
            tool_calls: Tool calls from agent step (may be ToolCall objects or dicts)

        Returns:
            List of dictionaries representing tool calls
        """
        if not tool_calls:
            return []

        serialized = []
        for call in tool_calls:
            if isinstance(call, dict):
                serialized.append(call)
            else:
                # Extract attributes from ToolCall object
                call_dict = {
                    "name": getattr(call, "name", None),
                    "arguments": getattr(call, "arguments", None),
                }
                if call_id := getattr(call, "id", None):
                    call_dict["id"] = call_id
                if call_type := getattr(call, "type", None):
                    call_dict["type"] = call_type
                serialized.append(call_dict)

        return serialized

    def _write_run_file(self, filepath: Path, run_data: Dict[str, Any]) -> None:
        """Write run data to JSON file.

        Args:
            filepath: Path to write the file to
            run_data: Data to write
        """
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(run_data, f, indent=2, ensure_ascii=False)
