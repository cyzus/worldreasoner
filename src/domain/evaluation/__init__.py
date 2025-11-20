"""Forecast evaluation module.

This module provides tools for evaluating the accuracy of LLM forecasts
after questions have been resolved. Evaluation is separate from the
forecasting process and runs as a batch job after ground truth is available.
"""

from .evaluator import ForecastEvaluator, EvaluationResult
from .metrics import calculate_brier_score, calculate_log_score, calculate_accuracy

__all__ = [
    'ForecastEvaluator',
    'EvaluationResult',
    'calculate_brier_score',
    'calculate_log_score',
    'calculate_accuracy',
]
