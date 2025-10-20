from smolagents import WebSearchTool, VisitWebpageTool

from src.agents.base import BaseAgent
from src.config import Config, load_config


class WebAgent(BaseAgent):
    """Agent specialized for web interactions."""
    def __init__(self, config: Config, tools: list = None, max_steps: int = 15):
        # Lazy import to avoid circular dependency
        from src.pipelines.stages.tools.web_fetch import WebFetchTool
        
        # Create a new list with web tools
        web_tools = [
            WebSearchTool(),
            WebFetchTool()
        ]
        # Add any additional custom tools
        if tools:
            web_tools.extend(tools)
        # WebAgent gets more steps since it needs to search + visit + collect
        super().__init__(config=config, tools=web_tools, max_steps=max_steps)