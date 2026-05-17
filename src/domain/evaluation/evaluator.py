"""Forecast evaluator for assessing prediction accuracy.

This module provides the main ForecastEvaluator class that evaluates
forecasts against ground truth after questions have been resolved.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from src.core.database import GenericDatabase
from src.domain.models import Forecast, Question
from src.utils.logging import logger

from .metrics import (
    calculate_accuracy,
    calculate_brier_score,
    calculate_log_score,
    calculate_calibration_metrics,
)


class EvaluationResult(BaseModel):
    """Result of evaluating a single forecast.

    Contains all evaluation metrics and metadata about the evaluation.
    """

    forecast_id: str = Field(..., description="ID of the forecast being evaluated")
    question_id: str = Field(..., description="ID of the question")

    # Basic correctness
    is_correct: bool = Field(..., description="Whether the prediction was correct")
    accuracy: float = Field(..., description="Accuracy score (1.0 or 0.0)")

    # Probabilistic metrics
    brier_score: Optional[float] = Field(
        None, description="Brier score (0-1, lower is better)"
    )
    log_score: Optional[float] = Field(None, description="Log score (higher is better)")

    # Metadata
    prediction: Any = Field(..., description="The prediction that was made")
    ground_truth: Any = Field(..., description="The actual outcome")
    confidence: float = Field(..., description="Confidence level of the prediction")
    question_type: str = Field(..., description="Type of question")

    # Additional analysis
    evaluation_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional evaluation details"
    )

    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the evaluation was performed",
    )


class ForecastEvaluator:
    """Evaluates forecast accuracy after questions have been resolved.

    This class is responsible for:
    1. Checking if questions are resolved (have ground truth)
    2. Calculating evaluation metrics for forecasts
    3. Updating forecast records with evaluation results
    4. Generating evaluation reports

    Example:
        >>> evaluator = ForecastEvaluator(db_path='worldreasoner.db')
        >>> # Evaluate a single forecast
        >>> result = evaluator.evaluate_forecast(forecast, question)
        >>> print(f"Accuracy: {result.accuracy}, Brier: {result.brier_score}")
        >>>
        >>> # Batch evaluate all resolved questions
        >>> results = evaluator.evaluate_all_resolved()
        >>> print(f"Evaluated {len(results)} forecasts")
    """

    def __init__(self, db_path: str):
        """Initialize the evaluator.

        Args:
            db_path: Path to the WorldReasoner database
        """
        self.db = GenericDatabase(db_path)
        logger.info(f"ForecastEvaluator initialized with database: {db_path}")

    def is_question_resolved(self, question: Question) -> bool:
        """Check if a question has been resolved (has ground truth).

        Args:
            question: Question to check

        Returns:
            True if the question has ground truth and is past resolution date
        """
        if question.ground_truth is None:
            return False

        # Check if we're past the resolution date
        now = datetime.now(timezone.utc)
        if question.resolution_date > now:
            logger.warning(
                f"Question {question.id} has ground truth but resolution date "
                f"{question.resolution_date.date()} is in the future"
            )
            return False

        return True

    def evaluate_forecast(
        self, forecast: Forecast, question: Question
    ) -> EvaluationResult:
        """Evaluate a single forecast against ground truth.

        Args:
            forecast: The forecast to evaluate
            question: The question with ground truth

        Returns:
            EvaluationResult with all metrics

        Raises:
            ValueError: If question is not resolved or forecast doesn't match question
        """
        # Validate inputs
        if not self.is_question_resolved(question):
            raise ValueError(
                f"Question {question.id} is not resolved yet "
                f"(ground_truth={question.ground_truth}, resolution_date={question.resolution_date})"
            )

        if forecast.question_id != question.id:
            raise ValueError(
                f"Forecast question_id {forecast.question_id} doesn't match "
                f"question id {question.id}"
            )

        # Calculate metrics
        accuracy = calculate_accuracy(
            forecast.prediction,
            question.ground_truth,
            question.question_type,
            question_text=question.question_text,
            options=question.options,
        )

        is_correct = accuracy == 1.0

        brier_score = calculate_brier_score(
            forecast.prediction,
            question.ground_truth,
            forecast.confidence,
            question.question_type,
            options=question.options,
        )

        log_score = calculate_log_score(
            forecast.prediction,
            question.ground_truth,
            forecast.confidence,
            question.question_type,
            options=question.options,
        )

        # Build evaluation metadata
        evaluation_metadata = {
            "question_text": question.question_text,
            "resolution_date": question.resolution_date.isoformat(),
            "simulated_date": forecast.simulated_date.isoformat()
            if forecast.simulated_date
            else None,
            "forecast_horizon_days": (
                (question.resolution_date - forecast.simulated_date).days
                if forecast.simulated_date
                else None
            ),
            "articles_accessed_count": len(forecast.articles_accessed),
            "searches_performed_count": len(forecast.searches_performed),
            "reasoning_word_count": forecast.get_reasoning_word_count(),
        }

        # Create evaluation result
        result = EvaluationResult(
            forecast_id=forecast.id,
            question_id=question.id,
            is_correct=is_correct,
            accuracy=accuracy,
            brier_score=brier_score,
            log_score=log_score,
            prediction=forecast.prediction,
            ground_truth=question.ground_truth,
            confidence=forecast.confidence,
            question_type=question.question_type.value,
            evaluation_metadata=evaluation_metadata,
        )

        # Format scores for logging
        brier_str = f"{brier_score:.3f}" if brier_score is not None else "N/A"
        log_str = f"{log_score:.3f}" if log_score is not None else "N/A"

        logger.info(
            f"Evaluated forecast {forecast.id}: "
            f"correct={is_correct}, brier={brier_str}, log={log_str}"
        )

        return result

    def update_forecast_with_evaluation(
        self, forecast: Forecast, evaluation: EvaluationResult
    ) -> Forecast:
        """Update a forecast object with evaluation results.

        This modifies the forecast in-place and saves it to the database.

        Args:
            forecast: The forecast to update
            evaluation: The evaluation results

        Returns:
            Updated forecast object
        """
        forecast.is_correct = evaluation.is_correct
        forecast.brier_score = evaluation.brier_score
        forecast.log_score = evaluation.log_score
        existing = forecast.evaluation_metadata or {}
        forecast.evaluation_metadata = {**existing, **evaluation.evaluation_metadata}

        # Save to database
        self.db.save(Forecast, forecast)

        logger.info(f"Updated forecast {forecast.id} with evaluation results")

        return forecast

    def evaluate_all_resolved(
        self, update_forecasts: bool = True
    ) -> List[EvaluationResult]:
        """Evaluate all forecasts for resolved questions.

        This is the main batch evaluation method.

        Args:
            update_forecasts: Whether to update forecast records with evaluation results

        Returns:
            List of evaluation results
        """
        logger.info("Starting batch evaluation of all resolved questions")

        # Get all questions
        all_questions = self.db.get_many(Question)
        resolved_questions = [q for q in all_questions if self.is_question_resolved(q)]

        logger.info(
            f"Found {len(resolved_questions)} resolved questions out of "
            f"{len(all_questions)} total"
        )

        # Get all forecasts
        all_forecasts = self.db.get_many(Forecast)
        logger.info(f"Found {len(all_forecasts)} total forecasts")

        # Evaluate each forecast
        results = []
        evaluated_count = 0
        skipped_count = 0

        for forecast in all_forecasts:
            # Find matching question
            question = next(
                (q for q in resolved_questions if q.id == forecast.question_id), None
            )

            if not question:
                logger.debug(
                    f"Skipping forecast {forecast.id}: "
                    f"question {forecast.question_id} not resolved yet"
                )
                skipped_count += 1
                continue

            try:
                # Evaluate the forecast
                evaluation = self.evaluate_forecast(forecast, question)
                results.append(evaluation)
                evaluated_count += 1

                # Update forecast if requested
                if update_forecasts:
                    self.update_forecast_with_evaluation(forecast, evaluation)

            except Exception as e:
                logger.error(
                    f"Error evaluating forecast {forecast.id}: {e}", exc_info=True
                )
                continue

        logger.info(
            f"Batch evaluation complete: {evaluated_count} evaluated, "
            f"{skipped_count} skipped"
        )

        return results

    def generate_evaluation_report(
        self, results: List[EvaluationResult]
    ) -> Dict[str, Any]:
        """Generate a summary report from evaluation results.

        Args:
            results: List of evaluation results

        Returns:
            Dict with summary statistics
        """
        if not results:
            return {"total_forecasts": 0, "message": "No evaluation results available"}

        # Overall statistics
        total = len(results)
        correct = sum(1 for r in results if r.is_correct)
        accuracy_rate = correct / total if total > 0 else 0.0

        # Brier scores
        brier_scores = [r.brier_score for r in results if r.brier_score is not None]
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        # Log scores
        log_scores = [r.log_score for r in results if r.log_score is not None]
        avg_log = sum(log_scores) / len(log_scores) if log_scores else None

        # By question type
        by_type = {}
        for result in results:
            qtype = result.question_type
            if qtype not in by_type:
                by_type[qtype] = {
                    "count": 0,
                    "correct": 0,
                    "brier_scores": [],
                    "log_scores": [],
                }

            by_type[qtype]["count"] += 1
            if result.is_correct:
                by_type[qtype]["correct"] += 1
            if result.brier_score is not None:
                by_type[qtype]["brier_scores"].append(result.brier_score)
            if result.log_score is not None:
                by_type[qtype]["log_scores"].append(result.log_score)

        # Calculate averages by type
        type_summary = {}
        for qtype, stats in by_type.items():
            type_summary[qtype] = {
                "count": stats["count"],
                "accuracy": stats["correct"] / stats["count"]
                if stats["count"] > 0
                else 0.0,
                "avg_brier_score": (
                    sum(stats["brier_scores"]) / len(stats["brier_scores"])
                    if stats["brier_scores"]
                    else None
                ),
                "avg_log_score": (
                    sum(stats["log_scores"]) / len(stats["log_scores"])
                    if stats["log_scores"]
                    else None
                ),
            }

        # By forecast mode
        by_mode = {}
        for result in results:
            # We need to fetch the forecast to get the mode
            # This is slightly inefficient but necessary unless we add mode to EvaluationResult
            try:
                forecast = self.db.get(Forecast, result.forecast_id)
                if not forecast:
                    continue

                mode = (
                    forecast.mode.value
                    if hasattr(forecast.mode, "value")
                    else str(forecast.mode)
                )

                if mode not in by_mode:
                    by_mode[mode] = {
                        "count": 0,
                        "correct": 0,
                        "brier_scores": [],
                        "log_scores": [],
                    }

                by_mode[mode]["count"] += 1
                if result.is_correct:
                    by_mode[mode]["correct"] += 1
                if result.brier_score is not None:
                    by_mode[mode]["brier_scores"].append(result.brier_score)
                if result.log_score is not None:
                    by_mode[mode]["log_scores"].append(result.log_score)
            except Exception:
                continue

        # Calculate averages by mode
        mode_summary = {}
        for mode, stats in by_mode.items():
            mode_summary[mode] = {
                "count": stats["count"],
                "accuracy": stats["correct"] / stats["count"]
                if stats["count"] > 0
                else 0.0,
                "avg_brier_score": (
                    sum(stats["brier_scores"]) / len(stats["brier_scores"])
                    if stats["brier_scores"]
                    else None
                ),
                "avg_log_score": (
                    sum(stats["log_scores"]) / len(stats["log_scores"])
                    if stats["log_scores"]
                    else None
                ),
            }

        # Calibration metrics (for boolean questions)
        boolean_results = [r for r in results if r.question_type == "boolean"]
        calibration = None
        if boolean_results:
            predictions = [r.prediction for r in boolean_results]
            ground_truths = [r.ground_truth for r in boolean_results]
            confidences = [r.confidence for r in boolean_results]
            calibration = calculate_calibration_metrics(
                predictions, ground_truths, confidences
            )

        # Collect model information from forecasts
        model_info = self._collect_model_info(results)

        return {
            "total_forecasts": total,
            "overall_accuracy": accuracy_rate,
            "avg_brier_score": avg_brier,
            "avg_log_score": avg_log,
            "by_question_type": type_summary,
            "by_mode": mode_summary,
            "calibration": calibration,
            "model_info": model_info,
            "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _collect_model_info(self, results: List[EvaluationResult]) -> Dict[str, Any]:
        """Collect model information from evaluation results.

        Args:
            results: List of evaluation results

        Returns:
            Dict with model statistics
        """
        # Get unique models from evaluation metadata
        models = {}

        for result in results:
            # Try to get model name from forecast
            # We need to fetch the forecast to get model info
            try:
                forecast = self.db.get(Forecast, result.forecast_id)
                if forecast and forecast.model_name:
                    model_name = forecast.model_name
                    if model_name not in models:
                        models[model_name] = {
                            "count": 0,
                            "correct": 0,
                            "version": forecast.model_version,
                        }
                    models[model_name]["count"] += 1
                    if result.is_correct:
                        models[model_name]["correct"] += 1
            except Exception:
                continue

        # Calculate accuracy per model
        model_summary = {}
        for model_name, stats in models.items():
            model_summary[model_name] = {
                "count": stats["count"],
                "accuracy": stats["correct"] / stats["count"]
                if stats["count"] > 0
                else 0.0,
                "version": stats["version"],
            }

        return {"models": model_summary, "total_unique_models": len(models)}
