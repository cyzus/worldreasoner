# Scripts

Scripts are supplementary tools that complement the `wr` CLI. Most day-to-day
operations are available as CLI commands — see `wr --help`. The scripts here
cover benchmark evaluation, paper figures, and DB screening.

All scripts run from the repo root:
```bash
uv run python scripts/<path>.py [options]
```

---

## CLI commands (promoted from scripts)

| Old script | New command |
|---|---|
| `init_db.py` | `wr db init` |
| `build_search_index.py` | `wr db build-index` |
| `merge_databases.py` | `wr db merge` |
| `cleanup.py` | `wr db clean` |
| `fetch_knowledge_cutoff_date.py` | `wr db fetch-cutoffs` |
| `run_experiment_collection.py` | `wr question collect` |
| `select_prolific_questions.py` | `wr question select` |
| `rerun_evidence.py` | `wr evidence rerun` |
| `evaluate_benchmark.py` (core) | `wr benchmark evaluate` |
| `evaluate_reasoning_graphs.py` (core) | `wr benchmark run` → Re-evaluate button |

---

## Benchmark

### `benchmark/cleanup_experiment_db.py`
Reclassify "general"-domain questions and remove low-quality micro-duration
markets from the benchmark DB.
```bash
uv run python scripts/benchmark/cleanup_experiment_db.py --db combined.db --dry-run
uv run python scripts/benchmark/cleanup_experiment_db.py --db combined.db
```

### `benchmark/contamination_report.py`
Per-condition benchmark evaluation with contamination-filter comparison tables and
SVG charts. Wraps `wr benchmark evaluate` with side-by-side all vs. clean output.
```bash
uv run python scripts/benchmark/contamination_report.py
uv run python scripts/benchmark/contamination_report.py --condition vanilla_llm
uv run python scripts/benchmark/contamination_report.py --db other.db
```
Output: `experiments/evaluation/contamination_*.md/.tsv/.svg`

### `benchmark/evaluate_graphs.py`
Evaluate forecast event graphs against hindsight reference graphs (event coverage
metrics).
```bash
uv run python scripts/benchmark/evaluate_graphs.py --db combined.db
```

### `benchmark/evaluate_reasoning_graphs.py`
Full reasoning-graph evaluation: event F1, key-event recall, source precision,
temporal MAE. Also available via the dashboard "Re-evaluate" button.
```bash
uv run python scripts/benchmark/evaluate_reasoning_graphs.py \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage \
  --exclude-annotation-rejected
```
Output: `experiments/evaluation/canonical_final/reasoning_graph_eval_filtered_latest.json`

### `benchmark/export_public_db.py`
Export a sanitized version of `combined.db` for public release (strips article
content, forecast reasoning text, audit tables).
```bash
uv run python scripts/benchmark/export_public_db.py \
  --src combined.db --dst worldreasoner_public.db
```

---

## Paper figures

All figure scripts write to `assets/figures/` by default.

### `analysis/plot_sliding_window.py`
Sliding-window ablation — accuracy across early/mid/late/near-res/real-time slots.
```bash
uv run python scripts/analysis/plot_sliding_window.py [--db combined.db]
```
Output: `assets/figures/sliding_window.pdf/.png`

### `analysis/plot_reasoning_quality.py`
Per-model reasoning quality — 3-row panel (Event F1, Key-event Recall, Source
Precision) across conditions.
```bash
uv run python scripts/analysis/plot_reasoning_quality.py
uv run python scripts/analysis/plot_reasoning_quality.py \
  --eval-json experiments/evaluation/reasoning_graph_eval_filtered_latest.json
```
Output: `assets/figures/reasoning_quality.pdf/.png`

### `benchmark/temporal_forecast_analysis.py`
Analyze how forecast accuracy evolves as the resolution date approaches for a
single question — runs live forecasts at multiple temporal points.
```bash
uv run python scripts/benchmark/temporal_forecast_analysis.py \
  --question-id <ID> --db combined.db
```

### `benchmark/plot_vanilla_time_performance.py`
Vanilla-LLM accuracy over time (question resolution date).
```bash
uv run python scripts/benchmark/plot_vanilla_time_performance.py --db combined.db
```

### `figures/render_pressure_charts.py`
Causal pressure charts — resolved questions as dated hindsight event timelines
with signed impact links.
```bash
uv run python scripts/figures/render_pressure_charts.py --db combined.db
```

---

## Paper numbers

### `analysis/compute_metrics_table.py`
Compute all paper metrics from the reasoning eval JSON and append a results table
to `docs/metrics.md`.
```bash
uv run python scripts/analysis/compute_metrics_table.py
```

### `analysis/final_numbers.py`
Print the paper table numbers side-by-side from the two eval JSONs (original vs
annotation-filtered). Useful for paper revision to verify numbers match.
```bash
uv run python scripts/analysis/final_numbers.py
```

### `analysis/sliding_window_results.py`
Temporal ablation: per-model accuracy and Brier score across early/mid/late/
near-resolution/real-time slots. Contains the DB queries for Table 3 and
the knowledge-only gap analysis.
```bash
uv run python scripts/analysis/sliding_window_results.py --db combined.db
uv run python scripts/analysis/sliding_window_results.py --db combined.db --latex
```

---

## Screening

### `screening/apply_decisions.py`
Apply manual screening decisions from `batch_*.json` files to the database.
```bash
uv run python scripts/screening/apply_decisions.py --db combined.db
```

**Files in `screening/`** (gitignored — kept locally):
- `batch_*.json` — raw screening inputs
- `results_batch_*.json` — annotator decisions

---

## Recommended workflow

```bash
# 1. Set up the database
wr db init --db combined.db
wr db clean --db combined.db --execute
wr db build-index --db combined.db

# 2. Collect and process questions
wr question collect --db combined.db
wr evidence rerun --db combined.db

# 3. Run benchmark (paper setup)
wr benchmark run \
  -c vanilla_llm -c structured_scenario -c search_enabled \
  -c worldreasoner -c oracle -c real_time \
  -m gemini/gemini-3-flash-preview -m gemini/gemini-3-pro-preview \
  -m deepseek/deepseek-v4-flash -m deepseek/deepseek-v4-pro \
  -m dashscope/qwen3.5-397b-a17b \
  --question-ids include_ids.txt --db combined.db

# 4. Score results
wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# 5. Reasoning graph evaluation
uv run python scripts/benchmark/evaluate_reasoning_graphs.py \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage \
  --exclude-annotation-rejected

# 6. Generate paper figures
uv run python scripts/analysis/plot_reasoning_quality.py
uv run python scripts/analysis/plot_sliding_window.py
uv run python scripts/benchmark/plot_vanilla_time_performance.py
uv run python scripts/benchmark/contamination_report.py
```
