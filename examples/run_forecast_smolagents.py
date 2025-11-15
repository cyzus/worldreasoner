from smolagents import ToolCallingAgent, MCPClient, LiteLLMModel


# MCP server connection with forecasting context in headers
# These headers establish the temporal context for the entire session
mcp_server_parameters = [
    {
        "url": "http://127.0.0.1:8110/mcp",
        "transport": "streamable-http",
        "headers": {
            "X-Question-ID": "q_tech_20251103_002_75688b26",
            "X-Knowledge-Cutoff": "2023-11-03",
            "X-Simulated-Date": "2025-09-01"
        }
    }
]
model_id = "litellm_proxy/claude-sonnet-4-5"

mcp_client = MCPClient(server_parameters=mcp_server_parameters)
tools = mcp_client.get_tools()
model = LiteLLMModel(model_id=model_id)
agent = ToolCallingAgent(tools=tools, model=model, stream_outputs=True)

# The agent now works in a temporally-constrained environment
# All tools automatically respect the knowledge cutoff
agent.run("Use the get_question tool to see what you need to forecast, then try to answer it.")