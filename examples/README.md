# WorldReasoner Examples

This directory contains example scripts demonstrating how to use the WorldReasoner library.
These examples are designed to be minimal and educational.

Most scripts use an **in-memory database** (`:memory:`) by default to avoid side effects. You can persist data by providing a path via `--db my.db`.

## 🔮 Forecasting

### `run_forecast.py`
Run a single forecast on a question.
```bash
python examples/run_forecast.py --question-id <ID>
```

### `run_realtime_forecast.py`
Run a forecast with full web access enabled (search, fetch).
```bash
python examples/run_realtime_forecast.py --query "Will X happen?"
```

## 📊 Evaluation & Benchmarking

### `run_benchmark_evaluation.py`
Run forecasts on all resolved questions in the DB to measure performance.
```bash
python examples/run_benchmark_evaluation.py --max-questions 10
```

### `evaluate_forecasts.py`
Evaluate existing forecast records against ground truth.
```bash
python examples/evaluate_forecasts.py
```

### `visualize_benchmarks.py`
Generate charts from benchmark JSON results.
```bash
python examples/visualize_benchmarks.py --benchmarks-dir benchmarks
```

### `run_temporal_forecast_analysis.py`
Analyze how forecast accuracy evolves as the resolution date approaches.
```bash
python examples/run_temporal_forecast_analysis.py --question-id <ID>
```

## 🧠 Causal Analysis

### `deep_causal_analysis.py`
Demonstrates the `HindsightAgent` for building causal graphs for past events.
```bash
python examples/deep_causal_analysis.py
```

## 📥 Data Collection

### `run_goal_collection.py`
Demonstrates the goal-oriented data collection orchestrator.
```bash
python examples/run_goal_collection.py
```
