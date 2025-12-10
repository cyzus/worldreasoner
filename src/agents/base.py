from typing import Optional
from smolagents import CodeAgent, ToolCallingAgent, LiteLLMModel
from src.config import Config, get_config
from src.utils.usage_tracking import UsageMetrics, extract_usage_from_agent

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

    def run(self, prompt: str) -> str:
        """Run the agent with the given prompt.

        After execution, usage metrics are available via get_last_usage().

        Args:
            prompt: The prompt to run the agent with

        Returns:
            Agent response string
        """
        response = self.agent.run(prompt)

        # Extract and store usage metrics
        self._last_usage = extract_usage_from_agent(
            self.agent,
            model_name=self.config.llm.model
        )

        return response

    def get_last_usage(self) -> Optional[UsageMetrics]:
        """Get usage metrics from the last agent run.

        Returns:
            UsageMetrics from the last run, or None if no run has occurred
        """
        return self._last_usage