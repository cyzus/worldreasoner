from src.agents.base import BaseAgent
from src.config import Config
from smolagents import MCPClient
import uuid
from datetime import datetime, timezone

from src.domain.models.question import Question


class ForecastAgent(BaseAgent):
    def __init__(self,
                 question: Question,
                 simulated_date: str,
                 knowledge_cutoff: str,
                 config: Config,
                 db_path: str = None,
                 mode: str = "container",
                 enable_causal_tools: bool = False,
                 tools: list = None,
                 max_steps: int = 15,
                 is_code: bool = False):
        """Initialize ForecastAgent.

        Args:
            question: Question to forecast
            simulated_date: Simulated "today" date (ISO format)
            knowledge_cutoff: LLM training cutoff date (ISO format)
            config: Configuration object
            db_path: Path to test/forecast database (optional)
            mode: Forecasting mode ('knowledge_only', 'container', 'real_time')
            enable_causal_tools: Whether to include causal reasoning tools (identify_forecast_event, create_forecast_causal_link, inspect_forecast_graph)
            tools: Additional custom tools
            max_steps: Maximum agent steps
            is_code: Whether this is a code execution agent
        """

        # Auto-configure for real-time mode
        if mode == "real_time":
            simulated_date = datetime.now(timezone.utc).isoformat()
            db_path = None  # Use main database for real-time forecasts

        # Generate session ID for tracking causal reasoning across requests
        session_id = f"sess_{question.id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"

        # Create headers for MCP connection
        headers = {
            "X-Question-ID": question.id,
            "X-Knowledge-Cutoff": knowledge_cutoff,
            "X-Simulated-Date": simulated_date,
            "X-Model-Name": config.llm.model,
            "X-Forecast-Mode": mode,
            "X-Session-ID": session_id,
        }

        if db_path:
            headers["X-Database-Path"] = db_path

        # Create MCP server parameters
        mcp_server_parameters = [
            {
                "url": f"http://{config.server.mcp_host}:{config.server.mcp_port}/mcp",
                "transport": "streamable-http",
                "headers": headers
            }
        ]

        # Get MCP tools
        mcp_client = MCPClient(server_parameters=mcp_server_parameters)
        forecast_tools = mcp_client.get_tools()

        # Filter/add tools based on mode
        if mode == "knowledge_only":
            # Only allow get_question and submit_forecast
            allowed_tool_names = {'get_question', 'submit_forecast'}
            forecast_tools = [
                tool for tool in forecast_tools
                if tool.name in allowed_tool_names
            ]
        elif mode == "real_time":
            # Add web tools for real-time mode
            from src.tools.web_search import WebSearchTool
            from src.tools.web_fetch import WebFetchTool
            allowed_tool_names = {'get_question', 'submit_forecast'}
            forecast_tools = [
                tool for tool in forecast_tools
                if tool.name in allowed_tool_names
            ]
            forecast_tools.extend([
                WebSearchTool(),
                WebFetchTool()
            ])

        # Filter out causal reasoning tools if not enabled
        if not enable_causal_tools:
            causal_tool_names = {
                'identify_forecast_event',
                'create_forecast_causal_link',
                'inspect_forecast_graph'
            }
            forecast_tools = [
                tool for tool in forecast_tools
                if tool.name not in causal_tool_names
            ]

        # Add any additional custom tools
        if tools:
            forecast_tools.extend(tools)

        # Initialize parent agent
        super().__init__(config=config, tools=forecast_tools, max_steps=max_steps, is_code=is_code)