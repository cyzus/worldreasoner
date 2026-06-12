---
name: run-forecast-benchmark
description: Run the WorldReasoner forecast benchmark across experimental conditions and models. Use when asked to benchmark LLM forecasting performance, compare conditions (vanilla_llm, structured_scenario, search_enabled, worldreasoner, oracle, real_time), evaluate accuracy or Brier score, or reproduce paper results.
license: MIT
compatibility: Requires Python 3.13+, uv, and a configured combined.db database. Run from the repo root.
metadata:
  author: worldreasoner
  version: "1.0"
---

# Run Forecast Benchmark

Runs LLM forecasts across experimental conditions and scores results with contamination filtering.

## Prerequisites

```bash
# Verify database exists and has questions
uv run wr db stats --db combined.db

# Verify search index is built (needed for search/oracle conditions)
uv run wr db build-index --db combined.db
```

## Step 1: Run the benchmark

```bash
# Quick test — 5 questions, one condition, one model
uv run wr benchmark run \
  -c vanilla_llm \
  -m gemini/gemini-3-flash-preview \
  -n 5 \
  --db combined.db

# Full paper setup — all 6 conditions, paper models, canonical 120 questions
uv run wr benchmark run \
  -c vanilla_llm -c structured_scenario -c search_enabled \
  -c worldreasoner -c oracle -c real_time \
  -m gemini/gemini-3-flash-preview -m gemini/gemini-3-pro-preview \
  -m deepseek/deepseek-v4-flash -m deepseek/deepseek-v4-pro \
  -m dashscope/qwen3.5-397b-a17b \
  --question-ids include_ids.txt \
  --db combined.db

# Resume an interrupted run
uv run wr benchmark run -c worldreasoner --resume --db combined.db
```

Results are saved to `experiments/benchmarks/autobench_<timestamp>.json`.

## Step 2: Score results

```bash
# Score with contamination filtering (matches paper numbers)
uv run wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# Score a specific condition
uv run wr benchmark evaluate \
  --condition worldreasoner \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage
```

Results written to `experiments/evaluation/<condition>_eval_<timestamp>.json`.

## Step 3: Check results in dashboard

```bash
uv run worldreasoner --reload &   # backend
cd frontend && npm run dev         # frontend → http://localhost:5173
# Navigate to Benchmark tab — contamination filter is on by default
```

## Experimental conditions

| Paper name | CLI name | What it tests |
|---|---|---|
| Vanilla LLM | `vanilla_llm` | Training knowledge only |
| Causal Simulation | `structured_scenario` | Causal reasoning, no search |
| Search-Enabled | `search_enabled` | Web search, no causal tools |
| Search-Enabled Graph | `worldreasoner` | Full system: search + causal |
| Near-Resolution | `oracle` | Upper bound (near-resolution info) |
| Real-Time | `real_time` | Live internet access |

## Contamination filtering

Questions where `estimated_start_time < model_knowledge_cutoff` are excluded before
computing metrics. This has a large effect on models with late cutoffs (e.g. DeepSeek
V4 loses ~52/120 questions, shifting accuracy by 7-11pp). The `--filter-knowledge-leakage`
flag applies this filter; omitting it shows unfiltered numbers.

## Troubleshooting

- **`No questions found`**: Run `wr db stats --db combined.db` to verify questions exist
- **`Search index missing`**: Run `wr db build-index --db combined.db`
- **`MCP server not running`**: Start with `uv run worldreasoner-mcp-forecast` before search/oracle conditions
- **`0.0% accuracy`**: Likely using wrong DB — verify questions are in `combined.db`
- **`failed to remove file ... Scripts\worldreasoner.exe ... (os error 32)` (Windows)**: A running server locks the binary so `uv run`'s sync can't reinstall. Use `uv run --no-sync wr <command>`, or stop the server first.
