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
                 max_steps: int = 15,
                 is_code: bool = False,
                 knowledge_only: bool = False):
        """Initialize ForecastAgent.

        Args:
            question: Question to forecast
            simulated_date: Simulated "today" date (ISO format)
            knowledge_cutoff: LLM training cutoff date (ISO format)
            config: Configuration object
            tools: Additional custom tools
            max_steps: Maximum agent steps
            knowledge_only: If True, only allow get_question and submit_forecast tools
                          (disable research tools to test inherent LLM knowledge)
        """

        # Create a new list with web tools
        mcp_server_parameters = [
            {
                "url": f"http://{config.server.host}:{config.server.port}/mcp",
                "transport": "streamable-http",
                "headers": {
                    "X-Question-ID": question.id,
                    "X-Knowledge-Cutoff": knowledge_cutoff,
                    "X-Simulated-Date": simulated_date,
                    "X-Model-Name": config.llm.model  # Include model name for tracking
                }
            }
        ]

        mcp_client = MCPClient(server_parameters=mcp_server_parameters)
        forecast_tools = mcp_client.get_tools()

        # If knowledge_only mode, filter to only essential tools
        if knowledge_only:
            # Only allow get_question and submit_forecast
            allowed_tool_names = {'get_question', 'submit_forecast'}
            forecast_tools = [
                tool for tool in forecast_tools
                if tool.name in allowed_tool_names
            ]

        # Add any additional custom tools
        if tools:
            forecast_tools.extend(tools)

        # WebAgent gets more steps since it needs to search + visit + collect
        super().__init__(config=config, tools=forecast_tools, max_steps=max_steps, is_code=is_code)