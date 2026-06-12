# Appendix A: WorldReasoner CLI Reference

## Overview

```bash
# Main entry point
wr [OPTIONS] COMMAND [ARGS]...

# Options
--verbose, -v    Enable verbose output
--help           Show help
```

---

## Commands

### 1. Database Management (`wr db`)

```bash
# Create / initialize a database (creates the file if absent, builds all tables)
wr db init --db mydataset.db

# Show database statistics
wr db stats
wr db stats --db experiment.db

# List items (questions, events, articles)
wr db list questions
wr db list questions --domain politics --limit 20
wr db list events --db experiment.db
wr db list articles

# Show item details
wr db show question <question_id>
wr db show question <question_id> --json
wr db show event <event_id>

# Analyze cascade impact of deleting an item
wr db analyze question <question_id>
wr db analyze question <question_id> --json

# Delete an item (with cascade)
wr db delete question <question_id>
wr db delete question <question_id> --dry-run
wr db delete event <event_id> --no-cascade

# Clear evidence for a question (keeps the question)
wr db clear-evidence <question_id>
wr db clear-evidence <question_id> --dry-run

# Update a field on a question
wr db update question <question_id> --field ground_truth --value "Yes"

# Build or rebuild search indexes
wr db build-index
wr db build-index --rebuild
wr db build-index --model text-embedding-3-large
wr db build-index --db experiment.db
```

---

### 2. Question Management (`wr question`)

```bash
# List questions with filtering
wr question list
wr question list --domain politics --limit 20
wr question list --db experiment.db

# Show question details
wr question show <question_id>
wr question show <question_id> --json

# Show question statistics
wr question status
wr question status --db experiment.db

# Search questions by text
wr question search "election"
wr question search "bitcoin" --domain finance
wr question search "climate" --limit 10

# Add a manually-authored question
wr question add --text "Will X happen by 2026?" --resolution-date 2026-12-31 --domain politics
wr question add --text "..." --resolution-date 2026-06-30 --type mcq --options "A,B,C"

# Run goal-oriented collection
wr question goal
wr question goal --goal config/my_goal.yaml
wr question goal --no-news
wr question goal --sequential

# Collect a distribution-balanced experiment dataset
wr question collect
wr question collect --dry-run
wr question collect --no-news --export dataset_summary.json
wr question collect --db experiment.db --max-iterations 5

# Add specific Polymarket questions by slug, URL, or numeric id
wr question add-polymarket will-trump-win-2024 --db combined.db
wr question add-polymarket https://polymarket.com/event/some-event
wr question add-polymarket slug-a slug-b 12345 --dry-run

# Select high-quality, domain-balanced questions for an annotation study
wr question select --db combined.db --polymarket-n 100

# Backfill ground truth for Polymarket questions that have since resolved
wr question refresh-polymarket --db combined.db
wr question refresh-polymarket -n 50
```

> `add-polymarket` fetches exactly the markets you name (no quality filtering or
> target counts) and saves them to `--db`, skipping any that already exist. Use
> `--dry-run` to resolve and preview without saving.
>
> `refresh-polymarket` re-fetches stored Polymarket questions that have no ground
> truth yet and copies the outcome over for any whose market has since resolved.
> The API server also runs this automatically on startup (disable with
> `POLYMARKET_REFRESH_ON_STARTUP=false`).

---

### 3. Evidence Pipeline (`wr evidence`)

#### Run Evidence Collection

```bash
# Process specific questions
wr evidence run -q q_abc123 -q q_def456

# Process with adaptive pipeline (deeper analysis)
wr evidence run -q q_abc123 --adaptive

# Process all questions from polymarket
wr evidence run --source polymarket

# Process resolved questions only
wr evidence run --resolved

# Process random sample
wr evidence run --sample 10

# Interactive selection
wr evidence run -i
```

#### Review Events

```bash
# Interactive manual review
wr evidence review --db experiment.db
wr evidence review -q q_abc123 --db experiment.db
wr evidence review --status all --summary

# Auto-review with LLM (recommended)
wr evidence auto-review --db experiment.db
wr evidence auto-review --db experiment.db --sample 5
wr evidence auto-review -y
wr evidence auto-review --skip-criteria
wr evidence auto-review -m gpt-5

# Custom criteria
wr evidence auto-review --min-events 15 --min-depth 4

# List rejected events
wr evidence list-rejected --db experiment.db
wr evidence list-rejected -n 20
wr evidence list-rejected -v
wr evidence list-rejected -e evt_123abc
```

#### Clear Evidence

```bash
# Clear evidence for specific questions
wr evidence clear -q q_abc123
wr evidence clear -q q_1 -q q_2 --cascade
wr evidence clear -q q_abc123 --dry-run

# Clear evidence for ALL questions
wr evidence clear --all --db experiment.db
```

#### Reset Review Status

```bash
# Reset all events to pending
wr evidence reset --db experiment.db

# Reset only rejected events
wr evidence reset --status rejected

# Reset for specific question
wr evidence reset -q q_abc123
```

---

### 4. Graph Builder (`wr graph`)

```bash
# Build graphs for pending questions (batch process)
wr graph build
wr graph build --limit 5

# Build a graph for a specific question
wr graph build -q <question_id>

# Run audit pipeline on a completed graph
wr graph audit -q <question_id>
```

---

### 5. Forecasting (`wr forecast`)

```bash
# Run single forecast
wr forecast run -q <question_id>
wr forecast run --interactive
wr forecast run -q q_abc123 --model gemini-2.5-flash --mode knowledge_only

# Batch forecasting
wr forecast batch -q q_1 -q q_2 -q q_3
wr forecast batch --source polymarket --domain politics --limit 10
```

---

### 6. Benchmark (`wr benchmark`)

```bash
# Run full benchmark (all 6 conditions)
wr benchmark run --db experiment.db -y

# Run specific condition
wr benchmark run -c worldreasoner -y

# List available conditions
wr benchmark conditions

# Run with specific model
wr benchmark run -m gemini/gemini-2.5-flash -y

# Multiple models
wr benchmark run -m gemini/gemini-2.5-flash -m gpt-5 -y

# Limit questions
wr benchmark run -n 5 -y
wr benchmark run --domain finance -y
wr benchmark run --source polymarket -y

# Resume interrupted run
wr benchmark run --resume -y

# Offset days (simulate earlier date)
wr benchmark run --offset-days 7 -y
```

---

## Shared Options

Most commands accept these common options:

| Option | Description | Default |
|--------|-------------|---------|
| `--db <path>` | Database path | `worldreasoner.db` |
| `--source/-s` | Filter by question source | None |
| `--domain/-d` | Filter by domain | None |
| `--limit/-n` | Maximum results | 50 |
| `--sample` | Random sample size | None |
| `--seed` | Random seed for sampling | None |
| `--yes/-y` | Skip confirmation prompt | False |
| `--json` | Output as JSON | False |

Common databases:
- `worldreasoner.db` — Main development database
- `experiment.db` — Benchmark experiment dataset

---

## Examples

### Full Evidence and Graph Workflow

```bash
# 1. Collect evidence for questions (creates NL explanation)
wr evidence run --db experiment.db --sample 20

# 2. Build the structured graphs
wr graph build --db experiment.db --limit 20

# 3. Auto-review collected events
wr evidence auto-review --db experiment.db -y

# 4. Check rejected events
wr evidence list-rejected --db experiment.db -v
```

### Running Benchmarks

```bash
# 1. Run baseline (vanilla LLM)
wr benchmark run -c vanilla_llm -n 10 -y

# 2. Run full system
wr benchmark run -c worldreasoner -y

# 3. Compare results
python examples/visualize_benchmarks.py
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No questions found | Run collection: `wr question goal` |
| Missing events | Check question has evidence: `wr question show <id>` |
| Review errors | Reset events: `wr evidence reset` |
| Import errors | Reinstall: `uv pip install -e .` |
| `failed to remove file ... Scripts\worldreasoner.exe ... (os error 32)` on Windows | The API server is running and locks the binary, so `uv run`'s pre-run sync can't reinstall. Run without syncing: `uv run --no-sync wr <command>`. Or stop the server first (`wr` and `worldreasoner` are separate entry points; the server is `worldreasoner.exe` plus its `mcp_forecasting_server` children). |
