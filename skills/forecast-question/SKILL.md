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

## Step 0 (optional): Create a fresh database

The workflow defaults to the existing `combined.db` / `worldreasoner.db`. To start from a new, empty dataset instead, create and initialize one — this creates the file (if absent) and builds all tables:

```bash
uv run wr db init --db mydataset.db
```

Then pass `--db mydataset.db` to the commands below. (Note: `wr question add` and `wr question add-polymarket` also create the db on the fly if `--db` points to a new path, so this step is only needed when you want an explicit empty dataset up front.)

## Step 1: Add the question

```bash
uv run wr question add \
  --text "Will X happen by Y date?" \
  --resolution-date 2025-12-31 \
  --source manual \
  --domain politics
```

Note the question ID printed after creation (e.g. `q_manual_1781264253_cd27431c`).

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
# For a manual question: set ground truth by hand once it resolves
uv run wr db update question <question_id> ground_truth true

# For a Polymarket question: backfill outcomes that have resolved since ingestion
# (the API server also does this automatically on startup)
uv run wr question refresh-polymarket --db combined.db

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

## Troubleshooting

- **`failed to remove file ... Scripts\worldreasoner.exe ... (os error 32)` (Windows):** the API server is running and locks the binary, so `uv run`'s pre-run sync can't reinstall the project. Run the CLI without syncing — `uv run --no-sync wr <command>` — or stop the running server first. (`wr` and `worldreasoner` are separate entry points; only the server binary is locked.)
