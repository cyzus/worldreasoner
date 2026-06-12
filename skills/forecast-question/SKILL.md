---
name: forecast-question
description: Add a custom forecast question to WorldReasoner, collect evidence (articles + causal graph), run a forecast with an LLM agent, and evaluate the result. Use when asked to forecast a specific question, add a new question to the database, test the evidence pipeline on a question, or run an end-to-end forecasting workflow.
license: MIT
compatibility: Requires Python 3.13+, uv, combined.db or worldreasoner.db, and LLM API keys in config/config.yaml.
metadata:
  author: worldreasoner
  version: "1.0"
---

# Forecast a Custom Question

End-to-end workflow: add a question → collect evidence → build causal graph → run forecast → evaluate.

## Step 1: Add the question

```bash
uv run wr question add \
  --text "Will X happen by Y date?" \
  --resolution-date 2025-12-31 \
  --source manual \
  --domain politics
```

Note the question ID printed after creation (e.g. `manual_abc123`).

Alternatively, to forecast an existing **Polymarket** market instead of a manual question, add it by slug, URL, or numeric id (the rest of the workflow is identical):

```bash
uv run wr question add-polymarket <event-slug-or-url> --db combined.db
```

This prints the resolved question ID (e.g. `polymarket_event_30829`); use that as `<question_id>` below.

## Step 2: Collect evidence

```bash
# Run evidence pipeline (scrapes articles, builds NL explanation)
uv run wr evidence run -q <question_id>

# Check evidence was collected
uv run wr question show -q <question_id>
```

## Step 3: Build causal graph

```bash
uv run wr graph build -q <question_id>

# Verify graph quality
uv run wr graph audit -q <question_id>
```

## Step 4: Run forecast

```bash
# With search + causal tools (recommended)
uv run wr forecast run \
  -q <question_id> \
  --mode container \
  --enable-causal-tools \
  --slot mid

# Knowledge-only baseline
uv run wr forecast run \
  -q <question_id> \
  --mode knowledge_only \
  --slot mid

# Machine-readable output
uv run wr forecast run \
  -q <question_id> \
  --mode container \
  --enable-causal-tools \
  --json
```

## Step 5: Evaluate (if ground truth is known)

```bash
# Once the question has resolved, set ground truth
uv run wr db update question <question_id> ground_truth true

# Score the forecast
uv run wr benchmark evaluate \
  --db combined.db \
  --condition worldreasoner
```

## Using an external agent via MCP

The MCP server exposes all forecasting tools for external agents:

```bash
# Start MCP server
uv run worldreasoner-mcp-forecast --port 8110

# Connect your agent with these HTTP headers on each request:
#   X-Question-ID: <question_id>
#   X-Simulated-Date: 2025-06-01T00:00:00Z   # "today" for the forecast
#   X-Knowledge-Cutoff: 2024-10-01T00:00:00Z  # agent's training cutoff (optional)
```

Available MCP tools: `get_question`, `temporal_search_articles`, `fetch_article`,
`identify_forecast_event`, `create_forecast_causal_link`, `inspect_forecast_graph`,
`propose_forecast_subgraph`, `submit_forecast`.

See `src/api/mcp_forecasting_server.py` for full tool documentation.
