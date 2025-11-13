# WorldReasoner MCP Server

Complete documentation for the WorldReasoner MCP (Model Context Protocol) Forecasting Server.

## Overview

The MCP server provides temporal-aware tools for LLMs to make forecasts while respecting historical information boundaries. This enables rigorous testing of forecasting capabilities by simulating historical contexts.

**Key Features:**
- ✅ Temporal Gateway - Information filtered by cutoff dates
- ✅ Session Management - Track forecasting context
- ✅ Article Search - Find relevant historical information
- ✅ Full Article Access - Read complete content with validation
- ✅ Forecast Submission - Save predictions with reasoning
- ✅ Multiple Modes - stdio, HTTP, and streaming (SSE)

---

## Quick Start (5 Minutes)

### 1. Test the Server

```bash
# Quick smoke test (no data required)
python examples/test_mcp_server.py
```

### 2. Run Development Mode

```bash
# Interactive testing interface
uv run fastmcp dev src.mcp_forecasting_server
```

### 3. Connect to Claude Desktop

**Step 1**: Edit your Claude Desktop config file:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Step 2**: Add this configuration (update `cwd` to your path):

```json
{
  "mcpServers": {
    "worldreasoner-forecasting": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_forecasting_server"],
      "cwd": "D:/workspace/worldreasoner",
      "env": {
        "WORLDREASONER_DB": "worldreasoner.db"
      }
    }
  }
}
```

**Step 3**: Restart Claude Desktop and look for the 🔌 icon

### 4. Make Your First Forecast

Try in Claude Desktop:
```
Use list_questions to show me available forecast questions about politics.
```

Then:
```
Start a forecast session for [question_id] with October 1, 2024 as cutoff.
Search for relevant articles.
Make a forecast based on the information.
```

---

---

## Example Forecasting Session

Here's what a complete session looks like in Claude Desktop:

**You**: "List available forecast questions"

**Claude** uses `list_questions()`:
```
Found 44 questions:
- q_pol_2024_001: Will the Republican candidate win the 2024 US Presidential Election?
- q_tech_2024_005: Will Apple announce a new AI chip by Q4 2024?
```

**You**: "Start a forecast session for q_pol_2024_001 with simulated date October 1, 2024"

**Claude** uses `start_forecast_session()`:
```
Session started! Forecasting as of October 1, 2024.
Resolution date: November 6, 2024 (36 days away)
```

**You**: "Search for recent polling data"

**Claude** uses `temporal_search_articles()`:
```
Found 12 articles from before Oct 1, 2024:
1. "Swing State Polls Show Tight Race" (Sep 28, 2024)
2. "Pennsylvania Polling Averages" (Sep 25, 2024)
```

**You**: "Fetch article art_pol_20240928_001"

**Claude** uses `fetch_article()` and reads the full content.

**You**: "Make your forecast"

**Claude** uses `submit_forecast()`:
```
Forecast submitted!
Prediction: True (Republican wins)
Confidence: 65%
Reasoning: Based on polling averages in swing states...
```

---

## Installation

Already included in WorldReasoner. Ensure dependencies are installed:

```bash
uv sync
```

## Running the Server

The MCP server supports three modes: **stdio** (for MCP clients like Claude Desktop), **http** (REST API), and **stream** (Server-Sent Events).

### stdio Mode (Default - MCP Clients)

For integration with Claude Desktop and other MCP clients:

```bash
python -m src.mcp_forecasting_server

# Explicit stdio mode
python -m src.mcp_forecasting_server --mode stdio
```

### HTTP Mode

REST-style endpoints for direct HTTP access:

```bash
python -m src.mcp_forecasting_server --mode http --host 0.0.0.0 --port 8100

# Test with curl
curl http://localhost:8100/mcp/tools

# List tools
curl http://localhost:8100/mcp/tools

# Invoke a tool (example)
curl -X POST http://localhost:8100/mcp/tools/list_questions \
  -H "Content-Type: application/json" \
  -d '{"limit":5}'
```

**HTTP Endpoints:**
- `GET /mcp/tools` - List available tools
- `POST /mcp/tools/{tool_name}` - Invoke a specific tool
- `GET /mcp/prompts` - List prompts (currently unused)
- `GET /docs` - OpenAPI documentation

### Streaming Mode (SSE)

Server-Sent Events for incremental tool output. Ideal for progressive updates from long-running operations:

```bash
python -m src.mcp_forecasting_server --mode stream --host 0.0.0.0 --port 8110
```

**When to use streaming:**
- Long-running searches across many articles
- Multi-step forecast reasoning processes
- Real-time progress updates to clients

**Note:** Current tools return final JSON strings. To leverage streaming fully, refactor tools to yield partial results (e.g., `yield` article matches as found, rather than returning all at once).

### Development Mode

Interactive testing with auto-reload:

```bash
uv run fastmcp dev src.mcp_forecasting_server
```

This provides:
- Interactive prompt to test tools
- Auto-reload on code changes
- Debug logging
- Great for development and testing

---

## Available Tools

### 1. list_questions

List available forecast questions from the database.

**Parameters:**
```json
{
  "domain": "politics",      // optional: filter by domain
  "difficulty": 4,            // optional: 1-5 difficulty
  "limit": 10                 // optional: max results (default: 20)
}
```

**Returns:**
```json
{
  "count": 10,
  "questions": [
    {
      "id": "q_pol_2024_001",
      "question_text": "Will the Republican candidate win the 2024 US Presidential Election?",
      "question_type": "boolean",
      "domain": "politics",
      "difficulty": 4,
      "resolution_date": "2024-11-06T00:00:00Z",
      "is_resolved": false
    }
  ]
}
```

### 2. start_forecast_session

Initialize a forecasting session with temporal context.

**Parameters:**
```json
{
  "question_id": "q_pol_2024_001",
  "knowledge_cutoff_date": "2024-10-01T00:00:00Z"  // optional
}
```

**Returns:**
```json
{
  "session_id": "session_q_pol_2024_001_1699564800",
  "question": { /* question details */ },
  "temporal_context": {
    "knowledge_cutoff_date": "2024-10-01T00:00:00Z",
    "resolution_date": "2024-11-06T00:00:00Z",
    "days_to_forecast": 36
  }
}
```

### 3. temporal_search_articles

Search articles with temporal filtering (only pre-cutoff articles).

**Prerequisites:** Must call `start_forecast_session` first.

**Parameters:**
```json
{
  "query": "election polling swing states",
  "domain": "politics",      // optional
  "max_results": 10          // optional (default: 10)
}
```

**Returns:**
```json
{
  "query": "election polling swing states",
  "knowledge_cutoff_date": "2024-10-01T00:00:00Z",
  "count": 5,
  "articles": [
    {
      "id": "art_pol_20240928_001",
      "title": "Swing State Polls Show Tight Race",
      "published_date": "2024-09-28T12:00:00Z",
      "excerpt": "Recent polling in Pennsylvania..."
    }
  ]
}
```

### 4. fetch_article

Fetch full article content with temporal validation.

**Prerequisites:** Must call `start_forecast_session` first.

**Parameters:**
```json
{
  "article_id": "art_pol_20240928_001"
}
```

**Returns:**
```json
{
  "id": "art_pol_20240928_001",
  "title": "Swing State Polls Show Tight Race",
  "content": "Full article text...",
  "word_count": 1250,
  "published_date": "2024-09-28T12:00:00Z"
}
```

### 5. submit_forecast

Submit a forecast for the current question.

**Prerequisites:** Must call `start_forecast_session` first.

**Parameters:**
```json
{
  "prediction": "true",      // boolean: "true"/"false", MCQ: option text, quantity: number
  "confidence": 0.65,        // 0.0 to 1.0
  "reasoning": "Based on analysis of polling data...",  // min 50 chars
  "articles_accessed": ["art_pol_20240928_001"]       // optional
}
```

**Returns:**
```json
{
  "forecast_id": "fcst_q_pol_2024_001_1699564800",
  "question_id": "q_pol_2024_001",
  "prediction": true,
  "confidence": 0.65,
  "knowledge_cutoff_date": "2024-10-01T00:00:00Z",
  "status": "submitted"
}
```

### 6. get_session_info

Get current forecast session details.

**Returns:**
```json
{
  "active": true,
  "session_id": "session_q_pol_2024_001_1699564800",
  "question_id": "q_pol_2024_001",
  "knowledge_cutoff_date": "2024-10-01T00:00:00Z"
}
```

---

## Claude Desktop Integration

### Step 1: Locate Config File

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

### Step 2: Add Configuration

```json
{
  "mcpServers": {
    "worldreasoner-forecasting": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_forecasting_server"],
      "cwd": "D:/workspace/worldreasoner",
      "env": {
        "WORLDREASONER_DB": "worldreasoner.db"
      }
    }
  }
}
```

**Important:** Update `cwd` to your actual WorldReasoner directory.

### Step 3: Restart Claude Desktop

Look for the 🔌 icon - "worldreasoner-forecasting" should appear as connected.

---

## Temporal Constraints

### How It Works

The MCP server enforces strict temporal boundaries:

1. **Cutoff Date**: Set when starting a forecast session
2. **Article Filtering**: Only `published_date < cutoff_date` are accessible
3. **Event Filtering**: Only `occurred_date < cutoff_date` are accessible
4. **Validation**: All temporal checks use timezone-aware UTC datetimes

### Why It Matters

**Without temporal control ❌**: LLM could access articles published after making the "forecast"

**With temporal control ✅**: LLM only sees information truly available at the time

### Important Rules

- Cutoff dates are **exclusive**: Items exactly at cutoff are NOT accessible
- All dates must be timezone-aware (UTC)
- Articles without `published_date` are rejected
- Events without `occurred_date` are rejected

---

## Configuration

### Environment Variables

- `WORLDREASONER_DB`: Path to database file (default: `worldreasoner.db`)

### Database Tables

Required tables:
- `questions` - Forecast questions
- `articles` - News articles (with temporal filtering)
- `events` - Events with occurrence dates (optional)

**Important**: Articles must have timezone-aware `published_date` for filtering to work.

---

## Testing

### Run Test Suite

```bash
# Comprehensive test
uv run python examples/test_mcp_server.py

# Quick smoke test
uv run python examples/smoke_check_mcp_server.py
```

### Manual Interactive Testing

```bash
uv run fastmcp dev src.mcp_forecasting_server
```

---

## Troubleshooting

### No Articles Accessible

**Symptom**: `temporal_search_articles` returns 0 results

**Solutions**:
1. Ensure articles have timezone-aware `published_date` (UTC)
2. Adjust the `knowledge_cutoff_date` parameter
3. Try broader search queries

### "No Active Forecast Session" Error

**Cause**: Using temporal tools without calling `start_forecast_session`

**Solution**: Always call `start_forecast_session` before:
- `temporal_search_articles`
- `fetch_article`
- `submit_forecast`

### Invalid Prediction Format

**Solutions by question type**:
- **Boolean**: "true" or "false" (case insensitive)
- **MCQ**: Exact option text from question
- **Quantity**: Numeric value
- **Timeframe**: ISO date format

---

## Architecture

```
┌─────────────────────────────────┐
│   LLM Client (Claude Desktop)   │
└────────────┬────────────────────┘
             │ MCP Protocol
┌────────────┴────────────────────┐
│  MCP Forecasting Server         │
│  ┌───────────────────────────┐  │
│  │  Temporal Gateway         │  │
│  │  (cutoff enforcement)     │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │  6 Tools                  │  │
│  │  • list_questions         │  │
│  │  • start_forecast_session │  │
│  │  • temporal_search_*      │  │
│  │  • fetch_article          │  │
│  │  • submit_forecast        │  │
│  │  • get_session_info       │  │
│  └───────────────────────────┘  │
└────────────┬────────────────────┘
             │
┌────────────┴────────────────────┐
│  WorldReasoner Database         │
│  • Questions                    │
│  • Articles (temporal filter)   │
│  • Events                       │
│  • Forecasts                    │
└─────────────────────────────────┘
```

---

## Development

### Adding New Tools

1. Define tool with `@mcp.tool()` decorator
2. Add type hints for all parameters
3. Return JSON string with results
4. Implement error handling
5. Update documentation

### Example

```python
@mcp.tool()
def my_new_tool(param: str, optional_param: Optional[int] = None) -> str:
    """Tool description for LLM.
    
    Args:
        param: Required parameter description
        optional_param: Optional parameter description
        
    Returns:
        JSON string with results
    """
    try:
        # Implementation
        result = {"status": "success", "data": param}
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error in my_new_tool: {e}")
        return json.dumps({"error": str(e)})
```

---

## Resources

- **[MCP Specification](https://spec.modelcontextprotocol.io/)** - Official MCP protocol docs
- **[FastMCP Documentation](https://github.com/jlowin/fastmcp)** - FastMCP library
- **[WorldReasoner Architecture](../AGENTS.md)** - System design and patterns
- **[Temporal Gateway Source](../src/core/temporal_gateway.py)** - Implementation

---

## License

MIT License - See [LICENSE](../LICENSE) file for details.
