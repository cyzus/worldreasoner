# WorldReasoner CLI Reference

## Overview

```bash
# Main entry point
wr [OPTIONS] COMMAND [ARGS]...

# Options
--verbose, -v    Enable verbose output
--help           Show help
```

## Commands

### 1. Database Management (`wr db`)

```bash
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

# Run goal-oriented collection
wr question goal
wr question goal --goal config/my_goal.yaml
wr question goal --no-news
wr question goal --sequential
```

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

### 5. Benchmark (`wr benchmark`)

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
- `worldreasoner.db` — Main database
- `experiment.db` — Experiment dataset

## Examples

### Full Evidence & Graph Workflow

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

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No questions found | Run collection: `wr question goal` |
| Missing events | Check question has evidence: `wr question show <id>` |
| Review errors | Reset events: `wr evidence reset` |
| Import errors | Reinstall: `uv pip install -e .` |
