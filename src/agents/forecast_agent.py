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
                 db_path: str = None,
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
            db_path: Database path (enables per-request database switching)
            tools: Additional custom tools
            max_steps: Maximum agent steps
            knowledge_only: If True, only allow get_question and submit_forecast tools
                          (disable research tools to test inherent LLM knowledge)
        """

        # Create headers for MCP connection
        headers = {
            "X-Question-ID": question.id,
            "X-Knowledge-Cutoff": knowledge_cutoff,
            "X-Simulated-Date": simulated_date,
            "X-Model-Name": config.llm.model
        }

        # Add database path if provided (enables per-request DB switching)
        if db_path:
            headers["X-Database-Path"] = db_path

        # Create MCP server connection parameters
        # Note: For streamable-http transport, URL should point to the /mcp endpoint
        mcp_server_parameters = [
            {
                "url": f"http://{config.server.mcp_host}:{config.server.mcp_port}/mcp",
                "transport": "streamable-http",
                "headers": headers
            }
        ]

        # Debug: Log connection details
        from src.utils.logging import logger
        logger.info(f"ForecastAgent connecting to MCP server at http://{config.server.mcp_host}:{config.server.mcp_port}/mcp")
        logger.debug(f"Headers: question_id={question.id}, simulated_date={simulated_date}, db_path={db_path or 'default'}")

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