# Examples

End-to-end usage examples for WorldReasoner.

## `forecast_custom_question.py`

Add a custom forecast question, collect evidence, run a forecast, and evaluate — all via the `wr` CLI.

```bash
# Full pipeline (adds question, collects evidence, builds graph, forecasts)
uv run python examples/forecast_custom_question.py

# With a specific model and database
uv run python examples/forecast_custom_question.py \
  --db combined.db \
  --model gemini/gemini-3-flash-preview \
  --mode container

# Skip evidence collection (if already collected)
uv run python examples/forecast_custom_question.py \
  --question-id <existing_id> \
  --no-evidence --no-graph

# Knowledge-only forecast (no search, no MCP server needed)
uv run python examples/forecast_custom_question.py \
  --mode knowledge_only
```

Edit `EXAMPLE_QUESTION` at the top of the script to use your own question.

## `external_agent_forecast.py`

Shows how an external agent connects to the WorldReasoner MCP server to run a temporally-gated forecast — searching articles, building a causal event graph, and submitting a prediction.

```bash
# Prerequisites
uv run worldreasoner --reload &             # REST API backend
uv run worldreasoner-mcp-forecast --port 8110 &  # MCP server

# Run (dry-run first to verify connectivity)
uv run python examples/external_agent_forecast.py \
  --question-id <question_id> \
  --dry-run

# Full run with explicit simulated date
uv run python examples/external_agent_forecast.py \
  --question-id <question_id> \
  --simulated-date 2025-06-01T00:00:00Z \
  --knowledge-cutoff 2024-10-01T00:00:00Z
```

The script shows the MCP tool call sequence an LLM agent should follow:
1. `get_question` — read question + temporal context
2. `temporal_search_articles` — find evidence published before `simulated_date`
3. `identify_forecast_event` — extract key events from articles
4. `create_forecast_causal_link` — link events causally
5. `inspect_forecast_graph` — verify graph quality
6. `submit_forecast` — submit prediction + confidence

Replace the placeholder prediction logic with your LLM's reasoning.

## Agent Skills

The `skills/` directory contains [Agent Skills](https://agentskills.io) — reusable instruction sets for AI coding agents (Claude Code, Cursor, Copilot, etc.):

| Skill | When it activates |
|---|---|
| `skills/forecast-question/` | Add, evidence-collect, and forecast a question |
| `skills/run-forecast-benchmark/` | Run the benchmark across conditions and models |
