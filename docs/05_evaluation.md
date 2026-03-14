# Section 5: Evaluation

This section covers the full evaluation system: the experiment dataset, models under test, experimental conditions, scoring metrics, benchmark execution, and result visualization.

---

## 5.1 Overview

Evaluation is **strictly separated** from the forecasting agent to prevent any information leakage:

1. **Forecasting (Simulated Past)**: The agent makes a prediction. It has no access to ground truth and can only retrieve evidence published before `simulated_date`.
2. **Evaluation (Present)**: After forecasting is complete, the evaluator compares the forecast against the known ground truth using standard scoring metrics.

The `ForecastEvaluator` and all scoring logic live in `src/domain/evaluation/metrics.py`. They are never exposed to or called by the forecasting agent.

---

## 5.2 Experimental Dataset

The benchmark uses a curated dataset of **300 resolved questions** stored in `experiment.db`.

| Dimension | Value |
|-----------|-------|
| Total questions | 300 |
| Domains | 6 (Finance, Politics, Sports, Culture, Climate, Health) |
| Time horizons | 3 (Short, Medium, Long) |
| Sources | Polymarket + News pipeline |

For full dataset composition details, see [Section 2.4](02_data_collection.md#24-dataset-composition).

---

## 5.3 Models Under Test

The benchmark is designed to evaluate **6 models × 6 conditions × 300 questions = 10,800 total runs**.

| Model | LiteLLM ID | Role |
|-------|-----------|------|
| GPT-5 | `gpt-5` | Frontier (OpenAI) |
| Claude 4.5 Sonnet | `anthropic/claude-sonnet-4-5-20250514` | Frontier (Anthropic) |
| Gemini 2.5 Pro | `gemini/gemini-2.5-pro` | Frontier (Google) |
| Gemini 2.5 Flash | `gemini/gemini-2.5-flash` | Scaling baseline (cost-efficient) |
| DeepSeek V3 | `deepseek/deepseek-chat` | Open-weight frontier |
| Qwen 3 | `qwen/qwen3` | Open-weight frontier |

---

## 5.4 Experimental Conditions

Six conditions form an ablation study across search mode, causal tools, and information access. Conditions are defined in `src/domain/evaluation/conditions.py`.

| # | Condition | CLI Name | Mode | Causal Tools | Oracle | Max Steps | Description |
|---|-----------|----------|------|:------------:|:------:|----------:|-------------|
| 1 | Vanilla LLM | `vanilla_llm` | `knowledge_only` | No | No | 10 | Baseline: LLM forecasts from training knowledge only |
| 2 | Structured Scenario | `structured_scenario` | `knowledge_only` | Yes | No | 25 | LLM + causal reasoning tools, no external search |
| 3 | Search-Enabled | `search_enabled` | `container` | No | No | 15 | LLM + article search via MCP, no causal structure |
| 4 | WorldReasoner | `worldreasoner` | `container` | Yes | No | 25 | Full system: search + causal reasoning |
| 5 | Oracle | `oracle` | `container` | Yes | Yes | 25 | Full system with near-resolution-date info (upper bound) |
| 6 | Real-Time | `real_time` | `real_time` | Yes | No | 25 | Full system using live internet access |

List available conditions at any time:
```bash
wr benchmark conditions
```

---

## 5.5 Evaluation Metrics

All metrics are computed per-condition and aggregated across questions. Implementation: `src/domain/evaluation/metrics.py`.

| Metric | Range | Better | Description |
|--------|-------|--------|-------------|
| **Accuracy** | 0.0–1.0 | Higher | Binary/MCQ: exact match. Quantity: within 10% tolerance. Simple fraction of correct predictions. |
| **Brier Score** | 0.0–1.0 | Lower | Mean squared error: `(probability - outcome)²`. Perfect = 0. Primary metric for competitive comparison. |
| **Log Score** | -∞–0.0 | Higher | Logarithmic scoring rule. Heavily penalizes confident wrong answers. Rewards well-calibrated uncertainty. |
| **Calibration Error** | 0.0–1.0 | Lower | Mean absolute difference between stated confidence bins and actual accuracy. |

**Python API:**
```python
from src.domain.evaluation import ForecastEvaluator

evaluator = ForecastEvaluator()
results = evaluator.evaluate_all_resolved(update_forecasts=True)
print(f"Overall Accuracy: {results['overall_accuracy']:.2%}")
```

**CLI:**
```bash
# Evaluate all resolved forecasts
python examples/evaluate_forecasts.py

# Evaluate a specific forecast
python examples/evaluate_forecasts.py --forecast-id fcst_123

# Output JSON report
python examples/evaluate_forecasts.py --output report.json
```

---

## 5.6 Evaluation Setup Prerequisites

Complete these steps before running any benchmark:

**Step 1: Resolved questions in database**

Questions must have `resolution` and `resolution_date` set. The experiment dataset (`experiment.db`) should already have these from the collection phase (see [Section 2](02_data_collection.md)).

**Step 2: Evidence collected and reviewed**

```bash
# Collect evidence (stratified sample or full)
wr evidence run --db experiment.db --sample 50

# Review events for accuracy (manual — interactive)
wr evidence review --db experiment.db --sample 30

# OR auto-review using LLM (faster, recommended)
wr evidence auto-review --db experiment.db --sample 30
```

**Step 3: Search index built**

Required for `container` mode conditions (3, 4, 5):
```bash
wr db build-index --db experiment.db
```

**Step 4: MCP forecasting server running**

Required for `container` mode conditions:
```bash
python src/mcp_forecasting_server.py
# Default port: 8110
```

**Step 5: LLM knowledge cutoff dates**

Needed for temporal access control to enforce per-model training cutoffs:
```bash
python scripts/fetch_knowledge_cutoff_date.py
```

Ensure `config/config.yaml` has a valid LLM provider configured before running.

---

## 5.7 Running the Benchmark

The primary benchmark script is `examples/run_benchmark_evaluation.py`. It identifies resolved questions, runs the `ForecastAgent` with temporal masking, and calculates metrics.

### Full Benchmark (All Conditions)

```bash
# Run all 6 conditions with default model on all resolved questions
wr benchmark run --db experiment.db -y

# Dry run — shows plan without executing
wr benchmark run --db experiment.db
```

### Single Condition

```bash
# Vanilla LLM baseline only
wr benchmark run --db experiment.db -c vanilla_llm -y

# WorldReasoner full system only
wr benchmark run --db experiment.db -c worldreasoner -y
```

### Multiple Models

```bash
# Compare two models across all conditions
wr benchmark run --db experiment.db -m gemini/gemini-2.5-flash -m gpt-5 -y

# Single condition, multiple models
wr benchmark run --db experiment.db -c vanilla_llm -m gemini/gemini-2.5-flash -m gpt-5 -y
```

### Limiting Questions

```bash
# Quick test: 5 questions, one condition
wr benchmark run --db experiment.db -c vanilla_llm -n 5 -y

# Filter by domain
wr benchmark run --db experiment.db --domain finance -y

# Filter by source
wr benchmark run --db experiment.db --source polymarket -y

# Specific questions
wr benchmark run --db experiment.db -q q_finance_123 -q q_politics_456 -y
```

### Resuming Interrupted Runs

```bash
# Resume from where it left off (skips completed question/condition/model triples)
wr benchmark run --db experiment.db --resume -y
```

### Offset Days

By default, the simulated date is based on the question's `estimated_start_time`. Use `--offset-days` to shift the simulated date earlier relative to the resolution date:

```bash
# Simulate forecasting 7 days before resolution
wr benchmark run --db experiment.db --offset-days 7 -y
```

### Key Script Options

| Flag | Description | Default |
|------|-------------|---------|
| `--model` | LLM model to test | Config default |
| `--knowledge-only` | Disable external research tools | `False` |
| `--offset-days` | Analysis point relative to resolution (0 = at resolution) | `0` |
| `--knowledge-cutoff` | Simulate a specific past date for training cutoff | None |
| `--min-context-items` | Minimum articles/events required before forecasting | `3` |
| `--output` | Custom path for results JSON | `benchmarks/autobench_<time>.json` |

---

## 5.8 Results Format

Results are saved as JSON files in `benchmarks/`:
```
benchmarks/autobench_<timestamp>.json
```

Each file contains:

```json
{
  "run_id": "...",
  "conditions": {
    "vanilla_llm": {
      "accuracy": 0.62,
      "brier_score": 0.21,
      "log_score": -0.45,
      "calibration_error": 0.08,
      "n_questions": 300
    }
  },
  "individual_results": [
    {
      "question_id": "q_finance_123",
      "condition": "vanilla_llm",
      "model": "gpt-5",
      "prediction": "Yes",
      "confidence": 0.75,
      "ground_truth": "Yes",
      "correct": true,
      "brier_score": 0.0625,
      "log_score": -0.287
    }
  ],
  "leaderboard": [...]
}
```

A summary report is also printed to the console after each run.

---

## 5.9 Visualization

Generate comparative charts from benchmark JSON files.

```bash
# Multi-metric side-by-side (accuracy, Brier, log score) — default
python examples/visualize_benchmarks.py

# Save to file instead of displaying
python examples/visualize_benchmarks.py --output benchmarks/figures/results.png

# Single metric
python examples/visualize_benchmarks.py --metric accuracy
python examples/visualize_benchmarks.py --metric brier

# Text summary table (no GUI required)
python examples/visualize_benchmarks.py --table

# Custom output directory
python examples/visualize_benchmarks.py --output-dir my_figures/
```

**Output files:**
- `accuracy_comparison.png` — Bar chart by model/condition
- `brier_score_comparison.png` — Calibration quality (lower is better)
- `performance_timeline.png` — Accuracy trends over time

The visualizer loads both `autobench_*.json` (from `wr benchmark run`) and legacy `benchmark_*.json` files from the `benchmarks/` directory.

**Temporal Analysis:**

To understand how early a model can predict a specific event:
```bash
python examples/run_temporal_forecast_analysis.py --question-id <id> --num-points 5
```

This generates a timeline showing context availability versus forecast confidence across multiple simulated dates.

---

## 5.10 Recommended Evaluation Order

Run conditions in order of cost (cheapest first) to validate setup before committing to expensive runs:

1. **`vanilla_llm`** — No MCP server needed; fastest (10 steps max); cheapest API cost
2. **`structured_scenario`** — No MCP server needed; uses causal tools from memory
3. **`search_enabled`** — Requires MCP server + search index
4. **`worldreasoner`** — Requires MCP server + search index + event graph
5. **`oracle`** — Most expensive; uses near-resolution-date information
6. **`real_time`** — Uses live search engines; ignores clock simulation overrides

```bash
# Step-by-step evaluation
wr benchmark run --db experiment.db -c vanilla_llm -n 10 -y      # Quick sanity check
wr benchmark run --db experiment.db -c vanilla_llm -y             # Full baseline
wr benchmark run --db experiment.db -c structured_scenario -y
wr benchmark run --db experiment.db -c search_enabled -y
wr benchmark run --db experiment.db -c worldreasoner -y
wr benchmark run --db experiment.db -c oracle -y
wr benchmark run --db experiment.db -c real_time -y
```

---

## 5.11 Best Practices

- **Never** expose `ground_truth` to forecasting agents. Evaluation and forecasting are fully separate processes.
- Use **Brier Score** as the primary metric for competitive model comparison (it is the most interpretable probabilistic metric).
- Run evaluation on a schedule (e.g., cron job) to catch newly resolved questions.
- Always run `vanilla_llm` first — it serves as the baseline against which all other conditions are measured.
- When testing a new model, run a small subset (`-n 10`) before committing to a full run.
- Use `--resume` to recover from API failures or interrupted runs without re-running completed work.

---

## 5.12 CI/CD Integration

To run weekly benchmarks via GitHub Actions:

```yaml
- name: Run benchmark
  run: python examples/run_benchmark_evaluation.py --max-questions 10
```

**Potential future enhancements:**
1. Parallel execution — run multiple forecasts simultaneously to reduce wall time
2. Ensemble methods — combine predictions from multiple models
3. Active learning — identify questions where models disagree most
4. Cost tracking — monitor API costs per benchmark run
5. Domain-specific analysis — compare performance across domains
6. Multi-question temporal analysis — aggregate temporal patterns across the dataset

---

*For the complete CLI reference including all `wr benchmark` options, see [Appendix A](appendix/A_cli_reference.md).*
