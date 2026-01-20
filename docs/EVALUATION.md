# Forecast Evaluation System

The evaluation system assesses the accuracy of LLM predictions **after** questions have been resolved (ground truth available).

## Architecture

Evaluation is strictly separated from the MCP forecasting server to prevent information leakage.

1.  **Forecasting (Simulated Past)**: Agent makes prediction. NO ground truth access.
2.  **Evaluation (Present)**: Evaluator compares forecast vs. ground truth.

## Key Metrics

| Metric | Goal | Description | range |
|--------|------|-------------|-------|
| **Accuracy** | maximize | Simple percentage of correct predictions. | 0.0 - 1.0 |
| **Brier Score** | minimize | Probabilistic error: `(probability - outcome)²`. Perfect = 0. | 0.0 - 1.0 |
| **Log Score** | maximize | Logarithmic scoring rule. Heavily penalizes confident wrong answers. | -∞ - 0.0 |
| **Calibration**| match | Measures if "70% confidence" means "70% accurate". | N/A |

## Usage

### CLI

```bash
# Evaluate all resolved forecasts
python examples/evaluate_forecasts.py

# Evaluate specific forecast
python examples/evaluate_forecasts.py --forecast-id fcst_123

# Output JSON report
python examples/evaluate_forecasts.py --output report.json
```

### Python API

```python
from src.domain.evaluation import ForecastEvaluator

evaluator = ForecastEvaluator()
# Evaluate all resolved questions that usually haven't been evaluated yet
results = evaluator.evaluate_all_resolved(update_forecasts=True)
print(f"Overall Accuracy: {results['overall_accuracy']:.2%}")
```

## Best Practices

-   **Never** expose `ground_truth` to agents.
-   Run evaluation on a schedule (e.g., cron job) to catch newly resolved questions.
-   Use `Brier Score` as the primary metric for competitive comparison.
