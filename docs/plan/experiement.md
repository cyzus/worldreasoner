## Question Dataset

A worldreasoner dataset

300 high quality questions

### Time horizon

100 short range questions (1 week)
100 medium range questions (1-3 month)
100 long range questions (more than 3 months)

### Question Domains

Finance
Politics
Sports
Entertainment
Climate
Health

### Sources
prediction market, news websites

### Collection Plan

The collection is automated using the goal-oriented orchestrator.

**Config**: `config/collection_goal_experiment.yaml`
**Script**: `scripts/run_experiment_collection.py`
**Database**: `experiment.db`

#### Type Distribution
| Type      | Target | Primary Source |
|-----------|--------|---------------|
| Binary    | 180    | Polymarket    |
| MCQ       | 60     | Polymarket + News |
| Quantity  | 30     | News pipeline |
| Timeframe | 30     | News pipeline |

#### Domain Distribution
| Domain    | Target | Notes |
|-----------|--------|-------|
| Finance   | 50     | Markets, earnings, economy |
| Politics  | 50     | Elections, policy, legislation |
| Sports    | 50     | Events, tournaments, matches |
| Culture   | 50     | Entertainment, arts, media |
| Climate   | 50     | Environment, weather, policy |
| Health    | 50     | Medical, healthcare, biotech |

#### Time Horizon Distribution
| Horizon | Target | Day Range | Examples |
|---------|--------|-----------|----------|
| Short   | 100    | 0-7 days  | Weekly sports, earnings reports |
| Medium  | 100    | 7-90 days | Quarterly events, elections |
| Long    | 100    | 90+ days  | Annual outcomes, long-term policy |

Time horizon is computed as: `resolution_date - estimated_start_time`.
For Polymarket, `estimated_start_time` is the market's `startDate`.

#### Running Collection

```bash
# View the collection plan
python scripts/run_experiment_collection.py --dry-run

# Run full collection (Polymarket + News)
python scripts/run_experiment_collection.py

# Polymarket only (faster, mostly binary/MCQ)
python scripts/run_experiment_collection.py --no-news

# Resume from previous run (deduplicates automatically)
python scripts/run_experiment_collection.py --db experiment.db --max-iterations 5

# Export dataset summary
python scripts/run_experiment_collection.py --export dataset_summary.json
```

#### Resumability

The orchestrator loads existing questions from the database on startup.
Running the script multiple times against the same `--db` file will:
1. Skip already-collected questions (deduplication by ID)
2. Focus on distribution gaps (types, domains, time horizons still needed)
3. Accumulate results across runs


## Evidence Collection

### Evidence Criteria

- at least 20 articles
- unique sources
- time coverage

### Event Graphs Criteria

- 10+ events
- time coverage
- 3+ depths

### Event Verification

`wr evidence review --db experiment.db --sample 30`


## Evaluation Setup

### LLM Models

6 models × 5 conditions × 300 questions = **9,000 runs**

| Model | LiteLLM ID | Role |
|-------|-----------|------|
| GPT-5 | `gpt-5` | Frontier (OpenAI) |
| Claude 4.5 Sonnet | `anthropic/claude-sonnet-4-5-20250514` | Frontier (Anthropic) |
| Gemini 2.5 Pro | `gemini/gemini-2.5-pro` | Frontier (Google) |
| Gemini 2.5 Flash | `gemini/gemini-2.5-flash` | Scaling baseline (cheap) |
| DeepSeek V3 | `deepseek/deepseek-chat` | Open-weight frontier |
| Qwen 3 | `qwen/qwen3` | Open-weight frontier |

### Experimental Conditions

The evaluation ablation study uses 5 conditions defined in `src/domain/evaluation/conditions.py`.
Each condition represents a unique combination of search mode, causal tools, and information access.

| # | Condition | CLI Name | Mode | Causal Tools | Oracle | Max Steps | Description |
|---|-----------|----------|------|:------------:|:------:|----------:|-------------|
| 1 | Vanilla LLM | `vanilla_llm` | `knowledge_only` | No | No | 10 | Baseline: LLM forecasts from training knowledge only |
| 2 | Structured Scenario | `structured_scenario` | `knowledge_only` | Yes | No | 25 | LLM + causal reasoning tools, no external search |
| 3 | Search-Enabled | `search_enabled` | `container` | No | No | 15 | LLM + article search via MCP, no causal structure |
| 4 | WorldReasoner | `worldreasoner` | `container` | Yes | No | 25 | Full system: search + causal reasoning tools |
| 5 | Oracle | `oracle` | `container` | Yes | Yes | 25 | Full system with near-resolution-date info (upper bound) |
| 6 | Real-Time | `real_time` | `real_time` | Yes | No | 25 | Full system using real-time live internet access |

List conditions at any time:
```bash
wr benchmark conditions
```

### Metrics

All metrics are computed per-condition and aggregated across questions.

| Metric | Range | Better | Description |
|--------|-------|--------|-------------|
| **Accuracy** | 0–1 | Higher | Binary/MCQ: exact match. Quantity: within 10% tolerance |
| **Brier Score** | 0–1 | Lower | Mean squared error between forecast probability and outcome |
| **Log Score** | -inf–0 | Higher | Logarithmic scoring rule; rewards calibrated confidence |
| **Calibration Error** | 0–1 | Lower | Mean absolute difference between confidence bins and actual accuracy |

Implementation: `src/domain/evaluation/metrics.py`

### Prerequisites

Before running the evaluation:

1. **Resolved questions in database** — Questions must have `resolution` and `resolution_date` set.
   The experiment dataset (`experiment.db`) should already have these from collection.

2. **Evidence collected and reviewed** — Run the evidence pipeline first, then review events:
   ```bash
   # Collect evidence (stratified sample or full)
   wr evidence run --db experiment.db --sample 50

   # Review events for accuracy
   wr evidence review --db experiment.db --sample 30
   ```

3. **Search index built** — Required for `container` mode conditions (3, 4, 5):
   ```bash
   python scripts/build_search_index.py --db experiment.db
   ```

4. **MCP forecasting server running** — Required for `container` mode conditions:
   ```bash
   # Start the MCP server (runs on port 8110 by default)
   python src/mcp_forecasting_server.py
   ```

5. **LLM knowledge cutoff dates** — Needed for temporal access control:
   ```bash
   python scripts/fetch_knowledge_cutoff_date.py
   ```

6. **Config** — Ensure `config/config.yaml` has a valid LLM provider configured.

### Running the Evaluation

#### Full Benchmark (All Conditions)

```bash
# Run all 5 conditions with default model on all resolved questions
wr benchmark run --db experiment.db -y

# Dry run — shows plan without executing
wr benchmark run --db experiment.db
# (will prompt for confirmation)
```

#### Single Condition

```bash
# Vanilla LLM baseline only
wr benchmark run --db experiment.db -c vanilla_llm -y

# WorldReasoner only
wr benchmark run --db experiment.db -c worldreasoner -y
```

#### Multiple Models

```bash
# Compare two models across all conditions
wr benchmark run --db experiment.db -m gemini/gemini-2.5-flash -m gpt-5 -y

# Single condition, multiple models
wr benchmark run --db experiment.db -c vanilla_llm -m gemini/gemini-2.5-flash -m gpt-5 -y
```

#### Limiting Questions

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

#### Resuming Interrupted Runs

```bash
# Resume from where it left off (skips completed triples)
wr benchmark run --db experiment.db --resume -y
```

#### Offset Days

By default the simulated date is based on the question's `estimated_start_time`.
Use `--offset-days` to shift the simulated date earlier from the resolution date:

```bash
# Simulate forecasting 7 days before resolution
wr benchmark run --db experiment.db --offset-days 7 -y
```

### Output

Results are saved as JSON files in `benchmarks/`:

```
benchmarks/autobench_<timestamp>.json
```

Each file contains:
- `run_id`: Unique identifier
- `conditions`: Per-condition aggregated results (accuracy, Brier, log score)
- `individual_results`: Per-question predictions, confidence, and scores
- `leaderboard`: Ranked comparison of condition × model combinations

A summary report is printed to the console after each run.

### Recommended Evaluation Order

Run conditions in order of cost (cheapest first) so you can validate the setup early:

1. **`vanilla_llm`** — No MCP server needed, fastest (10 steps max), cheapest
2. **`structured_scenario`** — No MCP server needed, uses causal tools from memory
3. **`search_enabled`** — Requires MCP server + search index
4. **`worldreasoner`** — Requires MCP server + search index + event graph
5. **`oracle`** — Most expensive, uses near-resolution information
6. **`real_time`** — Uses live search engines, ignores clock simulation overrides

```bash
# Step-by-step evaluation
wr benchmark run --db experiment.db -c vanilla_llm -n 10 -y          # Quick sanity check
wr benchmark run --db experiment.db -c vanilla_llm -y                 # Full baseline
wr benchmark run --db experiment.db -c structured_scenario -y
wr benchmark run --db experiment.db -c search_enabled -y
wr benchmark run --db experiment.db -c worldreasoner -y
wr benchmark run --db experiment.db -c oracle -y
wr benchmark run --db experiment.db -c real_time -y
```

### Individual Forecasting (Development / Debugging)

For testing a single question before running the full benchmark:

```bash
# Single question forecast
wr forecast run --db experiment.db -q <question_id>

# Batch of questions
wr forecast batch --db experiment.db -q q1 -q q2 -q q3
```

### Visualizing Results

```bash
# Multi-metric side-by-side (accuracy, Brier, log score)
python examples/visualize_benchmarks.py

# Save to file instead of showing
python examples/visualize_benchmarks.py --output benchmarks/figures/results.png

# Single metric
python examples/visualize_benchmarks.py --metric accuracy
python examples/visualize_benchmarks.py --metric brier

# Text summary table (no GUI)
python examples/visualize_benchmarks.py --table
```

This loads both `autobench_*.json` (from `wr benchmark run`) and legacy `benchmark_*.json` files.
