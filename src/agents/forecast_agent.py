from src.agents.base import BaseAgent
from src.config import Config
from smolagents import MCPClient
import uuid
from datetime import datetime, timezone

from src.domain.models.question import Question


class ForecastAgent(BaseAgent):
    def __init__(
        self,
        question: Question,
        simulated_date: str,
        knowledge_cutoff: str,
        config: Config,
        db_path: str = None,
        mode: str = "container",
        enable_causal_tools: bool = False,
        tools: list = None,
        max_steps: int = 15,
        is_code: bool = True,
    ):
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
                "headers": headers,
            }
        ]

        # Get MCP tools
        mcp_client = MCPClient(server_parameters=mcp_server_parameters)
        forecast_tools = mcp_client.get_tools()

        # Causal tool names (these create new events, valid for any mode)
        causal_tool_names = {
            "identify_forecast_event",
            "create_forecast_causal_link",
            "inspect_forecast_graph",
        }

        # Base tools always available
        base_tool_names = {"get_question", "submit_forecast"}

        # Filter/add tools based on mode
        if mode == "knowledge_only":
            # Knowledge-only: base tools + optionally causal tools
            allowed = base_tool_names.copy()
            if enable_causal_tools:
                allowed.update(causal_tool_names)
            forecast_tools = [t for t in forecast_tools if t.name in allowed]
        elif mode == "real_time":
            # Real-time: base tools + optionally causal tools + web tools
            from src.tools.web_search import WebSearchTool
            from src.tools.web_fetch import WebFetchTool

            allowed = base_tool_names.copy()
            if enable_causal_tools:
                allowed.update(causal_tool_names)
            forecast_tools = [t for t in forecast_tools if t.name in allowed]
            forecast_tools.extend([WebSearchTool(), WebFetchTool()])
        else:
            # Container mode: all MCP tools, filter causal if not enabled
            if not enable_causal_tools:
                forecast_tools = [
                    t for t in forecast_tools if t.name not in causal_tool_names
                ]

        # Increase max steps if causal tools enabled (they need more reasoning)
        if enable_causal_tools:
            max_steps = max(max_steps, 25)

        # Add any additional custom tools
        if tools:
            forecast_tools.extend(tools)

        # Initialize parent agent
        super().__init__(
            config=config, tools=forecast_tools, max_steps=max_steps, is_code=is_code
        )
