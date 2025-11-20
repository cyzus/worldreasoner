# Benchmarking Guide

This guide explains how to run comprehensive benchmark evaluations on WorldReasoner to test LLM forecasting performance.

## Overview

WorldReasoner provides comprehensive benchmarking and evaluation tools:

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `evaluate_forecasts.py` | Evaluate existing forecasts | After manual forecasting sessions |
| **`run_benchmark_evaluation.py`** | Run forecasts on all questions + evaluate | **Automated benchmarking of LLM models** |
| **`visualize_benchmarks.py`** | Generate comparative charts from results | **After running benchmarks** |

## Quick Start

Complete workflow for benchmarking and comparing models:

```bash
# 1. Run benchmarks for different models
python examples/run_benchmark_evaluation.py --model gpt-4
python examples/run_benchmark_evaluation.py --model claude-sonnet-4
python examples/run_benchmark_evaluation.py --model gemini/gemini-2.0-flash-exp

# 2. Test knowledge-only mode (no research)
python examples/run_benchmark_evaluation.py --model gpt-4 --knowledge-only

# 3. Visualize all results
python examples/visualize_benchmarks.py

# Results are saved to:
# - benchmarks/benchmark_*.json (raw data)
# - benchmarks/figures/*.png (visualizations)
```

## Benchmark Evaluation Script

`run_benchmark_evaluation.py` is the comprehensive benchmarking tool that:

1. Finds all resolved questions in the database
2. Runs the forecast agent on each question (with temporal constraints)
3. Evaluates each forecast immediately
4. Generates a comprehensive report with model comparison

### Prerequisites

1. **Database with resolved questions**:
   - Questions must have `ground_truth` set (not None)
   - Questions need sufficient context (articles/events)

2. **MCP server running**:
   ```bash
   python -m src.mcp_forecasting_server
   ```

3. **Configuration set up**:
   - `config/config.yaml` with LLM API keys
   - Model configured (or override with `--model`)

### Basic Usage

```bash
# Run benchmark on all resolved questions
# Results automatically saved to: benchmarks/benchmark_<timestamp>_<model>.json
python examples/run_benchmark_evaluation.py

# Use specific model
python examples/run_benchmark_evaluation.py --model gpt-4

# Use different model configurations
python examples/run_benchmark_evaluation.py --model claude-sonnet-4
python examples/run_benchmark_evaluation.py --model gemini/gemini-2.0-flash-exp

# Override default output path
python examples/run_benchmark_evaluation.py --output my_custom_results.json

# Don't save JSON (only print to console)
python examples/run_benchmark_evaluation.py --no-save
```

**Automatic JSON Saving:**
- By default, results are automatically saved to `benchmarks/benchmark_<timestamp>_<model>.json`
- Example: `benchmarks/benchmark_20251120_193045_gpt-4.json`
- The `benchmarks/` directory is created automatically if it doesn't exist
- Use `--output` to override the default path
- Use `--no-save` to disable saving (only print to console)

### Advanced Options

#### Temporal Configuration

Control when the "simulated forecast" is made relative to the resolution date:

```bash
# Forecast at resolution date (hardest - no advance info)
python examples/run_benchmark_evaluation.py --offset-days 0

# Forecast 7 days before resolution (easier - more recent info)
python examples/run_benchmark_evaluation.py --offset-days 7

# Set knowledge cutoff date (LLM training data ends)
python examples/run_benchmark_evaluation.py --knowledge-cutoff 2024-05-01
```

#### Context Requirements

```bash
# Require more context before forecasting
python examples/run_benchmark_evaluation.py --min-context-items 5

# More lenient context requirements
python examples/run_benchmark_evaluation.py --min-context-items 2
```

#### Agent Configuration

```bash
# Allow more reasoning steps
python examples/run_benchmark_evaluation.py --max-steps 20

# Faster evaluation with fewer steps
python examples/run_benchmark_evaluation.py --max-steps 10

# Knowledge-only mode (disable research tools)
# Tests LLM's inherent knowledge without external information access
python examples/run_benchmark_evaluation.py --knowledge-only
```

**Knowledge-Only Mode:**

The `--knowledge-only` flag is crucial for understanding what the LLM actually knows vs. what it can learn through research:

```bash
# Full mode (default): LLM can search articles and fetch information
python examples/run_benchmark_evaluation.py --model gpt-4

# Knowledge-only mode: LLM can only use get_question and submit_forecast
# Tests pure inherent knowledge from training data
python examples/run_benchmark_evaluation.py --model gpt-4 --knowledge-only
```

**Available tools by mode:**

| Mode | Tools Available | Use Case |
|------|----------------|----------|
| **Full** (default) | `get_question`, `temporal_search_articles`, `fetch_article`, `submit_forecast` | Test LLM's research + reasoning ability |
| **Knowledge-Only** | `get_question`, `submit_forecast` only | Test LLM's inherent knowledge without external info |

This is particularly useful for:
- **Comparing inherent knowledge vs. research ability**: Run same questions in both modes
- **Testing knowledge cutoff effectiveness**: Verify the LLM truly doesn't know future events
- **Baseline measurements**: Establish accuracy floor without any external help
- **Cost analysis**: Knowledge-only runs are faster and cheaper (fewer API calls)

#### Execution Control

```bash
# Test on limited number of questions
python examples/run_benchmark_evaluation.py --max-questions 5

# Skip questions that already have forecasts
python examples/run_benchmark_evaluation.py --skip-existing

# Verbose output (show each forecast)
python examples/run_benchmark_evaluation.py --verbose
```

### Example Output

```
================================================================================
BENCHMARK EVALUATION RESULTS
================================================================================

Model Configuration:
------------------------------------------------------------
  Model: gpt-4
  Max Steps: 15
  Knowledge Cutoff: 2024-05-01
  Forecast Offset: 0 days before resolution
  Min Context Items: 3

Execution Info:
------------------------------------------------------------
  Duration: 342.5 seconds
  Throughput: 1.23 questions/minute
  Timestamp: 2025-11-20T19:30:00+00:00

Results:
------------------------------------------------------------
  Total Questions: 7
  Successful: 7
  Failed: 0

  Overall Accuracy: 71.43%
  Average Brier Score: 0.2341 (lower is better)
  Average Log Score: -0.5832 (higher is better)

================================================================================

Benchmark complete!
Successfully evaluated 7/7 questions
```

## Comparing Knowledge vs. Research Ability

One of the most valuable comparisons is testing the same model with and without research tools:

```bash
# Test GPT-4 with full research capability
python examples/run_benchmark_evaluation.py --model gpt-4

# Test GPT-4 with only inherent knowledge (no research)
python examples/run_benchmark_evaluation.py --model gpt-4 --knowledge-only
```

**Expected results:**
- **Full mode**: Higher accuracy (can research and verify facts)
- **Knowledge-only mode**: Lower accuracy (only pre-trained knowledge)
- **Difference**: Shows how much research helps vs. pure knowledge

This reveals:
1. **Knowledge gaps**: What the LLM doesn't know from training
2. **Research effectiveness**: How much accuracy improves with information access
3. **Knowledge cutoff validity**: Whether the LLM truly doesn't know future events

**Example comparison:**

```python
import json
from pathlib import Path

# Load results
with open('benchmarks/benchmark_20251120_193045_gpt-4.json') as f:
    full_mode = json.load(f)

with open('benchmarks/benchmark_20251120_194530_gpt-4.json') as f:
    knowledge_only = json.load(f)

# Compare
print(f"GPT-4 Full Mode:         {full_mode['results']['overall_accuracy']:.2%}")
print(f"GPT-4 Knowledge-Only:    {knowledge_only['results']['overall_accuracy']:.2%}")
print(f"Research Improvement:    {(full_mode['results']['overall_accuracy'] - knowledge_only['results']['overall_accuracy']):.2%}")
```

## Visualizing Benchmark Results

After running benchmarks, use the visualization script to generate comparative charts:

```bash
# Generate all visualizations
python examples/visualize_benchmarks.py

# Save to custom directory
python examples/visualize_benchmarks.py --output-dir my_figures/

# Generate specific plots only
python examples/visualize_benchmarks.py --plots accuracy brier mode_comparison

# Show interactive plots instead of saving
python examples/visualize_benchmarks.py --show
```

**Prerequisites:**
```bash
# Install visualization dependencies
uv sync --group viz

# Or using pip
pip install matplotlib pandas
```

**Generated Visualizations:**

1. **Accuracy Comparison** (`accuracy_comparison.png`)
   - Bar chart comparing accuracy across all models
   - Color-coded by mode (Full vs Knowledge-Only)
   - Shows most recent run for each model

2. **Brier Score Comparison** (`brier_score_comparison.png`)
   - Compares calibration quality across models
   - Lower is better (0 = perfect)

3. **Log Score Comparison** (`log_score_comparison.png`)
   - Compares probabilistic scoring
   - Higher is better (closer to 0)

4. **Mode Comparison** (`mode_comparison.png`)
   - Side-by-side comparison of Full vs Knowledge-Only
   - Shows research impact for each model
   - Annotates performance differences

5. **Performance Timeline** (`performance_timeline.png`)
   - Tracks accuracy and Brier score over time
   - Useful for monitoring improvements

**Example Output:**

The visualization script automatically:
- Loads all JSON files from `benchmarks/`
- Extracts key metrics (accuracy, Brier score, log score)
- Generates publication-quality figures
- Prints summary statistics to console

```
BENCHMARK SUMMARY STATISTICS
================================================================================

Total benchmark runs: 12
Unique models: 4
Date range: 2025-11-15 to 2025-11-20

Overall Statistics:
  Mean Accuracy: 68.42%
  Std Accuracy:  12.31%
  Mean Brier:    0.2341
  Std Brier:     0.0823

By Mode:
  Full:
    Runs: 8
    Mean Accuracy: 72.15%
    Mean Brier: 0.2123
  Knowledge-Only:
    Runs: 4
    Mean Accuracy: 60.95%
    Mean Brier: 0.2777

Top 3 Best Performing (by accuracy):
  1. gpt-4 (Full): 75.43%
  2. claude-sonnet-4 (Full): 71.82%
  3. gemini-2.0-flash-exp (Full): 69.21%
```

## Model Comparison Benchmarks

To compare different models, run separate benchmarks (results automatically saved with model name):

```bash
# GPT-4 (auto-saves to benchmarks/benchmark_<timestamp>_gpt-4.json)
python examples/run_benchmark_evaluation.py --model gpt-4

# Claude Sonnet 4 (auto-saves to benchmarks/benchmark_<timestamp>_claude-sonnet-4.json)
python examples/run_benchmark_evaluation.py --model claude-sonnet-4

# Gemini Flash (auto-saves to benchmarks/benchmark_<timestamp>_gemini_gemini-2.0-flash-exp.json)
python examples/run_benchmark_evaluation.py --model gemini/gemini-2.0-flash-exp
```

Then visualize results:

```bash
# Automatically generates comparative figures for all models
python examples/visualize_benchmarks.py
```

Or compare programmatically:

```python
import json
from pathlib import Path

# Find latest results for each model
benchmarks_dir = Path('benchmarks')

# Load latest GPT-4 results
gpt4_files = sorted(benchmarks_dir.glob('benchmark_*_gpt-4.json'))
with open(gpt4_files[-1]) as f:
    gpt4 = json.load(f)

# Load latest Claude results
claude_files = sorted(benchmarks_dir.glob('benchmark_*_claude-sonnet-4.json'))
with open(claude_files[-1]) as f:
    claude = json.load(f)

# Compare
print(f"GPT-4 Accuracy: {gpt4['results']['overall_accuracy']:.2%}")
print(f"Claude Accuracy: {claude['results']['overall_accuracy']:.2%}")
print(f"GPT-4 Brier Score: {gpt4['results']['avg_brier_score']:.4f}")
print(f"Claude Brier Score: {claude['results']['avg_brier_score']:.4f}")
```

## Evaluating Existing Forecasts

If you already have forecasts in the database and just want to evaluate them:

```bash
# Evaluate all existing forecasts
python examples/evaluate_forecasts.py

# Evaluate specific forecast
python examples/evaluate_forecasts.py --forecast-id fcst_123

# Save report
python examples/evaluate_forecasts.py --output evaluation_report.json
```

### Example Output with Model Info

```
================================================================================
EVALUATION SUMMARY
================================================================================

Total Forecasts Evaluated: 42
Overall Accuracy: 64.29%
Average Brier Score: 0.2341 (lower is better)
Average Log Score: -0.5832 (higher is better)

Breakdown by Question Type:
------------------------------------------------------------

BOOLEAN:
  Count: 35
  Accuracy: 65.71%
  Avg Brier Score: 0.2189
  Avg Log Score: -0.5421

MCQ:
  Count: 7
  Accuracy: 57.14%
  Avg Brier Score: 0.3012
  Avg Log Score: -0.7234

Model Performance:
------------------------------------------------------------
Total Unique Models: 2

gpt-4:
  Forecasts: 30
  Accuracy: 66.67%

claude-sonnet-4:
  Forecasts: 12
  Accuracy: 58.33%

Calibration Analysis (Boolean Questions):
------------------------------------------------------------
Mean Calibration Error: 0.0823

Confidence Bins:
Range           Count      Accuracy     Cal Error
------------------------------------------------------------
0.5-0.6         8          50.00%       0.0500
0.6-0.7         12         66.67%       0.0167
0.7-0.8         10         80.00%       0.0500
0.8-0.9         5          60.00%       0.2500

================================================================================
```

## Metrics Explained

### Accuracy
- **Range**: 0.0 to 1.0 (0% to 100%)
- **Meaning**: Percentage of correct predictions
- **Higher is better**

### Brier Score
- **Range**: 0.0 to 1.0
- **Meaning**: Mean squared error between predicted probabilities and outcomes
- **Formula**: `(forecast_probability - outcome)²`
- **Lower is better** (0 = perfect)
- Standard metric in forecasting competitions

### Log Score
- **Range**: -∞ to 0
- **Meaning**: Logarithmic scoring rule
- **Formula**: `log(probability_of_actual_outcome)`
- **Higher is better** (closer to 0)
- Heavily penalizes overconfident wrong predictions

### Calibration
- **Meaning**: Whether confidence levels match actual accuracy
- **Well-calibrated**: 70% confidence → 70% accurate
- **Overconfident**: 70% confidence → 50% accurate
- **Underconfident**: 70% confidence → 90% accurate

## Best Practices

### 1. Run Benchmarks Regularly

```bash
# Weekly benchmark (auto-saves to benchmarks/ with timestamp)
python examples/run_benchmark_evaluation.py

# All results are automatically timestamped, so you can track progress over time
# Example: benchmarks/benchmark_20251120_193045_gpt-4.json
```

### 2. Test Different Forecast Horizons

```bash
# Same-day forecasting (hardest)
# Auto-saves to: benchmarks/benchmark_<timestamp>_<model>.json
python examples/run_benchmark_evaluation.py --offset-days 0

# 1 week ahead
python examples/run_benchmark_evaluation.py --offset-days 7

# 1 month ahead
python examples/run_benchmark_evaluation.py --offset-days 30

# Results are automatically saved with timestamps for easy comparison
```

### 3. A/B Test Model Configurations

```bash
# Default settings (auto-saved with timestamp)
python examples/run_benchmark_evaluation.py --model gpt-4

# More steps (auto-saved with timestamp)
python examples/run_benchmark_evaluation.py --model gpt-4 --max-steps 20

# Earlier knowledge cutoff (auto-saved with timestamp)
python examples/run_benchmark_evaluation.py --model gpt-4 --knowledge-cutoff 2024-01-01

# All results are timestamped, so you can compare different configurations
```

### 4. Track Performance Over Time

Create a benchmarking script that runs daily:

```bash
#!/bin/bash
# daily_benchmark.sh

MODEL="gpt-4"

# Run benchmark (auto-saves to benchmarks/ with timestamp)
python examples/run_benchmark_evaluation.py \
  --model $MODEL \
  --skip-existing

echo "Benchmark complete! Check benchmarks/ directory for results."
```

Results accumulate in `benchmarks/` with automatic timestamping:
```
benchmarks/
├── benchmark_20251120_090000_gpt-4.json
├── benchmark_20251121_090000_gpt-4.json
├── benchmark_20251122_090000_gpt-4.json
└── ...
```

## Troubleshooting

### "No resolved questions found"

Questions need:
- `ground_truth` set (not None)
- At least N context items (default: 3)
- Temporal window calculable

**Solution**: Check your questions:
```python
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase('worldreasoner.db')
questions = db.get_many(Question)

for q in questions:
    print(f"{q.id}: ground_truth={q.ground_truth}")
```

### "MCP server connection failed"

**Solution**: Start the MCP server:
```bash
python -m src.mcp_forecasting_server
```

### "Model API error"

**Solution**: Check your API keys in `config/config.yaml`:
```yaml
llm:
  model: "gpt-4"
  api_key: "your-key-here"  # Must be valid
```

### Benchmark takes too long

**Solution**: Test with limited questions first:
```bash
python examples/run_benchmark_evaluation.py --max-questions 5
```

## Integration with CI/CD

Add benchmarking to your CI pipeline:

```yaml
# .github/workflows/benchmark.yml
name: Weekly Benchmark

on:
  schedule:
    - cron: '0 0 * * 0'  # Every Sunday

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run benchmark
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python examples/run_benchmark_evaluation.py \
            --max-questions 10 \
            --output benchmark_results.json
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: benchmark-results
          path: benchmark_results.json
```

## Future Enhancements

Potential improvements to benchmarking:

1. **Parallel execution** - Run multiple forecasts simultaneously
2. **Ensemble methods** - Combine predictions from multiple models
3. **Active learning** - Identify questions where models are uncertain
4. **Cost tracking** - Monitor API costs per benchmark run
5. **Temporal trends** - Track how accuracy changes with forecast horizon
6. **Domain-specific analysis** - Compare performance across different domains

## References

- [Brier Score - Wikipedia](https://en.wikipedia.org/wiki/Brier_score)
- [Good Judgment Project](https://goodjudgment.com/)
- [Superforecasting by Tetlock](https://www.penguinrandomhouse.com/books/227815/superforecasting-by-philip-e-tetlock-and-dan-gardner/)
