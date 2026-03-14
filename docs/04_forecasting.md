# Section 4: Forecasting

This section describes the forecasting architecture, the MCP server that provides temporally-filtered evidence to agents, and how the context window is managed to prevent information leakage.

---

## 4.1 Architecture Overview

The forecasting system is built around a strict separation between the **evidence access layer** (what the agent can see) and **evaluation** (what actually happened). This separation is enforced by the Temporal Gateway.

```
┌─────────────────────────────────────────────────────────┐
│                    Forecasting Agent                    │
│   (LLM with smolagents tool-calling framework)          │
└────────────────────┬────────────────────────────────────┘
                     │  MCP tool calls
                     ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Forecasting Server                     │
│         (Temporal Gateway — src/mcp_forecasting_server) │
│                                                         │
│  Intercepts every call → checks X-Simulated-Date        │
│  Filters SQL queries → no future data returned          │
│  Ground truth withheld at all times                     │
└────────────────────┬────────────────────────────────────┘
                     │  Filtered queries
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   SQLite Database                       │
│      Articles, Events, Questions (with ground truth)    │
└─────────────────────────────────────────────────────────┘
```

The agent operates as if it exists at `simulated_date` — it cannot retrieve any article or event published after that date, and it never sees the `ground_truth` field on the question.

---

## 4.2 MCP Forecasting Server

The MCP (Model Context Protocol) server is the core component that enables LLM agents to forecast by exploring a simulated past.

### Installation

```bash
uv sync  # Install all dependencies
```

### Configuration

Add to your `claude_desktop_config.json` to use with Claude Desktop:

```json
{
  "mcpServers": {
    "worldreasoner": {
      "command": "uv",
      "args": ["run", "worldreasoner-mcp-forecast"],
      "cwd": "/absolute/path/to/worldreasoner"
    }
  }
}
```

To start the server directly:
```bash
python src/mcp_forecasting_server.py
# Runs on port 8110 by default
```

### Available Tools

| Tool Name | Description | Key Inputs |
|-----------|-------------|------------|
| `get_question` | Retrieves the forecasting question without ground truth | None |
| `temporal_search_articles` | Semantic search for articles published *before* simulated date | `query`, `limit` |
| `fetch_article` | Gets full content of a specific article | `article_id` |
| `get_statistics` | Returns server stats (database size, uptime) | None |
| `submit_forecast` | Submits a final prediction | `prediction`, `confidence`, `reasoning` |

All tools require the `X-Simulated-Date` header, which is injected automatically by the agent's context (see Section 4.3).

### Resource URIs

The MCP server also exposes resource endpoints:

- `forecast://questions/{id}` — Get question details
- `forecast://articles/{id}` — Get article content

### How Temporal Filtering Works

The server acts as a **Temporal Gateway**:

1. Intercepts all tool calls from the agent.
2. Reads the `X-Simulated-Date` value from request context.
3. Rewrites SQL queries to add `WHERE published_date <= simulated_date` (or equivalent).
4. Returns only "historically accurate" data to the agent.
5. Never returns the `ground_truth` field regardless of the date.

This ensures the agent cannot observe any information that would not have been available at `simulated_date`, making the forecast genuinely predictive rather than retrospective.

---

## 4.3 Context Window Management

### The Problem

To produce a valid forecast, the agent needs:
1. **Enough context**: A sufficient number of articles and events must have already occurred.
2. **Valid window**: The simulated date must be strictly before the question's resolution date.

Setting the simulated date too early means the agent has no useful context. Setting it too late risks including post-resolution information. The `prepare_forecast()` method computes an optimal `simulated_date` automatically.

### Automatic Calculation with `prepare_forecast()`

```python
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase("worldreasoner.db")
question = db.get(Question, "q_tech_20251115_001")

# Automatically calculates the correct window based on available articles
setup = question.prepare_forecast(
    db=db,
    offset_days_before_resolution=7,  # Optional buffer before resolution date
    min_context_items=3               # Wait until at least 3 articles exist
)

print(f"Simulated Date: {setup['simulated_date']}")
# > Simulated Date: 2024-11-08 (The date when the 3rd article was published)
```

### Integration with MCP Headers

Pass the derived date to the MCP server via request headers:

```python
mcp_headers = {
    "X-Question-ID": question.id,
    "X-Simulated-Date": setup['simulated_date'].isoformat()
}
```

The MCP server reads `X-Simulated-Date` from these headers to enforce temporal filtering.

### How It Works (Algorithm)

1. Retrieve all events and articles related to the question from the database.
2. Sort them chronologically by publication/creation date.
3. Set `window_start` to the date of the *N*th item, where *N* = `min_context_items`.
4. Set `window_end` to `resolution_date - 1 second`.
5. If `window_start > window_end`, the question is invalid (resolved before enough context existed) and is skipped.

The `offset_days_before_resolution` parameter adds a buffer: the window is further capped at `resolution_date - offset_days`.

---

## 4.4 Forecasting Agents

### Running Individual Forecasts

For development, debugging, or testing a single question before a full benchmark run:

```bash
# Single question forecast (interactive mode)
wr forecast run -q <question_id>
wr forecast run --interactive

# Specify model and mode
wr forecast run -q q_abc123 --model gemini-2.5-flash --mode knowledge_only

# Against experiment database
wr forecast run --db experiment.db -q <question_id>
```

### Batch Forecasting

```bash
# Forecast specific questions
wr forecast batch -q q_1 -q q_2 -q q_3

# Forecast from a source with filters
wr forecast batch --source polymarket --domain politics --limit 10
```

Forecasting modes:

| Mode | Description |
|------|-------------|
| `knowledge_only` | Agent uses only LLM training knowledge — no MCP tools, no external search |
| `container` | Agent has access to MCP server with temporally-filtered evidence |
| `real_time` | Agent uses live internet access; clock simulation overrides are ignored |

For the full set of experimental conditions that combine these modes, see [Section 5](05_evaluation.md).

---

*For evaluation of forecast results, see [Section 5](05_evaluation.md). For CLI reference, see [Appendix A](appendix/A_cli_reference.md).*
