# Scripts

Scripts are supplementary tools that complement the `wr` CLI. Most day-to-day
operations are now available as CLI commands — see `wr --help`. The scripts here
cover benchmark evaluation, paper figures, annotation study tooling, and DB
screening that don't fit naturally as interactive CLI commands.

All scripts run from the repo root:
```bash
uv run python scripts/<path>.py [options]
```

---

## CLI commands (promoted from scripts)

These operations were previously standalone scripts and are now `wr` subcommands:

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

---

## Benchmark

### `benchmark/cleanup_experiment_db.py`
Reclassify "general"-domain questions, remove low-quality micro-duration Bitcoin
markets, and report distribution against experiment targets.
```bash
uv run python scripts/benchmark/cleanup_experiment_db.py --db combined.db --dry-run
uv run python scripts/benchmark/cleanup_experiment_db.py --db combined.db
```

### `benchmark/contamination_report.py`
Run per-condition benchmark evaluation and produce contamination-filter comparison
tables and SVG charts (used in the paper). Builds on `wr benchmark evaluate` core.
```bash
uv run python scripts/benchmark/contamination_report.py
uv run python scripts/benchmark/contamination_report.py --condition vanilla_llm
uv run python scripts/benchmark/contamination_report.py --db other.db
```
Output: `experiments/evaluation/contamination_*.md/.tsv/.svg`

### `benchmark/evaluate_graphs.py`
Evaluate forecast graphs against hindsight reference graphs.
```bash
uv run python scripts/benchmark/evaluate_graphs.py --db combined.db
```

### `benchmark/evaluate_reasoning_graphs.py`
Evaluate reasoning graph quality (event F1, key-event recall, source precision).
```bash
uv run python scripts/benchmark/evaluate_reasoning_graphs.py --db combined.db
```

---

## Paper figures

All figure scripts write output to `assets/figures/` by default.

### `analysis/plot_sliding_window.py`
Sliding-window ablation figure — accuracy across early/mid/late/near-res/real-time
slots per model, line chart.
```bash
uv run python scripts/analysis/plot_sliding_window.py [--db combined.db] [--out assets/]
```
Output: `assets/figures/sliding_window.pdf` and `.png`

### `analysis/plot_reasoning_quality.py`
Per-model reasoning quality figure — 3-row panel (Event F1, Key-event Recall,
Source Precision) across conditions.
```bash
uv run python scripts/analysis/plot_reasoning_quality.py
uv run python scripts/analysis/plot_reasoning_quality.py --eval-json experiments/evaluation/reasoning_graph_eval_filtered_latest.json
```
Output: `assets/figures/reasoning_quality.pdf` and `.png`

### `benchmark/plot_vanilla_time_performance.py`
Vanilla-LLM accuracy over time (question resolution date) figure.
```bash
uv run python scripts/benchmark/plot_vanilla_time_performance.py --db combined.db
```

### `figures/render_pressure_charts.py`
Causal pressure charts — converts resolved questions into dated hindsight event
timelines with signed impact links.
```bash
uv run python scripts/figures/render_pressure_charts.py --db combined.db
```

---

## Paper numbers

### `analysis/compute_metrics_table.py`
Compute all implemented metrics from the eval JSON and append a results table to
`docs/metrics.md`.
```bash
uv run python scripts/analysis/compute_metrics_table.py
```

### `analysis/final_numbers.py`
Pull the final paper numbers from evaluation JSON (before/after annotation
filtering).
```bash
uv run python scripts/analysis/final_numbers.py
```

### `analysis/sliding_window_results.py`
Sliding-window ablation data dump — per-model accuracy & Brier score across slots,
knowledge-only gap. Use as input to `plot_sliding_window.py` or independently.
```bash
uv run python scripts/analysis/sliding_window_results.py --db combined.db
```

### `analysis/compare_semantic_robustness.py`
Compare hybrid (BM25+lexical) vs semantic (sentence-transformer) matching across
matching strategies. Intended for appendix.
```bash
uv run python scripts/analysis/compare_semantic_robustness.py
```

### `analysis/compare_annotation_eval.py`
Before/after comparison of reasoning graph eval with and without annotation
filtering.
```bash
uv run python scripts/analysis/compare_annotation_eval.py
```

---

## Annotation study

### `annotation_ui/recreate_wr_annotation.sh`
Rebuild the annotation study workspace from `combined.db` and the annotation UI
source. Run after `wr question select` updates `include_ids.txt`.
```bash
bash scripts/annotation_ui/recreate_wr_annotation.sh            # reuse cached prices
bash scripts/annotation_ui/recreate_wr_annotation.sh --fetch    # refresh price history
```

### `annotation_ui/export_data.py`
Export question data to `annotation_data_*.js` session files. Called by
`recreate_wr_annotation.sh`; can also be run directly.

### `annotation_ui/import_data.py`
Import completed annotation JSON files (downloaded from Google Drive) back into
the database.

### `annotation_ui/fetch_price_history.py`
Fetch and cache Polymarket price history for annotated questions.

### `analysis/annotation_quality.py`
Compute annotation quality metrics (IRR, attention checks, majority-vote
agreement) from the annotated session data.
```bash
uv run python scripts/analysis/annotation_quality.py
```
Output: `docs/annotation_quality.md`

### `analysis/apply_annotation_review.py`
Apply annotation majority votes to `events.review_status` in `combined.db`.
```bash
uv run python scripts/analysis/apply_annotation_review.py --db combined.db
```

### `analysis/check_attention.py`
Analyse attention-check pass/fail rates across annotation sessions.
```bash
uv run python scripts/analysis/check_attention.py
```

---

## Screening

### `screening/apply_decisions.py`
Apply manual screening decisions from `batch_*.json` files to the database.
```bash
uv run python scripts/screening/apply_decisions.py --db combined.db
```

**Files in `screening/`** (gitignored — kept locally):
- `batch_1.json` … `batch_6.json` — raw screening inputs
- `results_batch_1.json` … `results_batch_6.json` — annotator decisions
- `needs_evidence.json` — questions needing more evidence collection
- `CRITERIA.md` — screening criteria documentation

---

## Recommended workflow

```bash
# 1. Collect questions
wr question collect --db combined.db

# 2. Clean bad data
wr db clean --db combined.db --execute

# 3. Re-run evidence for low-source questions
wr evidence rerun --db combined.db

# 4. Select annotation questions
wr question select --db combined.db

# 5. Build annotation study
bash scripts/annotation_ui/recreate_wr_annotation.sh

# 6. Run benchmark
wr benchmark run --db combined.db -m <model> --resume -n 100 -w 8 -y

# 7. Evaluate results
wr benchmark evaluate --db combined.db

# 8. Generate paper figures
uv run python scripts/analysis/plot_sliding_window.py
uv run python scripts/analysis/plot_reasoning_quality.py
uv run python scripts/benchmark/contamination_report.py
```
