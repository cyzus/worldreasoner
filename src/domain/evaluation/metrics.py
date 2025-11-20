"""Evaluation metrics for forecast accuracy.

This module implements standard forecasting metrics:
- Accuracy: Simple correctness for binary/MCQ questions
- Brier Score: Probabilistic accuracy metric (lower is better)
- Log Score: Logarithmic scoring rule (higher is better)
"""

import math
from typing import Any, Dict, Optional
from src.domain.models.question import QuestionType


def calculate_accuracy(prediction: Any, ground_truth: Any, question_type: QuestionType) -> float:
    """Calculate simple accuracy (1.0 for correct, 0.0 for incorrect).

    Args:
        prediction: The predicted value
        ground_truth: The actual outcome
        question_type: Type of question

    Returns:
        1.0 if correct, 0.0 if incorrect
    """
    if question_type == QuestionType.BOOLEAN:
        return 1.0 if prediction == ground_truth else 0.0

    elif question_type == QuestionType.MCQ:
        return 1.0 if prediction == ground_truth else 0.0

    elif question_type == QuestionType.QUANTITY:
        # For quantities, we need to define what "correct" means
        # Simple approach: exact match
        # Better approach: within tolerance or range
        if isinstance(prediction, dict) and isinstance(ground_truth, (int, float)):
            # Prediction is a range, ground truth is a value
            return 1.0 if prediction.get('lower', 0) <= ground_truth <= prediction.get('upper', float('inf')) else 0.0
        elif isinstance(prediction, (int, float)) and isinstance(ground_truth, (int, float)):
            # Both are point estimates - check if within 10% tolerance
            tolerance = abs(ground_truth) * 0.1
            return 1.0 if abs(prediction - ground_truth) <= tolerance else 0.0
        return 0.0

    elif question_type == QuestionType.TIMEFRAME:
        # For timeframes, check if predicted date is close to actual
        # This would need more sophisticated logic
        return 1.0 if prediction == ground_truth else 0.0

    return 0.0


def calculate_brier_score(
    prediction: Any,
    ground_truth: Any,
    confidence: float,
    question_type: QuestionType
) -> Optional[float]:
    """Calculate Brier score for probabilistic forecasts.

    The Brier score measures the mean squared difference between predicted
    probabilities and actual outcomes. Lower is better (0 = perfect, 1 = worst).

    Formula for binary: BS = (forecast - outcome)^2
    where outcome is 1 for YES, 0 for NO

    Args:
        prediction: The predicted value
        ground_truth: The actual outcome
        confidence: Confidence level (0-1)
        question_type: Type of question

    Returns:
        Brier score (0-1), or None if not applicable

    References:
        - https://en.wikipedia.org/wiki/Brier_score
        - Brier, G. W. (1950). "Verification of forecasts expressed in terms of probability"
    """
    if question_type == QuestionType.BOOLEAN:
        # Convert prediction to probability
        if prediction is True:
            forecast_prob = confidence
        else:
            forecast_prob = 1 - confidence

        # Outcome is 1 for YES, 0 for NO
        outcome = 1.0 if ground_truth else 0.0

        # Brier score = (forecast - outcome)^2
        return (forecast_prob - outcome) ** 2

    elif question_type == QuestionType.MCQ:
        # For MCQ, use multi-class Brier score
        # Assume uniform confidence distribution if not specified
        # This is simplified - ideally we'd have per-option probabilities
        if prediction == ground_truth:
            # Predicted the correct option with confidence
            return (1 - confidence) ** 2
        else:
            # Predicted wrong option
            return confidence ** 2

    elif question_type == QuestionType.QUANTITY:
        # Brier score doesn't apply directly to continuous quantities
        # Could use normalized squared error instead
        return None

    return None


def calculate_log_score(
    prediction: Any,
    ground_truth: Any,
    confidence: float,
    question_type: QuestionType
) -> Optional[float]:
    """Calculate logarithmic scoring rule.

    The log score rewards confidence in correct predictions and penalizes
    confidence in incorrect predictions. Higher is better.

    Formula for binary: LS = log(p) if correct, log(1-p) if incorrect
    where p is the probability assigned to what actually happened

    Args:
        prediction: The predicted value
        ground_truth: The actual outcome
        confidence: Confidence level (0-1)
        question_type: Type of question

    Returns:
        Log score (negative infinity to 0), or None if not applicable

    References:
        - https://en.wikipedia.org/wiki/Scoring_rule#Logarithmic_scoring_rule
    """
    if question_type == QuestionType.BOOLEAN:
        # Convert prediction to probability
        if prediction is True:
            forecast_prob = confidence
        else:
            forecast_prob = 1 - confidence

        # Probability of what actually happened
        if ground_truth:
            prob_actual = forecast_prob
        else:
            prob_actual = 1 - forecast_prob

        # Avoid log(0)
        prob_actual = max(prob_actual, 1e-10)

        # Log score
        return math.log(prob_actual)

    elif question_type == QuestionType.MCQ:
        # For MCQ, log of probability assigned to correct answer
        if prediction == ground_truth:
            prob_correct = confidence
        else:
            # Distributed among other options
            # This is simplified
            prob_correct = 1 - confidence

        prob_correct = max(prob_correct, 1e-10)
        return math.log(prob_correct)

    return None


def calculate_calibration_metrics(predictions: list, ground_truths: list, confidences: list) -> Dict[str, float]:
    """Calculate calibration metrics across multiple forecasts.

    Calibration measures whether confidence levels match actual accuracy.
    For example, predictions with 70% confidence should be correct 70% of the time.

    Args:
        predictions: List of predictions
        ground_truths: List of actual outcomes
        confidences: List of confidence levels

    Returns:
        Dict with calibration metrics:
        - calibration_error: Mean absolute difference between confidence and accuracy
        - reliability_curve: Binned confidence vs accuracy data
    """
    # Bin predictions by confidence level
    bins = [(i/10, (i+1)/10) for i in range(10)]  # 10 bins: 0-0.1, 0.1-0.2, ..., 0.9-1.0

    bin_stats = []
    total_calibration_error = 0.0
    count = 0

    for bin_lower, bin_upper in bins:
        # Get predictions in this confidence bin
        bin_predictions = []
        bin_outcomes = []

        for pred, truth, conf in zip(predictions, ground_truths, confidences):
            if bin_lower <= conf < bin_upper or (bin_upper == 1.0 and conf == 1.0):
                bin_predictions.append(pred)
                bin_outcomes.append(truth)

        if bin_predictions:
            # Calculate accuracy in this bin
            correct = sum(1 for p, t in zip(bin_predictions, bin_outcomes) if p == t)
            accuracy = correct / len(bin_predictions)
            avg_confidence = (bin_lower + bin_upper) / 2

            # Calibration error for this bin
            calibration_error = abs(avg_confidence - accuracy)
            total_calibration_error += calibration_error * len(bin_predictions)
            count += len(bin_predictions)

            bin_stats.append({
                'confidence_range': (bin_lower, bin_upper),
                'count': len(bin_predictions),
                'accuracy': accuracy,
                'calibration_error': calibration_error
            })

    mean_calibration_error = total_calibration_error / count if count > 0 else 0.0

    return {
        'mean_calibration_error': mean_calibration_error,
        'bins': bin_stats
    }
