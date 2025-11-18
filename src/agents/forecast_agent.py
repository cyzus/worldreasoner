from src.agents.base import BaseAgent
from src.config import Config
from smolagents import MCPClient

from src.domain.models.question import Question


class ForecastAgent(BaseAgent):
    def __init__(self, 
                 question: Question,
                 simulated_date: str,
                 knowledge_cutoff: str,
                 config: Config, 
                 tools: list = None, 
                 max_steps: int = 15):
        
        
        # Create a new list with web tools
        mcp_server_parameters = [
            {
                "url": f"http://{config.server.host}:{config.server.port}/mcp",
                "transport": "streamable-http",
                "headers": {
                    "X-Question-ID": question.id,
                    "X-Knowledge-Cutoff": knowledge_cutoff,
                    "X-Simulated-Date": simulated_date 
                }
            }
        ]

        mcp_client = MCPClient(server_parameters=mcp_server_parameters)
        forecast_tools = mcp_client.get_tools()
        # Add any additional custom tools
        if tools:
            forecast_tools.extend(tools)
        # WebAgent gets more steps since it needs to search + visit + collect
        super().__init__(config=config, tools=forecast_tools, max_steps=max_steps)