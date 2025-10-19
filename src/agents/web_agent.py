from smolagents import WebSearchTool, VisitWebpageTool

from src.agents.base import BaseAgent
from src.utils.config import Config, load_config


class WebAgent(BaseAgent):
    """Agent specialized for web interactions."""
    def __init__(self, config: Config, tools: list = None, max_steps: int = 15):
        # Create a new list with web tools
        web_tools = [
            WebSearchTool(),
            VisitWebpageTool()
        ]
        # Add any additional custom tools
        if tools:
            web_tools.extend(tools)
        # WebAgent gets more steps since it needs to search + visit + collect
        super().__init__(config=config, tools=web_tools, max_steps=max_steps)