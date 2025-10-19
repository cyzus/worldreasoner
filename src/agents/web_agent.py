from smolagents import WebSearchTool, VisitWebpageTool

from src.agents.base import BaseAgent
from src.utils.config import Config, load_config


class WebAgent(BaseAgent):
    """Agent specialized for web interactions."""
    def __init__(self, config: Config, tools: list = None):
        # Create a new list with web tools
        web_tools = [
            WebSearchTool(),
            VisitWebpageTool()
        ]
        # Add any additional custom tools
        if tools:
            web_tools.extend(tools)
        super().__init__(config=config, tools=web_tools)