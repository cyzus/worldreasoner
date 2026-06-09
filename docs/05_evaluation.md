# Section 5: Evaluation

Evaluation of WorldReasoner forecasts covers dataset selection, contamination filtering, scoring metrics, benchmark execution, and result analysis.

---

## 5.1 Overview

Evaluation is **strictly separated** from the forecasting agent:

1. **Forecasting (simulated past)** — the agent predicts. It has no access to ground truth and can only retrieve evidence published before `simulated_date`.
2. **Evaluation (present)** — after forecasting completes, the evaluator compares the prediction against the known ground truth using standard scoring metrics.

All scoring logic lives in `src/domain/evaluation/metrics.py` and is never called by the forecasting agent.

---

## 5.2 Benchmark Dataset

The paper benchmark uses a curated subset of **120 resolved questions** stored in `combined.db`. Question IDs are listed in `include_ids.txt`.

| Dimension | Value |
|-----------|-------|
| Questions | 120 (from `include_ids.txt`) |
| Sources | Polymarket |
| Domains | Politics, Economics, Science, Technology, Sports, Culture |
| Resolution | All resolved with known ground truth |
| Evidence | Causal event graphs built and quality-reviewed |

The full database (`combined.db`) contains ~345 questions; only the 120 curated questions are used for paper results to ensure quality and annotation completeness.

---

## 5.3 Models

| Model | LiteLLM ID |
|-------|-----------|
| Gemini 3 Flash | `gemini/gemini-3-flash-preview` |
| Gemini 3 Pro | `gemini/gemini-3-pro-preview` |
| DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` |
| DeepSeek V4 Pro | `deepseek/deepseek-v4-pro` |
| Qwen 3.5 397B | `dashscope/qwen3.5-397b-a17b` |
| GPT-4o | `openai/gpt-4o-2024-11-20` |

---

## 5.4 Experimental Conditions

Six conditions form an ablation across search mode, causal tools, and information access. Defined in `src/domain/evaluation/conditions.py`.

| # | Paper name | CLI name | Search | Causal tools | Oracle |
|---|------------|----------|:------:|:------------:|:------:|
| 1 | Vanilla LLM | `vanilla_llm` | | | |
| 2 | Causal Simulation | `structured_scenario` | | ✓ | |
| 3 | Search-Enabled | `search_enabled` | ✓ | | |
| 4 | Search-Enabled Graph | `worldreasoner` | ✓ | ✓ | |
| 5 | Near-Resolution | `oracle` | ✓ | ✓ | ✓ |
| 6 | Real-Time | `real_time` | live | ✓ | |

```bash
wr benchmark conditions        # list all conditions with descriptions
```

---

## 5.5 Scoring Metrics

All metrics are computed in `src/domain/evaluation/metrics.py` and `src/domain/evaluation/benchmark_eval.py`. See [metrics.md](metrics.md) for full definitions.

### Forecasting accuracy

| Metric | Better | Notes |
|--------|--------|-------|
| **Accuracy** | Higher | Fraction correct. Binary/MCQ: exact match. Quantity: ±10% tolerance. |
| **Brier Score** | Lower | `(forecast_prob − outcome)²`. Range 0–1. Primary ranking metric. |
| **Log Score** | Higher | `log(prob_of_correct_outcome)`. Penalises confident wrong answers. |

### Reasoning graph quality

Computed by matching agent-produced events against the hindsight graph for each question. Implementation: `scripts/benchmark/evaluate_reasoning_graphs.py`.

| Metric | Better | Notes |
|--------|--------|-------|
| **Source Precision** | Higher | Fraction of agent-cited sources that appear in the hindsight evidence set. Undefined for knowledge-only conditions. |
| **Event F1** | Higher | Token-level F1 between agent event descriptions and hindsight events. |
| **Key-Event Recall** | Higher | Fraction of paper-annotated key events mentioned by the agent. |
| **Key-Event F1** | Higher | Harmonic mean of key-event precision and recall. |
| **Key-Event Precision** | Higher | Fraction of agent events that match a key event. |
| **Temporal MAE** | Lower | Mean absolute error in days between agent event dates and ground truth. Only for conditions with structured event output. |

Contamination filtering (see §5.6) is applied before computing any aggregate metrics.

---

## 5.6 Contamination Filtering

A question is **contaminated** for a given model if:

```
question.estimated_start_time < model.knowledge_cutoff_date
```

This means the model may have seen the question's resolution in training data, making its forecast trivially easy. Contaminated `(model, question)` pairs are excluded before computing accuracy and Brier score.

Contamination has a large effect on models with late cutoffs. For example, DeepSeek V4 (cutoff 2025-05-01) has 52 of 120 questions excluded, shifting accuracy from ~65% to ~53% on `vanilla_llm`.

**CLI (paper evaluation):**
```bash
wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage
```

**Dashboard:** the Benchmark tab has a "Contam. filter" toggle that is **on by default** to show paper-consistent numbers.

Knowledge cutoff dates are stored in `config/llm_cutoff_dates.json` and can be refreshed with:
```bash
wr db fetch-cutoffs --output config/llm_cutoff_dates.json
```

---

## 5.7 Running the Benchmark

### Prerequisites

```bash
# 1. Database set up and indexed
wr db init --db combined.db
wr db build-index --db combined.db

# 2. MCP server running (needed for search/oracle conditions)
uv run worldreasoner-mcp-forecast

# 3. LLM API keys configured in config/config.yaml
```

### Run commands

```bash
# Quick sanity check — 5 questions, one condition
wr benchmark run -c vanilla_llm -n 5

# Full paper run — all conditions, specific models, curated question set
wr benchmark run \
  -c vanilla_llm -c structured_scenario -c search_enabled \
  -c worldreasoner -c oracle -c real_time \
  -m gemini/gemini-3-flash-preview -m deepseek/deepseek-v4-flash \
  --question-ids include_ids.txt \
  --db combined.db

# Resume an interrupted run (skips completed triples)
wr benchmark run -c worldreasoner --resume

# Filter by domain or source
wr benchmark run -c vanilla_llm --domain politics --source polymarket
```

### Recommended order (cheapest first)

1. `vanilla_llm` — no MCP server, fastest (training knowledge only)
2. `structured_scenario` — no MCP server, uses causal reasoning tools
3. `search_enabled` — requires MCP server + search index
4. `worldreasoner` — requires MCP server + search index
5. `oracle` — most expensive, upper-bound reference
6. `real_time` — uses live internet, bypasses temporal simulation

---

## 5.8 Scoring Saved Runs

After running the benchmark, score the results with contamination filtering:

```bash
# Score a specific condition against the paper question set
wr benchmark evaluate \
  --condition worldreasoner \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# Score all conditions (produces per-condition JSON + Markdown)
wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage \
  --output-dir experiments/evaluation/
```

Results are written to `experiments/evaluation/<condition>_eval_<timestamp>.json` and `.md`.

### Result format

```json
{
  "condition": "worldreasoner",
  "all": {
    "overall": { "accuracy": 0.694, "total": 120 },
    "by_model": { "gemini/gemini-3-flash-preview": { "accuracy": 0.675, "total": 120 } }
  },
  "clean": {
    "overall": { "accuracy": 0.682, "total": 98 },
    "by_model": { "gemini/gemini-3-flash-preview": { "accuracy": 0.648, "total": 108 } }
  }
}
```

`clean` is the contamination-filtered subset and matches the paper numbers.

---

## 5.9 Dashboard

The research dashboard provides an interactive condition × model matrix:

```bash
uv run worldreasoner --reload          # backend
cd frontend && npm run dev             # frontend → http://localhost:5173
```

Navigate to the **Benchmark** tab. The matrix shows accuracy (or Brier score) for each `(condition, model)` cell using the most recent run. The "Contam. filter" toggle applies contamination filtering server-side via `GET /benchmark/results/{run_id}/filtered`.

---

## 5.10 Reproducing Paper Figures

```bash
# Metrics table → docs/metrics.md
uv run python scripts/analysis/compute_metrics_table.py

# Reasoning quality figure (Event F1, Key-event Recall, Source Precision)
uv run python scripts/analysis/plot_reasoning_quality.py

# Sliding-window ablation figure
uv run python scripts/analysis/plot_sliding_window.py

# Vanilla-LLM accuracy over time
uv run python scripts/benchmark/plot_vanilla_time_performance.py --db combined.db
```

See [scripts/README.md](../scripts/README.md) for the full reproduction workflow.

See [scripts/README.md](../scripts/README.md) for the full list of reproduction scripts.

---

*For the complete `wr benchmark` CLI reference, run `wr benchmark --help`.*
