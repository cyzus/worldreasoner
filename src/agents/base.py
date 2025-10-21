from smolagents import ToolCallingAgent, LiteLLMModel
from src.config import Config, get_config

class BaseAgent():
    """Base class for all agents in the SmolAgents framework."""
    def __init__(self, config: Config = None, tools: list = None, max_steps: int = 10):
        self.config = config or get_config()
        self.llm_model = LiteLLMModel(
            model_id=self.config.llm.model,
            **self.config.llm.model_dump(exclude={"model"})
        )
        self.agent = ToolCallingAgent(
            model=self.llm_model,
            tools=tools or [],
            max_steps=max_steps,  # Configurable max steps
            stream_outputs=True
        )
    
    def run(self, prompt: str) -> str:
        """Run the agent with the given prompt."""
        response = self.agent.run(prompt)
        return response