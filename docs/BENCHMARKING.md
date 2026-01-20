# Benchmarking Guide

This guide details how to evaluate LLM forecasting performance using WorldReasoner's automated tools.

## Quick Reference

| Script | Purpose |
|--------|---------|
| `examples/run_benchmark_evaluation.py` | **Primary Tool**. Runs forecasts on valid questions and evaluates results. |
| `examples/visualize_benchmarks.py` | Generates comparative charts (accuracy, calibration) from benchmark results. |
| `examples/run_temporal_forecast_analysis.py` | Analyzes how forecast accuracy changes for a single question as context reveals over time. |
| `examples/evaluate_forecasts.py` | Re-evaluates existing forecast records in the database. |

## 1. Automated Benchmarking

The `run_benchmark_evaluation.py` script identifies resolved questions, runs the `ForecastAgent` with temporal masking, and calculates metrics.

### Usage

```bash
python examples/run_benchmark_evaluation.py [OPTIONS]
```

### Key Options

| Flag | Description | Default |
|------|-------------|---------|
| `--model` | LLM model to test (e.g., `gpt-4`). | Config default |
| `--knowledge-only` | **Important**. Disables external research tools to test inherent knowledge. | `False` |
| `--offset-days` | Analysis point relative to resolution (0 = at resolution). | `0` |
| `--knowledge-cutoff` | Simulate a specific past date for training cutoff. | None |
| `--min-context-items` | Minimum articles/events required before forecasting. | `3` |
| `--output` | Custom path for results JSON. | `benchmarks/benchmark_<time>_<model>.json` |

## 2. Visualization

Generate charts from your benchmark JSON files.

```bash
python examples/visualize_benchmarks.py --output-dir my_figures/
```

**Outputs:**
- `accuracy_comparison.png`: Bar chart by model/mode.
- `brier_score_comparison.png`: Calibration quality (lower is better).
- `performance_timeline.png`: Accuracy trends over time.

## 3. Temporal Analysis

Understand how "early" a model can predict an event.

```bash
python examples/run_temporal_forecast_analysis.py --question-id <id> --num-points 5
```

Generates a timeline showing context availability vs. forecast confidence.

## CI/CD Integration

To run weekly benchmarks via GitHub Actions:

```yaml
- name: Run benchmark
  run: python examples/run_benchmark_evaluation.py --max-questions 10
```
- Low confidence even with lots of context (uncertain)

## Future Enhancements

Potential improvements to benchmarking:

1. **Parallel execution** - Run multiple forecasts simultaneously
2. **Ensemble methods** - Combine predictions from multiple models
3. **Active learning** - Identify questions where models are uncertain
4. **Cost tracking** - Monitor API costs per benchmark run
5. **Domain-specific analysis** - Compare performance across different domains
6. **Multi-question temporal analysis** - Aggregate temporal patterns across questions

## References

- [Brier Score - Wikipedia](https://en.wikipedia.org/wiki/Brier_score)
- [Good Judgment Project](https://goodjudgment.com/)
- [Superforecasting by Tetlock](https://www.penguinrandomhouse.com/books/227815/superforecasting-by-philip-e-tetlock-and-dan-gardner/)
