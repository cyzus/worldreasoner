# WorldReasoner

**WorldReasoner** is a temporal forecasting benchmark for large language models. It evaluates how well LLMs predict real-world outcomes when given structured, temporally-filtered evidence — measuring the contribution of causal reasoning, web search, and evidence quality across six experimental conditions.

## Overview

The system builds on two core ideas:

- **Temporal access control** — every model call is gated to evidence published before a configurable `simulated_date`, preventing future knowledge leakage.
- **Causal evidence graphs** — a backward pipeline extracts events, builds causal chains, and quality-scores the graph against the known outcome, providing richer signal than raw article retrieval.

Benchmarking is an ablation from pure knowledge recall (`vanilla_llm`) up to oracle access (`oracle`), evaluated on a curated 120-question dataset sourced from Polymarket.

## Installation

**Requirements:** Python 3.13+, [`uv`](https://docs.astral.sh/uv/), Node.js 18+

```bash
git clone https://github.com/cyzus/worldreasoner.git
cd worldreasoner

uv sync
uv run playwright install        # headless browser for article scraping

cp config/config.example.yaml config/config.yaml
# Add your LLM API keys to config/config.yaml
```

## Quick Start

```bash
# Collect questions from Polymarket
uv run wr question collect

# Run evidence pipeline for a question
uv run wr evidence run -q <question_id>

# Build causal graph
uv run wr graph build -q <question_id>

# Run a benchmark across conditions and models
uv run wr benchmark run \
  -c worldreasoner -c vanilla_llm \
  -m gemini/gemini-3-flash-preview \
  --question-ids include_ids.txt

# Score results (with contamination filtering, matching paper numbers)
uv run wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# Launch the research dashboard
uv run worldreasoner --reload &
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

See `wr --help` for the full command reference.

## Experimental Conditions

| Condition | CLI name | Search | Causal tools | Oracle |
|-----------|----------|:------:|:------------:|:------:|
| Vanilla LLM | `vanilla_llm` | | | |
| Structured Scenario | `structured_scenario` | | ✓ | |
| Search-Enabled Agent | `search_enabled` | ✓ | | |
| WorldReasoner Agent | `worldreasoner` | ✓ | ✓ | |
| Oracle Agent | `oracle` | ✓ | ✓ | ✓ |
| Real-Time Agent | `real_time` | live | ✓ | |

## Architecture

```
worldreasoner/
├── src/
│   ├── agents/          # Forecasting agents (MCP-based)
│   ├── api/             # FastAPI backend + MCP server
│   ├── cli/             # wr CLI (Typer)
│   ├── core/            # DB init, maintenance, search index
│   ├── domain/
│   │   ├── evaluation/  # Metrics, conditions, benchmark runner
│   │   └── models/      # Question, Forecast, Event, Article
│   ├── pipelines/       # Forward (collection) & backward (evidence) pipelines
│   └── services/        # Graph, search, market, annotation services
├── frontend/            # React + Vite research dashboard
├── scripts/             # Paper reproduction scripts
├── experiments/         # Saved benchmark runs and evaluation outputs
├── config/              # YAML config + LLM cutoff dates
├── include_ids.txt      # 120 canonical benchmark question IDs
└── docs/                # Extended documentation
```

## CLI Reference

```
wr db           database management (init, merge, clean, build-index, fetch-cutoffs)
wr question     question collection and selection
wr evidence     evidence pipeline (run, rerun, auto-review)
wr graph        causal graph building and audit
wr forecast     run individual forecasts
wr benchmark    benchmark runner and evaluator (run, evaluate, status, conditions)
```

Run `wr <group> --help` for options on any group.

## Research Dashboard

A React/Vite dashboard for exploring results interactively:

- **Questions** — browse questions, causal event timeline, evidence articles, forecast results
- **Data** — collection pipeline status, search index management
- **Benchmark** — condition × model accuracy matrix with contamination filter toggle

```bash
uv run worldreasoner --reload          # backend on port 8300
cd frontend && npm run dev             # frontend on port 5173
```

See [frontend/README.md](frontend/README.md) for environment configuration.

## Reproducing Paper Results

```bash
# 1. Merge source databases into the canonical combined DB
uv run wr db merge \
  --source paper=paper.db --source extra=extra.db \
  --output combined.db

# 2. Run the full benchmark (matches paper Table 2 setup)
uv run wr benchmark run \
  -c vanilla_llm -c structured_scenario -c search_enabled \
  -c worldreasoner -c oracle -c real_time \
  -m gemini/gemini-3-flash-preview -m gemini/gemini-3-pro-preview \
  -m deepseek/deepseek-v4-flash -m deepseek/deepseek-v4-pro \
  -m dashscope/qwen3.5-397b-a17b \
  --question-ids include_ids.txt --db combined.db

# 3. Score with contamination filtering
uv run wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# 4. Generate paper figures
uv run python scripts/analysis/plot_accuracy_comparison.py
uv run python scripts/analysis/compute_metrics_table.py
```

See [scripts/README.md](scripts/README.md) for the complete reproduction workflow.

## Documentation

| | |
|---|---|
| [docs/README.md](docs/README.md) | Full documentation index |
| [docs/01_introduction.md](docs/01_introduction.md) | Background and problem statement |
| [docs/02_data_collection.md](docs/02_data_collection.md) | Dataset composition and collection pipeline |
| [docs/03_evidence_pipeline.md](docs/03_evidence_pipeline.md) | Article collection, event graphs, quality scoring |
| [docs/04_forecasting.md](docs/04_forecasting.md) | MCP server, temporal gateway, context management |
| [docs/05_evaluation.md](docs/05_evaluation.md) | Metrics, conditions, contamination filtering, benchmark guide |
| [docs/metrics.md](docs/metrics.md) | Accuracy, Brier score, log score definitions |
| [scripts/README.md](scripts/README.md) | Paper figure and number reproduction |
| [frontend/README.md](frontend/README.md) | Dashboard setup and configuration |
| [AGENTS.md](AGENTS.md) | Multi-agent system design |

## Citation

```bibtex
@software{worldreasoner2025,
  title   = {WorldReasoner: Temporal Forecasting Benchmark for Large Language Models},
  author  = {Chi, Yizhou},
  year    = {2025},
  url     = {https://github.com/cyzus/worldreasoner}
}
```
