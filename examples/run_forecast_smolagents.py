from smolagents import ToolCallingAgent, MCPClient, LiteLLMModel
from src.core.database import GenericDatabase
from src.domain.models import Question

# ============================================================================
# CONFIGURATION
# ============================================================================
QUESTION_ID = "q_tech_20251117_003_5c55a8f1"  # Change this to your question
MODEL_ID = "litellm_proxy/claude-sonnet-4-5"
MCP_SERVER_URL = "http://127.0.0.1:8110/mcp"
KNOWLEDGE_CUTOFF = "2024-05-01"  # LLM training cutoff

# Threshold configuration
MIN_CONTEXT_ITEMS = 3  # Default: Need 3 context items before forecasting
OFFSET_DAYS_BEFORE_RESOLUTION = 0  # Forecast 0 days before resolution
    
# ============================================================================
# AUTOMATIC CONTEXT WINDOW CALCULATION
# ============================================================================
print("="*80)
print("FORECAST SETUP - AUTOMATIC CONTEXT WINDOW CALCULATION")
print("="*80)

# Load question from database
db = GenericDatabase("worldreasoner.db")
question = db.get(Question, QUESTION_ID)

if not question:
    raise ValueError(f"Question {QUESTION_ID} not found in database")

print(f"\nQuestion: {question.question_text}")
print(f"Resolution date: {question.resolution_date.date()}")

# Calculate valid forecast window
try:
    window_start, window_end = question.get_forecast_context_window(
        db=db,
        min_context_items=MIN_CONTEXT_ITEMS
    )

    days_available = (window_end - window_start).days

    print(f"\nValid Forecast Window:")
    print(f"  Opens:      {window_start.date()} (after {MIN_CONTEXT_ITEMS} context items)")
    print(f"  Closes:     {window_end.date()} (before resolution)")
    print(f"  Duration:   {days_available} days")

    # Get suggested simulated date
    simulated_date = question.suggest_simulated_date(
        db=db,
        offset_days_before_resolution=OFFSET_DAYS_BEFORE_RESOLUTION,
        min_context_items=MIN_CONTEXT_ITEMS
    )

    print(f"\nSimulated Date (auto-calculated):")
    print(f"  Using:      {simulated_date.date()}")
    print(f"  Strategy:   {OFFSET_DAYS_BEFORE_RESOLUTION} days before resolution")

    # Validate the date
    valid, error = question.validate_simulated_date(simulated_date, db=db)
    if not valid:
        raise ValueError(f"Invalid simulated date: {error}")

    print(f"  Status:     VALID ✓")

except ValueError as e:
    print(f"\n❌ Error: {e}")
    print("\nThis may indicate:")
    print("  - Not enough context items in database")
    print("  - Evidence collected after resolution (data quality issue)")
    print("  - Question has no related events/articles")
    raise

print(f"\n{'='*80}")
print("STARTING FORECAST AGENT")
print(f"{'='*80}\n")

# MCP server connection with automatically derived temporal context
mcp_server_parameters = [
    {
        "url": MCP_SERVER_URL,
        "transport": "streamable-http",
        "headers": {
            "X-Question-ID": question.id,
            "X-Knowledge-Cutoff": KNOWLEDGE_CUTOFF,
            "X-Simulated-Date": simulated_date.isoformat()  # ✨ Auto-calculated!
        }
    }
]

mcp_client = MCPClient(server_parameters=mcp_server_parameters)
tools = mcp_client.get_tools()
model = LiteLLMModel(model_id=MODEL_ID)
agent = ToolCallingAgent(tools=tools, model=model, stream_outputs=True)

# The agent now works in a temporally-constrained environment
# - Knowledge cutoff: No info after LLM training date
# - Simulated date: "Current time" for the forecast (auto-calculated)
# - All tools automatically respect these temporal constraints
agent.run("Use the get_question tool to see what you need to forecast, then try to answer it.")