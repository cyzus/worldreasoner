"""Runner for benchmark evaluations."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging

from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast
from src.domain.models.question_helpers import ForecastSlot, get_forecast_date_for_slot
from src.agents.factory import AgentFactory
from src.domain.evaluation.evaluator import ForecastEvaluator

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Runs benchmark evaluations on questions."""

    def __init__(self, db: GenericDatabase, config):
        self.db = db
        self.config = config
        self.evaluator = ForecastEvaluator(db_path=db.db_path)

    def get_resolved_questions(self, min_context_items: int = 3) -> List[Question]:
        """Get all resolved questions with sufficient context."""
        all_questions = self.db.get_many(Question)
        resolved = []
        for question in all_questions:
            if question.ground_truth is None:
                continue
            try:
                # Check context availability
                question.get_forecast_context_window()
                resolved.append(question)
            except ValueError:
                continue
        return resolved

    def run_single_forecast(
        self,
        question: Question,
        knowledge_cutoff: str,
        slot: str = "mid",
        min_context_items: int = 3,
        max_steps: int = 15,
        mode: str = "container",
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """Run forecast on a single question and evaluate."""
        try:
            # Prepare forecast via slot-based date selection
            try:
                forecast_slot = ForecastSlot(slot)
            except ValueError:
                forecast_slot = ForecastSlot.MID

            forecast_setup = get_forecast_date_for_slot(question, slot=forecast_slot)

            if verbose:
                print(f"\\nQuestion: {question.id}")
                print(f"  Text: {question.question_text[:100]}...")

            # Create agent
            agent = AgentFactory.create_forecast_agent(
                question=question,
                simulated_date=forecast_setup["simulated_date"].isoformat(),
                knowledge_cutoff=knowledge_cutoff,
                config=self.config,
                max_steps=max_steps,
                mode=mode,
            )

            # Run agent
            result = agent.run(
                "Use the get_question tool to see what you need to forecast, then try to answer it."
            )

            # Get the submitted forecast
            forecasts = self.db.get_many(Forecast, filters={"question_id": question.id})
            if not forecasts:
                return {
                    "question_id": question.id,
                    "status": "error",
                    "error": "No forecast created",
                }

            forecast = max(forecasts, key=lambda f: f.timestamp)

            # Tag the forecast with the slot label before evaluation is persisted
            existing_meta = forecast.evaluation_metadata or {}
            forecast.evaluation_metadata = {**existing_meta, "slot": slot}

            # Evaluate
            evaluation = self.evaluator.evaluate_forecast(forecast, question)
            self.evaluator.update_forecast_with_evaluation(forecast, evaluation)

            return {
                "question_id": question.id,
                "forecast_id": forecast.id,
                "status": "success",
                "evaluation": {
                    "is_correct": evaluation.is_correct,
                    "accuracy": evaluation.accuracy,
                    "brier_score": evaluation.brier_score,
                    "log_score": evaluation.log_score,
                    "confidence": evaluation.confidence,
                    "prediction": evaluation.prediction,
                    "ground_truth": evaluation.ground_truth,
                },
                "metadata": evaluation.evaluation_metadata,
            }

        except Exception as e:
            logger.error(
                f"Error forecasting question {question.id}: {e}", exc_info=True
            )
            return {"question_id": question.id, "status": "error", "error": str(e)}

    def run_benchmark(
        self,
        questions: List[Question],
        knowledge_cutoff: str,
        slot: str = "mid",
        min_context_items: int = 3,
        max_steps: int = 15,
        mode: str = "container",
        model_name: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """Run benchmark on a list of questions."""
        start_time = datetime.now(timezone.utc)
        results = []

        if model_name:
            self.config.llm.model = model_name

        print(f"Running benchmark on {len(questions)} questions...")

        for i, question in enumerate(questions, 1):
            if verbose:
                print(f"[{i}/{len(questions)}] Processing {question.id}...")

            result = self.run_single_forecast(
                question=question,
                knowledge_cutoff=knowledge_cutoff,
                slot=slot,
                min_context_items=min_context_items,
                max_steps=max_steps,
                mode=mode,
                verbose=verbose,
            )
            results.append(result)

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # Generate report
        successful = [r for r in results if r["status"] == "success"]
        failed = [r for r in results if r["status"] == "error"]

        accuracy = 0.0
        if successful:
            correct_count = sum(1 for r in successful if r["evaluation"]["is_correct"])
            accuracy = correct_count / len(successful)

        brier_scores = [
            r["evaluation"]["brier_score"]
            for r in successful
            if r["evaluation"]["brier_score"] is not None
        ]
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        return {
            "benchmark_info": {
                "timestamp": end_time.isoformat(),
                "duration_seconds": duration,
                "questions_per_minute": (len(results) / duration * 60)
                if duration > 0
                else 0,
            },
            "model_info": {
                "model": self.config.llm.model,
                "max_steps": max_steps,
                "knowledge_cutoff": knowledge_cutoff,
                "slot": slot,
                "mode": mode,
            },
            "results": {
                "total_questions": len(results),
                "successful": len(successful),
                "failed": len(failed),
                "overall_accuracy": accuracy,
                "avg_brier_score": avg_brier,
            },
            "detailed_results": results if verbose else None,
        }
