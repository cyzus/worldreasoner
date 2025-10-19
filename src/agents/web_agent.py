from smolagents import WebSearchTool, VisitWebpageTool

from src.agents.base import BaseAgent
from src.utils.config import Config, load_config


class WebAgent(BaseAgent):
    """Agent specialized for web interactions."""
    def __init__(self, config: Config, tools: list = []):
        tools.extend([
            WebSearchTool(),
            VisitWebpageTool()
        ])
        super().__init__(config=config, tools=tools)
    
if __name__ == "__main__":
    config = load_config()
    agent = WebAgent(config=config)
    response = agent.run("Find the latest news on climate change and summarize it.")
    print(response)