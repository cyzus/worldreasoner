"""Forecast evaluation module.

This module provides tools for evaluating the accuracy of LLM forecasts
after questions have been resolved. Evaluation is separate from the
forecasting process and runs as a batch job after ground truth is available.

Also includes the auto-benchmark system for running ablation studies
across multiple experimental conditions, models, and questions.
"""

from .evaluator import ForecastEvaluator, EvaluationResult
from .metrics import calculate_brier_score, calculate_log_score, calculate_accuracy
from .conditions import ConditionName, ExperimentCondition, EXPERIMENT_CONDITIONS
from .auto_benchmark import AutoBenchmarkService, AutoBenchmarkResult

__all__ = [
    "ForecastEvaluator",
    "EvaluationResult",
    "calculate_brier_score",
    "calculate_log_score",
    "calculate_accuracy",
    "ConditionName",
    "ExperimentCondition",
    "EXPERIMENT_CONDITIONS",
    "AutoBenchmarkService",
    "AutoBenchmarkResult",
]
