from typing import Optional
from smolagents import CodeAgent, ToolCallingAgent, LiteLLMModel
from src.config import Config, get_config
from src.utils.usage_tracking import UsageMetrics, extract_usage_from_agent
from src.utils.logging import logger

class BaseAgent():
    """Base class for all agents in the SmolAgents framework."""
    def __init__(self, config: Config = None, tools: list = None, max_steps: int = 10, is_code: bool = False,
                 **kwargs):
        self.config = config or get_config()
        self.llm_model = LiteLLMModel(
            model_id=self.config.llm.model,
            **self.config.llm.model_dump(exclude={"model", "embedding_model"})
        )
        if not is_code:
            self.agent = ToolCallingAgent(
                model=self.llm_model,
                tools=tools or [],
                max_steps=max_steps,  # Configurable max steps
                stream_outputs=True,
                **kwargs
            )
        else:
            self.agent = CodeAgent(
                model=self.llm_model,
                tools=tools or [],
                max_steps=max_steps,  
                stream_outputs=True,
                additional_authorized_imports=["json"], # Allow json imports in code agent
                **kwargs
            )
        self._last_usage: Optional[UsageMetrics] = None

    def run(self, prompt: str, log_execution: bool = True) -> str:
        """Run the agent with the given prompt.

        After execution, usage metrics are available via get_last_usage().

        Args:
            prompt: The prompt to run the agent with
            log_execution: Whether to log detailed execution steps (default: True)

        Returns:
            Agent response string
        """
        response = self.agent.run(prompt)

        # Extract and store usage metrics
        self._last_usage = extract_usage_from_agent(
            self.agent,
            model_name=self.config.llm.model
        )

        # Log execution details if requested
        if log_execution:
            self._log_execution()

        return response

    def get_last_usage(self) -> Optional[UsageMetrics]:
        """Get usage metrics from the last agent run.

        Returns:
            UsageMetrics from the last run, or None if no run has occurred
        """
        return self._last_usage

    def _log_execution(self) -> None:
        """Log detailed agent execution history from memory.

        Logs the agent's execution steps, tool calls, observations, and errors
        to help with debugging and understanding agent behavior.
        """
        try:
            # Get agent name if available
            agent_name = getattr(self.agent, 'name', 'Agent')

            # Log system prompt
            if hasattr(self.agent.memory, 'system_prompt'):
                prompt_preview = self.agent.memory.system_prompt.system_prompt[:200]
                logger.debug(f"[{agent_name}] System prompt: {prompt_preview}...")

            # Log execution steps
            step_count = len(self.agent.memory.steps)
            logger.info(f"[{agent_name}] Execution steps: {step_count}")

            from smolagents import ActionStep, TaskStep

            for i, step in enumerate(self.agent.memory.steps, 1):
                if isinstance(step, TaskStep):
                    task_preview = step.task[:200] if len(step.task) > 200 else step.task
                    logger.debug(f"[{agent_name}] Step {i} (Task): {task_preview}...")

                elif isinstance(step, ActionStep):
                    logger.debug(f"[{agent_name}] Step {i} (Action):")

                    # Log tool calls/code executed
                    if hasattr(step, 'tool_calls') and step.tool_calls:
                        logger.debug(f"[{agent_name}]   Tool calls: {step.tool_calls}")

                    # Log observations (results)
                    if hasattr(step, 'observations') and step.observations:
                        obs_str = str(step.observations)
                        obs_preview = obs_str[:300] if len(obs_str) > 300 else obs_str
                        logger.debug(f"[{agent_name}]   Observations: {obs_preview}...")

                    # Log errors if any
                    if hasattr(step, 'error') and step.error:
                        logger.warning(f"[{agent_name}]   Error in step {i}: {step.error}")

            # Log managed agents if available
            if hasattr(self.agent, 'managed_agents') and self.agent.managed_agents:
                managed_names = [a.name for a in self.agent.managed_agents]
                logger.info(f"[{agent_name}] Managed agents used: {managed_names}")

        except Exception as e:
            logger.warning(f"Failed to log agent execution details: {e}")