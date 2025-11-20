# Forecast Evaluation System

This document describes the forecast evaluation system in WorldReasoner, which assesses the accuracy of LLM predictions after questions have been resolved.

## Architecture Overview

The evaluation system is **separate from the MCP forecasting server** by design:

```
┌─────────────────────────────────────────────────────────────────┐
│                    FORECASTING PHASE                            │
│                    (BEFORE Resolution)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  MCP Server  →  ForecastAgent  →  Forecast Saved to DB         │
│    ↓                ↓                      ↓                    │
│  Temporal      Makes         {prediction, confidence,           │
│  Context      Prediction      reasoning, simulated_date}        │
│  (No Ground                                                     │
│   Truth!)                                                       │
└─────────────────────────────────────────────────────────────────┘

                          ⏳ Time Passes...
                    Question reaches resolution_date
                    Ground truth becomes available

┌─────────────────────────────────────────────────────────────────┐
│                    EVALUATION PHASE                             │
│                    (AFTER Resolution)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ForecastEvaluator  →  Calculate Metrics  →  Update DB         │
│         ↓                      ↓                  ↓             │
│  Load Forecasts        {accuracy, brier,    Save evaluation    │
│  Load Ground Truth      log_score, etc.}    results            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why Separate Evaluation from MCP Server?

1. **Temporal Separation**:
   - Forecasting happens BEFORE the event resolves
   - Evaluation happens AFTER ground truth is available
   - These are fundamentally different time phases

2. **Information Isolation**:
   - MCP server must NOT have access to ground truth (would leak the answer)
   - Evaluation requires ground truth to calculate metrics
   - Keeping them separate prevents accidental information leakage

3. **Single Responsibility**:
   - MCP server: Provide temporally-constrained forecasting tools
   - Evaluator: Assess forecast accuracy after resolution
   - Each component has a clear, focused purpose

4. **Batch Processing**:
   - Evaluation is typically done in batches (all resolved questions)
   - Forecasting is done individually (one question at a time)
   - Different processing patterns require different architectures

## Components

### 1. Evaluation Metrics (`src/domain/evaluation/metrics.py`)

Implements standard forecasting metrics:

#### Accuracy
- Simple binary correctness (1.0 = correct, 0.0 = incorrect)
- For BOOLEAN/MCQ: exact match
- For QUANTITY: tolerance-based matching (±10% by default)

#### Brier Score
- Measures probabilistic accuracy: `BS = (forecast - outcome)²`
- Range: 0 (perfect) to 1 (worst)
- Lower is better
- Penalizes overconfidence in wrong predictions
- Standard metric in forecasting competitions (e.g., Good Judgment Project)

**Example**:
```python
# Prediction: YES with 70% confidence, Actual: YES
forecast_prob = 0.7
outcome = 1.0
brier_score = (0.7 - 1.0)² = 0.09  # Good score

# Prediction: YES with 90% confidence, Actual: NO
forecast_prob = 0.9
outcome = 0.0
brier_score = (0.9 - 0.0)² = 0.81  # Bad score (overconfident)
```

#### Log Score
- Logarithmic scoring rule: `LS = log(p_actual)`
- Range: -∞ (worst) to 0 (perfect)
- Higher is better
- Strongly penalizes very confident wrong predictions
- Proper scoring rule (incentivizes honest probability reporting)

**Example**:
```python
# Prediction: YES with 70% confidence, Actual: YES
log_score = log(0.7) = -0.357

# Prediction: YES with 90% confidence, Actual: NO
log_score = log(1 - 0.9) = log(0.1) = -2.303  # Much worse!
```

#### Calibration
- Measures whether confidence levels match actual accuracy
- Groups forecasts by confidence level (0-10%, 10-20%, etc.)
- Compares average confidence to actual accuracy in each bin
- Well-calibrated forecaster: 70% confidence → 70% accuracy

**Example**:
```
Confidence Range  |  Count  |  Accuracy  |  Calibration Error
60-70%           |   50    |   68%      |   2% (good!)
70-80%           |   30    |   55%      |   20% (overconfident)
```

### 2. Forecast Evaluator (`src/domain/evaluation/evaluator.py`)

Main class for evaluating forecasts:

```python
from src.domain.evaluation import ForecastEvaluator

# Initialize evaluator
evaluator = ForecastEvaluator(db_path='worldreasoner.db')

# Evaluate single forecast
result = evaluator.evaluate_forecast(forecast, question)
print(f"Correct: {result.is_correct}")
print(f"Brier Score: {result.brier_score:.4f}")

# Batch evaluate all resolved questions
results = evaluator.evaluate_all_resolved(update_forecasts=True)

# Generate summary report
report = evaluator.generate_evaluation_report(results)
print(f"Overall Accuracy: {report['overall_accuracy']:.2%}")
```

**Key Methods**:

- `is_question_resolved(question)`: Check if ground truth is available
- `evaluate_forecast(forecast, question)`: Evaluate single forecast
- `update_forecast_with_evaluation(forecast, result)`: Save evaluation to DB
- `evaluate_all_resolved(update_forecasts=True)`: Batch evaluation
- `generate_evaluation_report(results)`: Create summary statistics

### 3. Evaluation Script (`examples/evaluate_forecasts.py`)

Command-line tool for running evaluations:

```bash
# Evaluate all resolved forecasts and update database
python examples/evaluate_forecasts.py

# Dry run (don't update database)
python examples/evaluate_forecasts.py --no-update

# Evaluate specific forecast
python examples/evaluate_forecasts.py --forecast-id fcst_123

# Save report to JSON
python examples/evaluate_forecasts.py --output report.json

# Verbose output
python examples/evaluate_forecasts.py --verbose
```

**Output Example**:
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

Calibration Analysis (Boolean Questions):
------------------------------------------------------------
Mean Calibration Error: 0.0823

Confidence Bins:
Range           Count      Accuracy     Cal Error
0.5-0.6         8          50.00%       0.0500
0.6-0.7         12         66.67%       0.0167
0.7-0.8         10         80.00%       0.0500
0.8-0.9         5          60.00%       0.2500
```

## Workflow

### 1. Forecasting Phase (BEFORE resolution)

```bash
# Run forecast agent
python examples/run_forecast_smolagents.py

# Agent uses MCP server to:
# 1. Get question details (NO ground truth exposed)
# 2. Search temporally-filtered articles
# 3. Submit prediction with confidence and reasoning

# Forecast saved to database with:
# - prediction
# - confidence
# - reasoning
# - simulated_date
# - articles_accessed
# BUT: is_correct = None, brier_score = None (not evaluated yet)
```

**Special Case - Already Resolved Questions:**

If the question is already resolved (has ground truth), the forecast will be **automatically evaluated immediately** after submission:

```bash
# Run forecast on historical question
python examples/run_forecast_smolagents.py --question-id q_resolved_123

# Output:
# ... forecast process ...
# ⚡ Question is already resolved - evaluating forecast immediately...
#
# ================================================================================
# IMMEDIATE EVALUATION (Question Already Resolved)
# ================================================================================
#
# ✓ CORRECT
#
# Your Prediction: True (confidence: 75.0%)
# Actual Outcome:  True
#
# Accuracy: 100.0%
# Brier Score: 0.0625 (0=perfect, 1=worst)
# Log Score:   -0.2877 (higher is better)
#
# Forecast Horizon: 21 days ahead
#
# ✓ Evaluation saved to database

# Skip immediate evaluation with --no-evaluate flag
python examples/run_forecast_smolagents.py --question-id q_resolved_123 --no-evaluate
```

This is particularly useful for:
- **Testing with historical data**: Immediate feedback on forecast quality
- **Benchmarking**: Quick assessment of model performance
- **Development**: Rapid iteration when testing forecast logic

### 2. Resolution Phase

After the question's `resolution_date` passes, update ground truth:

```python
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase('worldreasoner.db')
question = db.get(Question, 'q_tech_20251117_003')

# Set ground truth (actual outcome)
question.ground_truth = True  # or False, or specific value
db.save(Question, question)
```

### 3. Batch Evaluation Phase (AFTER resolution)

For evaluating multiple forecasts at once:

```bash
# Run batch evaluation
python examples/evaluate_forecasts.py

# This will:
# 1. Find all resolved questions (ground_truth is not None)
# 2. Load all forecasts for those questions
# 3. Calculate accuracy, Brier score, log score
# 4. Update forecast records with evaluation results
# 5. Generate summary report
```

## Immediate vs Batch Evaluation

WorldReasoner supports two evaluation modes:

| Mode | When | Where | Use Case |
|------|------|-------|----------|
| **Immediate** | During forecast submission | `run_forecast_smolagents.py` | Historical questions, testing, rapid feedback |
| **Batch** | Separate process | `evaluate_forecasts.py` | Production, multiple forecasts, scheduled jobs |

**Architectural Note**: Even for immediate evaluation, the evaluation logic is **not in the MCP server**. It happens in the CLI script after the forecast is submitted. This maintains clean separation:
- MCP server: Pure forecasting tools (never sees ground truth)
- CLI script: Orchestration layer (can evaluate if appropriate)
- Evaluation module: Pure evaluation logic (reusable)

The MCP server remains stateless and focused solely on providing temporally-constrained forecasting tools.

## Database Schema Updates

The `Forecast` model includes evaluation fields:

```python
@register_model('forecasts', indexes=['question_id', 'session_id'])
class Forecast(BaseModel):
    # ... prediction fields ...

    # Evaluation results (populated AFTER resolution)
    is_correct: Optional[bool] = None
    brier_score: Optional[float] = None
    log_score: Optional[float] = None
    evaluation_metadata: Optional[Dict[str, Any]] = None
```

These fields are:
- `None` during forecasting phase
- Populated by `ForecastEvaluator` after resolution
- Indexed for efficient querying

## Best Practices

### 1. Never Expose Ground Truth During Forecasting

```python
# ✅ CORRECT - MCP server uses temporal filtering
@mcp.tool()
def get_question(ctx: Context) -> str:
    question = forecast_ctx["question"]
    return json.dumps({
        "question_text": question.question_text,
        # NO ground_truth field!
    })

# ❌ WRONG - Leaks the answer!
def get_question_wrong():
    return {
        "question_text": question.question_text,
        "ground_truth": question.ground_truth  # DON'T DO THIS!
    }
```

### 2. Evaluate Only Resolved Questions

```python
# ✅ CORRECT - Check resolution
if evaluator.is_question_resolved(question):
    result = evaluator.evaluate_forecast(forecast, question)

# ❌ WRONG - Will fail if not resolved
result = evaluator.evaluate_forecast(forecast, question)  # May raise ValueError
```

### 3. Run Batch Evaluation Periodically

Set up a cron job or scheduled task:

```bash
# Daily at 3 AM
0 3 * * * cd /path/to/worldreasoner && python examples/evaluate_forecasts.py
```

### 4. Track Evaluation Metadata

The evaluator includes useful metadata:

```python
result.evaluation_metadata = {
    'question_text': "...",
    'resolution_date': "2024-11-05T00:00:00Z",
    'simulated_date': "2024-10-15T00:00:00Z",
    'forecast_horizon_days': 21,  # How far ahead was the forecast?
    'articles_accessed_count': 15,
    'reasoning_word_count': 342
}
```

This helps analyze:
- How forecast horizon affects accuracy
- Whether more research improves predictions
- Quality of reasoning

## Integration with Benchmarking

The evaluation system integrates with WorldReasoner's benchmarking goals:

1. **Temporal Validity**: Evaluation respects `simulated_date` - all metrics account for when the forecast was made

2. **Proper Scoring**: Uses Brier and log scores to incentivize honest probability reporting

3. **Calibration Tracking**: Monitors whether models are well-calibrated over time

4. **Multi-Model Comparison**: Evaluation can compare different LLM models:

```bash
# Evaluate forecasts from different models
python examples/evaluate_forecasts.py --output gpt4_results.json
# (filter by model_name='gpt-4')

python examples/evaluate_forecasts.py --output claude_results.json
# (filter by model_name='claude-sonnet-4')
```

## Future Enhancements

Potential improvements:

1. **Baseline Comparisons**: Compare LLM forecasts to simple baselines (random, always yes, etc.)

2. **Temporal Trends**: Track how accuracy changes over time or with forecast horizon

3. **Reasoning Analysis**: Use LLMs to analyze reasoning quality

4. **Cross-Model Ensembles**: Combine predictions from multiple models

5. **Active Learning**: Identify questions where model is uncertain for targeted research

6. **Real-time Dashboard**: Visualize evaluation metrics over time

## References

- [Brier Score - Wikipedia](https://en.wikipedia.org/wiki/Brier_score)
- [Scoring Rules - Wikipedia](https://en.wikipedia.org/wiki/Scoring_rule)
- [Good Judgment Project](https://goodjudgment.com/)
- [Superforecasting (Tetlock & Gardner)](https://www.penguinrandomhouse.com/books/227815/superforecasting-by-philip-e-tetlock-and-dan-gardner/)
