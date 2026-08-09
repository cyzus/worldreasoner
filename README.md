![WorldReasoner](docs/images/banner.png)

# WorldReasoner

**WorldReasoner** is an evaluation framework for temporally valid event forecasting. Each task gives an agent a resolved forecasting question, a simulated forecast date, and access only to evidence available before that date. After resolution, the framework scores the submitted probability, cited evidence, and optional causal event graph across three complementary axes: **outcome quality** against resolved answers, **evidence quality** over cited sources, and **reasoning quality** against post-resolution hindsight graphs.

## Overview

To forecast real-world events, LLM agents must reason from partial evidence under strict temporal constraints. A fundamental obstacle is **temporal data leakage**: an agent backed by a model trained through 2025 that answers a question about a 2022 election is not forecasting — it is recalling history. WorldReasoner addresses this by restricting all tool access to evidence available at the simulated forecast date, scoring the submission immediately while preserving the temporal boundary.

A scalable agentic construction pipeline generates forecasting questions from prediction markets and news streams, collects time-stamped evidence, and builds post-resolution hindsight reference graphs automatically — yielding **345 resolved tasks** derived from **14,141 articles** with graphs covering **8,087 extracted events** (paper snapshot; the public DB includes additional evidence collected since publication).

<p align="center">
  <img src="docs/images/forecasting_sandbox.png" width="100%" alt="An example forecasting task: Forecast Card, Temporal View (only evidence before the simulated date is visible), Agent Submission, and Post-Resolution Scoring across outcome, evidence, and reasoning." />
  <br/><em>An example forecasting task. The agent sees only evidence available before the simulated date (Temporal View), submits a probability with cited evidence and an optional forecast graph, and is scored after resolution on outcome, evidence, and reasoning quality.</em>
</p>

Key findings across six controlled agent settings:
- Temporally valid retrieval is the **strongest driver of outcome accuracy**
- Causal graph construction **improves key-event recovery**
- Correct graph-enabled forecasts are more strongly grounded in key events and relevant sources — yet agents still struggle to convert grounded evidence into calibrated probabilities

## Dataset

The benchmark database is available as a GitHub release asset (~60MB, article full-text and LLM reasoning traces stripped):

```bash
# Download
gh release download v1.0.0 --pattern "worldreasoner_public.db"
```

The public DB ships **without article full-text** (copyright), so it reproduces the stored
outcome scores (accuracy, Brier, log score) and the hindsight event graph, but the search
index cannot be rebuilt from it. To reproduce the **search/oracle conditions** (which need
live retrieval over article text), build the full local DB from `combined.db`:

```bash
# Full DB with article content + forecast reasoning (local-only; not the public release)
uv run python scripts/benchmark/export_public_db.py \
  --src combined.db --dst worldreasoner_full.db --with-content
uv run wr db build-index --db worldreasoner_full.db
```

| | |
|---|---|
| Resolved questions | 345 (120 curated in `include_ids.txt`) |
| Question types | Binary (69%), MCQ (13.3%), Quantity (11.6%), Timeframe (6.1%) |
| Domains | 10 (politics, culture, health, sports, finance, …) |
| Sources | Polymarket (97) + news pipeline (248) |
| Articles (DB) | 14,364 (metadata only; full text stripped) |
| Events (DB) | 9,149 causal events with evidence graphs |
| Causal edges (DB) | 9,858 hypothesis edges |
| Forecasts (DB) | 11,566 records with accuracy, Brier score, log score |

To regenerate from source: `uv run python scripts/benchmark/export_public_db.py --src combined.db --dst worldreasoner_public.db`

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

Six controlled agent settings form an ablation from pure knowledge recall to near-resolution access:

| Paper name | CLI name | Search | Causal graph | Notes |
|------------|----------|:------:|:------------:|-------|
| Vanilla LLM | `vanilla_llm` | | | Training knowledge only |
| Causal Simulation | `structured_scenario` | | ✓ | Knowledge + causal tools |
| Search-Enabled | `search_enabled` | ✓ | | Temporally valid retrieval |
| Search-Enabled Graph | `worldreasoner` | ✓ | ✓ | Full system |
| Near-Resolution | `oracle` | ✓ | ✓ | Upper bound |
| Real-Time | `real_time` | live | ✓ | Live internet access |

## Architecture

<p align="center">
  <img src="docs/images/pipeline.png" width="100%" alt="Forward (question generation) and backward (evidence & hindsight) pipelines" />
</p>

The benchmark is built by two agentic pipelines. The **forward pipeline** generates forecasting questions from prediction markets and news streams. The **backward pipeline** runs after resolution: the Hindsight Agent collects post-resolution evidence, the Event Analyzer synthesizes it into a causal narrative, and GraphBuilder converts this into a structural event DAG used as the reference for reasoning quality scoring.

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
├── data/                # Local versioned datasets, manifests, and selections
├── research/            # Planning and private paper-development artifacts
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
wr dataset      versioned dataset creation and evidence-quality passes
```

Run `wr <group> --help` for options on any group.

## Research Dashboard

A React/Vite dashboard for exploring benchmark results interactively:

- **Questions** — causal explanation, evidence timeline, pressure chart, forecast results
- **Data** — question collection, evidence pipeline, search index management
- **Benchmark** — condition × model accuracy matrix with contamination filter toggle

### Example: Will Netflix close Warner Bros. acquisition by end of 2026?

<p align="center"><img src="docs/images/evidence-1.png" width="100%" /><br/><em>Evidence tab — causal explanation with executive summary and key event timeline</em></p>

<p align="center"><img src="docs/images/evidence-2.png" width="100%" /><br/><em>Evidence tab — causal events list with impact direction and evidence accumulation chart</em></p>

<p align="center"><img src="docs/images/hindsight_graph.png" width="100%" /><br/><em>Graph tab — SVG evidence timeline with event detail popup and causal links</em></p>

<p align="center"><img src="docs/images/market_fetch.png" width="100%" /><br/><em>Data tab — question collection from Polymarket with ground truth preview</em></p>

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

# 4. Generate paper figures and metrics table
uv run python scripts/analysis/plot_reasoning_quality.py
uv run python scripts/analysis/plot_sliding_window.py
uv run python scripts/benchmark/plot_vanilla_time_performance.py
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
@misc{worldreasoner2026,
  title         = {WorldReasoner: Evaluating Whether Language Model Agents Forecast Events with Valid Reasoning},
  author        = {Chi, Yizhou and Chamoun, Eric and Ding, Zifeng and Vlachos, Andreas},
  year          = {2026},
  eprint        = {2606.11816},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/2606.11816}
}
```
