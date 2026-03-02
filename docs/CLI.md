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

### 1. Database Management

```bash
# Show database info
wr db info

# List tables
wr db tables

# Run migrations
wr db migrate
```

### 2. Question Collection

```bash
# List questions
wr question list

# Show question details
wr question show <question_id>

# Search questions
wr question search --domain politics --source polymarket

# View question status
wr question status
```

### 3. Evidence Pipeline

The evidence pipeline collects articles and events for questions.

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
wr evidence auto-review --db experiment.db           # Review all pending
wr evidence auto-review --db experiment.db --sample 5  # Sample 5 questions
wr evidence auto-review -y                           # Skip confirmation
wr evidence auto-review --skip-criteria             # Skip criteria filter
wr evidence auto-review -m gpt-5                    # Use custom model

# Custom criteria
wr evidence auto-review --min-events 15 --min-depth 4

# List rejected events
wr evidence list-rejected --db experiment.db
wr evidence list-rejected -n 20                     # Limit 20
wr evidence list-rejected -v                        # Verbose (full reasons)
wr evidence list-rejected -e evt_123abc             # Specific event details
```

#### Clear Evidence

```bash
# Clear evidence for specific questions
wr evidence clear -q q_abc123

# Clear all evidence
wr evidence clear --all
```

### 4. Forecasting

```bash
# Run single forecast
wr forecast run --db experiment.db -q <question_id>

# Batch forecasting
wr forecast batch -q q1 -q q2 -q q3

# Check forecast status
wr forecast status
```

### 5. Benchmark

```bash
# Run full benchmark
wr benchmark run --db experiment.db -y

# Run specific condition
wr benchmark run -c worldreasoner -y

# List available conditions
wr benchmark conditions

# Run with specific model
wr benchmark run -m gemini/gemini-2.5-flash -y

# Limit questions
wr benchmark run -n 5 -y  # 5 questions
wr benchmark run --domain finance -y
wr benchmark run --source polymarket -y

# Offset days (simulate earlier date)
wr benchmark run --offset-days 7 -y
```

## Database Options

Most commands accept a `--db` option:

```bash
--db <path>    Database path (default: worldreasoner.db)
```

Common databases:
- `worldreasoner.db` - Main database
- `experiment.db` - Experiment dataset

## Examples

### Full Evidence Workflow

```bash
# 1. Collect evidence for questions
wr evidence run --db experiment.db --sample 20

# 2. Auto-review collected events
wr evidence auto-review --db experiment.db -y

# 3. Check rejected events
wr evidence list-rejected --db experiment.db -v

# 4. Manual review of specific events (if needed)
wr evidence review -q q_abc123
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
| No questions found | Run collection: `wr evidence run` |
| Missing events | Check question has evidence: `wr question show <id>` |
| Review errors | Reset events: update `review_status` to `pending` |
| Import errors | Reinstall: `uv pip install -e .` |
