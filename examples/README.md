# Using WorldReasoner with External Agents

WorldReasoner exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server
that gives any MCP-compatible agent temporal forecasting capabilities — searching articles
published before a given date, building causal event graphs, and submitting calibrated predictions.

## Quick start

```bash
# 1. Install and configure
uv sync
cp config/config.example.yaml config/config.yaml  # add LLM API keys

# 2. Start the MCP server (stdio mode — for agents that manage their own process)
uv run worldreasoner-mcp-forecast --transport stdio --db combined.db

# 3. Or HTTP mode — for agents that connect over the network
uv run worldreasoner-mcp-forecast --transport http --port 8110 --db combined.db
```

---

## Connecting agents

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "worldreasoner": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/worldreasoner",
               "worldreasoner-mcp-forecast", "--transport", "stdio",
               "--db", "/path/to/worldreasoner/combined.db"]
    }
  }
}
```

See [`mcp-configs/claude-desktop.json`](mcp-configs/claude-desktop.json).

### Claude Code

```bash
# From the worldreasoner repo root:
claude mcp add worldreasoner -- uv run worldreasoner-mcp-forecast --transport stdio --db combined.db
```

Or add [`mcp-configs/claude-code.json`](mcp-configs/claude-code.json) as `.mcp.json` in the repo root.

### OpenAI Codex / Agents SDK

```bash
codex --mcp-server "uv run worldreasoner-mcp-forecast --transport stdio --db combined.db"
```

See [`mcp-configs/openai-codex.json`](mcp-configs/openai-codex.json).

### Any MCP-compatible agent (generic stdio)

```bash
# The server reads context from the client session metadata:
#   question_id     — which question to forecast (required)
#   simulated_date  — "today" for temporal access control (required)
#   knowledge_cutoff — agent's training cutoff, for contamination filtering (optional)
uv run worldreasoner-mcp-forecast --transport stdio --db combined.db
```

---

## What the agent can do

Once connected, the agent has access to these MCP tools:

| Tool | What it does |
|---|---|
| `get_question` | Read question text, resolution date, and temporal context |
| `temporal_search_articles` | Search articles published **before** `simulated_date` |
| `fetch_article` | Fetch full article content (temporally validated) |
| `identify_forecast_event` | Extract and store a causal event from an article |
| `create_forecast_causal_link` | Link two events with a typed causal relation |
| `propose_forecast_subgraph` | Batch-create events + edges in one call |
| `inspect_forecast_graph` | Check graph quality (event count, depth, coverage) |
| `delete_forecast_event` | Remove an incorrectly identified event |
| `submit_forecast` | Submit prediction + confidence + reasoning |

### Example agent prompt

```
You are a forecasting agent. Use the WorldReasoner tools to:
1. Call get_question to read the question and note the simulated_date
2. Search for 5-10 relevant articles using temporal_search_articles
3. Identify the 3-5 most causally important events using identify_forecast_event
4. Link them causally using create_forecast_causal_link or propose_forecast_subgraph
5. Call inspect_forecast_graph to verify the graph makes sense
6. Submit your calibrated probability using submit_forecast

Remember: you can only see information published before the simulated_date.
```

---

## Evaluating submitted forecasts

`submit_forecast` saves the prediction to the database but **does not score it immediately** — evaluation happens separately once the question has resolved and `ground_truth` is set.

### Step 1 — mark the question as resolved

Once you know the outcome, set it via the REST API or CLI:

```bash
# Via CLI
uv run wr db update question <question_id> ground_truth true   # or false

# Via REST API (backend must be running)
curl -X PATCH http://localhost:8300/api/questions/<question_id> \
  -H "Content-Type: application/json" \
  -d '{"ground_truth": true}'
```

### Step 2 — score all resolved forecasts

```bash
# Via CLI (writes per-condition JSON + Markdown to experiments/evaluation/)
uv run wr benchmark evaluate --db combined.db

# Via REST API (scores in background, updates is_correct + brier_score on each forecast)
curl -X POST http://localhost:8300/api/evaluation/run \
  -H "Content-Type: application/json" \
  -d '{"update_forecasts": true}'
```

### Step 3 — retrieve results

```bash
# Aggregate accuracy/Brier across all evaluated forecasts
curl http://localhost:8300/api/evaluation/report

# Per-forecast scores for a specific question
curl http://localhost:8300/api/questions/<question_id>/forecasts

# Full benchmark matrix (all conditions × models)
curl http://localhost:8300/api/benchmark/results
```

Each forecast record gets the full metric set once both evaluation steps run:

**Step A — outcome metrics** (written by `wr benchmark evaluate` / `POST /api/evaluation/run`):

| Field | Description |
|---|---|
| `is_correct` | `true` / `false` — whether prediction matched ground truth |
| `brier_score` | `(confidence − outcome)²` — 0 is perfect, 1 is worst |
| `log_score` | `log(prob_of_correct_outcome)` — penalises confident wrong answers |

**Step B — reasoning graph metrics** (written by `evaluate_reasoning_graphs.py` / dashboard "Re-evaluate" button):

| Field | Description |
|---|---|
| `event_f1` | F1 between agent events and hindsight events |
| `event_recall` / `event_precision` | Component scores |
| `accessible_event_f1` | F1 using only events before `simulated_date` as denominator |
| `exact_source_precision` | Fraction of agent-cited sources in hindsight evidence set |
| `key_event_recall` / `key_event_precision` | Coverage of annotated key events |
| `temporal_mae_days` | Mean absolute error in event date estimates |
| `market_signal_recall` | Coverage of price-moving events |
| `edge_recall` / `edge_precision` | Causal edge alignment with hindsight graph |

Both are available on `GET /api/questions/{id}/forecasts` per forecast, and aggregated on `GET /api/evaluation/report` under `reasoning_metrics`.

### With contamination filtering

If you want scores that exclude questions where the agent's training cutoff predates the question start (i.e. the paper methodology):

```bash
uv run wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage
```

Or toggle "Contam. filter" in the dashboard Benchmark tab.

---

## Agent Skills

The `skills/` directory contains [Agent Skills](https://agentskills.io) — reusable instruction
sets that agents supporting the standard (Claude Code, Cursor, Copilot, Gemini CLI, OpenHands,
and others) auto-discover and activate for relevant tasks:

| Skill | Activates when |
|---|---|
| [`skills/forecast-question/`](../skills/forecast-question/SKILL.md) | Asked to forecast a question or collect evidence |
| [`skills/run-forecast-benchmark/`](../skills/run-forecast-benchmark/SKILL.md) | Asked to run a benchmark or compare conditions |

---

## Setting context per forecast session

The MCP server uses **session metadata** (HTTP headers in HTTP mode, or connection
metadata in stdio mode) to scope each forecast:

| Field | Required | Description |
|---|---|---|
| `X-Question-ID` | Yes | Question ID from the database |
| `X-Simulated-Date` | Yes | ISO datetime — "today" for temporal access control |
| `X-Knowledge-Cutoff` | No | Agent training cutoff — used for contamination filtering |

In Claude Desktop / stdio mode these are set by the agent framework automatically
when it connects. In HTTP mode, include them as request headers.

---

## Preparing the database

The MCP tools need questions and evidence in the database. Use the `wr` CLI:

```bash
# Add a question manually
uv run wr db update question <id> ...      # or use the programmatic API

# Collect evidence for a question
uv run wr evidence run -q <question_id>

# Build causal graph
uv run wr graph build -q <question_id>

# Verify it's ready
uv run wr benchmark status --db combined.db
```

See the main [README](../README.md) and [docs/](../docs/) for the full workflow.
