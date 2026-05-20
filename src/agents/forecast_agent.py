from src.agents.base import BaseAgent
from src.config import Config
from smolagents import MCPClient
from mcp import StdioServerParameters
import uuid
import sys
import os
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
        benchmark_condition: str = None,
    ):
        """Initialize ForecastAgent.

        Args:
            question: Question to forecast
            simulated_date: Simulated "today" date (ISO format)
            knowledge_cutoff: LLM training cutoff date (ISO format)
            config: Configuration object
            db_path: Path to test/forecast database (optional)
            mode: Forecasting mode ('knowledge_only', 'container', 'real_time')
            enable_causal_tools: Whether to include causal reasoning tools
            tools: Additional custom tools
            max_steps: Maximum agent steps
            is_code: Whether this is a code execution agent
        """

        # Auto-configure for real-time mode
        if mode == "real_time":
            simulated_date = datetime.now(timezone.utc).isoformat()

        # Generate session ID for tracking causal reasoning across requests
        session_id = f"sess_{question.id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"
        self.session_id = session_id

        # Build context — same values regardless of transport
        context_env = {
            "WR_QUESTION_ID": question.id,
            "WR_KNOWLEDGE_CUTOFF": knowledge_cutoff,
            "WR_SIMULATED_DATE": simulated_date,
            "WR_MODEL_NAME": config.llm.model,
            "WR_FORECAST_MODE": mode,
            "WR_SESSION_ID": session_id,
        }
        if benchmark_condition:
            context_env["WR_BENCHMARK_CONDITION"] = benchmark_condition
        if db_path:
            context_env["WR_DATABASE_PATH"] = db_path

        # stdio transport: spawn server as subprocess, pass context via env vars.
        # Must use StdioServerParameters (not a dict) so mcpadapt routes to stdio_client.
        subprocess_env = {**os.environ, **context_env}
        mcp_server_parameters = [
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "src.api.mcp_forecasting_server", "--transport", "stdio",
                      "--db", db_path or config.database.db_path],
                env=subprocess_env,
            )
        ]

        self.mcp_client = MCPClient(
            server_parameters=mcp_server_parameters,
            structured_output=False,
            adapter_kwargs={"connect_timeout": 120},
        )
        forecast_tools = self.mcp_client.get_tools()

        # Causal tool names (these create new events, valid for any mode)
        causal_tool_names = {
            "identify_forecast_event",
            "create_forecast_causal_link",
            "propose_forecast_subgraph",
            "inspect_forecast_graph",
            "delete_forecast_event",
            "delete_forecast_hypothesis",
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
            from src.tools.collectors.web_search import WebSearchTool
            from src.tools.collectors.web_fetch import WebFetchTool

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
        # Increase max steps if conditions satisfied (they require more reasoning and iterative calls)
        if mode == "container" or mode == "real_time" or enable_causal_tools:
            max_steps = max(max_steps, 50)

        # Add any additional custom tools
        if tools:
            forecast_tools.extend(tools)

        # Initialize parent agent
        super().__init__(
            config=config, tools=forecast_tools, max_steps=max_steps, is_code=is_code
        )
