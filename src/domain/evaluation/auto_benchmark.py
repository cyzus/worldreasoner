"""Auto-benchmark service for running ablation study experiments.

Orchestrates running all experimental conditions x models x questions,
producing comparative results for the research paper.
"""

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.config import Config, get_config
from src.core.database import GenericDatabase
from src.domain.evaluation.conditions import (
    ConditionName,
    ExperimentCondition,
    get_conditions,
)
from src.domain.evaluation.evaluator import ForecastEvaluator, EvaluationResult
from src.domain.models import Article, Event, Forecast, Question
from src.domain.models.question_helpers import (
    ForecastSlot,
    get_forecast_date_for_slot,
)
from src.pipelines.prompts.forecast import get_forecast_instructions
from src.utils.llm_utils import get_knowledge_cutoff_date
from src.utils.logging import logger


@dataclass
class AutoBenchmarkProgress:
    """Progress tracking for auto-benchmark runs."""

    condition_index: int
    condition_total: int
    condition_name: str
    model_index: int
    model_total: int
    model_name: str
    question_index: int
    question_total: int
    question_id: str
    overall_current: int
    overall_total: int


@dataclass
class ConditionResult:
    """Aggregated results for a single (condition, model) pair."""

    condition_name: str
    display_name: str
    model_name: str
    total_questions: int = 0
    successful: int = 0
    failed: int = 0
    accuracy: float = 0.0
    avg_brier_score: Optional[float] = None
    avg_log_score: Optional[float] = None
    detailed_results: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AutoBenchmarkResult:
    """Full result of an auto-benchmark run."""

    run_id: str
    timestamp: str
    duration_seconds: float
    configuration: Dict[str, Any]
    condition_results: Dict[str, Dict[str, ConditionResult]]
    comparative_summary: Dict[str, Any]


class AutoBenchmarkService:
    """Orchestrates running all experiment conditions across models and questions."""

    def __init__(
        self,
        db_path: str = "worldreasoner.db",
        config: Optional[Config] = None,
        output_dir: str = "benchmarks",
    ):
        self.db_path = db_path
        self.db = GenericDatabase(db_path)
        self.config = config or get_config()
        self.output_dir = Path(output_dir)

    def get_resolved_questions(
        self,
        question_ids: Optional[List[str]] = None,
        min_context_items: int = 3,
        max_questions: Optional[int] = None,
        source: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[Question]:
        """Get resolved questions suitable for benchmarking.

        Args:
            question_ids: If provided, only these questions (must be resolved)
            min_context_items: Minimum articles/evidence for the question
            max_questions: Limit number of questions returned
            source: Filter by question source
            domain: Filter by domain

        Returns:
            List of resolved Question objects
        """
        if question_ids:
            questions = []
            for qid in question_ids:
                q = self.db.get(Question, qid)
                if q and q.ground_truth is not None:
                    questions.append(q)
                else:
                    logger.warning(f"Question {qid} not found or not resolved, skipping")
        else:
            all_questions = self.db.get_many(Question)
            now = datetime.now(timezone.utc)
            questions = [
                q
                for q in all_questions
                if q.ground_truth is not None
                and q.resolution_date is not None
                and q.resolution_date <= now
            ]

        if source:
            questions = [q for q in questions if q.source == source]

        if domain:
            questions = [
                q
                for q in questions
                if (q.domain.value if hasattr(q.domain, "value") else str(q.domain))
                == domain
            ]

        # Filter by minimum evidence (articles + events)
        if min_context_items > 0:
            all_articles = self.db.get_many(Article)
            all_events = self.db.get_many(Event)

            # Count articles per question
            article_counts: Dict[str, int] = {}
            for a in all_articles:
                qid = a.collected_for_question_id
                if qid:
                    article_counts[qid] = article_counts.get(qid, 0) + 1

            # Count events per question
            event_counts: Dict[str, int] = {}
            for e in all_events:
                qid = e.extracted_for_question_id
                if qid:
                    event_counts[qid] = event_counts.get(qid, 0) + 1

            before_count = len(questions)
            questions = [
                q
                for q in questions
                if article_counts.get(q.id, 0) + event_counts.get(q.id, 0)
                >= min_context_items
            ]
            filtered_count = before_count - len(questions)
            if filtered_count > 0:
                logger.info(
                    f"Filtered {filtered_count} questions with < {min_context_items} "
                    f"evidence items ({len(questions)} remaining)"
                )

        if max_questions:
            questions = questions[:max_questions]

        return questions

    def _compute_simulated_date(
        self,
        question: Question,
        condition: ExperimentCondition,
        slot: str = "mid",
    ) -> datetime:
        """Compute the simulated date for a forecast.

        For oracle conditions, uses resolution_date - 1 day.
        For others, uses get_forecast_date_for_slot() with the given slot.
        """
        if condition.is_oracle:
            return question.resolution_date - timedelta(days=1)

        try:
            forecast_slot = ForecastSlot(slot)
        except ValueError:
            logger.warning(
                f"Unknown slot '{slot}', falling back to 'mid'. "
                f"Valid options: {[s.value for s in ForecastSlot]}"
            )
            forecast_slot = ForecastSlot.MID

        try:
            setup = get_forecast_date_for_slot(
                question,
                slot=forecast_slot,
                db=self.db,
                min_context_items=0,
            )
            return setup["simulated_date"]
        except (ValueError, KeyError):
            # Fallback: use resolution_date - 1 day
            logger.warning(
                f"Could not compute slot-based date for question {question.id}, "
                "falling back to resolution_date - 1 day"
            )
            return question.resolution_date - timedelta(days=1)

    def _run_single(
        self,
        condition: ExperimentCondition,
        question: Question,
        model_name: str,
        knowledge_cutoff: str,
        slot: str = "mid",
    ) -> Dict[str, Any]:
        """Run a single (condition, model, question) triple.

        Returns:
            Dict with forecast result and evaluation metrics
        """
        from src.agents.forecast_agent import ForecastAgent

        simulated_date = self._compute_simulated_date(
            question, condition, slot
        )

        # Create config copy with overridden model
        config = deepcopy(self.config)
        config.llm.model = model_name

        # Get condition-specific prompt
        prompt = get_forecast_instructions(
            mode=condition.mode,
            enable_causal_tools=condition.enable_causal_tools,
            condition_name=condition.name.value,
        )

        # Create and run forecast agent
        agent = ForecastAgent(
            question=question,
            simulated_date=simulated_date.isoformat(),
            knowledge_cutoff=knowledge_cutoff,
            config=config,
            db_path=self.db_path,
            mode=condition.mode,
            enable_causal_tools=condition.enable_causal_tools,
            max_steps=condition.max_steps,
        )

        try:
            agent.run(prompt)
        except Exception as e:
            logger.error(
                f"Agent failed for {condition.name.value}/{model_name}/{question.id}: {e}"
            )
            return {
                "status": "error",
                "error": str(e),
                "question_id": question.id,
                "condition": condition.name.value,
                "model": model_name,
            }

        # Retrieve the forecast from DB
        forecasts = self.db.get_many(Forecast, filters={"question_id": question.id})
        if not forecasts:
            return {
                "status": "error",
                "error": "No forecast was created",
                "question_id": question.id,
                "condition": condition.name.value,
                "model": model_name,
            }

        latest_forecast = sorted(
            forecasts, key=lambda f: f.timestamp, reverse=True
        )[0]

        # Tag the forecast with benchmark metadata
        metadata = latest_forecast.evaluation_metadata or {}
        metadata["benchmark_condition"] = condition.name.value
        metadata["benchmark_model"] = model_name
        latest_forecast.evaluation_metadata = metadata
        self.db.save(Forecast, latest_forecast)

        # Evaluate the forecast
        evaluator = ForecastEvaluator(db_path=self.db_path)
        try:
            evaluation = evaluator.evaluate_forecast(latest_forecast, question)
            evaluator.update_forecast_with_evaluation(latest_forecast, evaluation)

            return {
                "status": "success",
                "question_id": question.id,
                "forecast_id": latest_forecast.id,
                "condition": condition.name.value,
                "model": model_name,
                "prediction": latest_forecast.prediction,
                "confidence": latest_forecast.confidence,
                "is_correct": evaluation.is_correct,
                "accuracy": evaluation.accuracy,
                "brier_score": evaluation.brier_score,
                "log_score": evaluation.log_score,
                "simulated_date": simulated_date.isoformat(),
            }
        except Exception as e:
            logger.error(f"Evaluation failed for forecast {latest_forecast.id}: {e}")
            return {
                "status": "error",
                "error": f"Evaluation failed: {e}",
                "question_id": question.id,
                "forecast_id": latest_forecast.id,
                "condition": condition.name.value,
                "model": model_name,
                "prediction": latest_forecast.prediction,
                "confidence": latest_forecast.confidence,
            }

    def _check_already_completed(
        self,
        condition: ExperimentCondition,
        question: Question,
        model_name: str,
    ) -> bool:
        """Check if a (condition, model, question) triple already has a forecast."""
        forecasts = self.db.get_many(Forecast, filters={"question_id": question.id})
        for f in forecasts:
            meta = f.evaluation_metadata or {}
            if (
                meta.get("benchmark_condition") == condition.name.value
                and meta.get("benchmark_model") == model_name
            ):
                return True
        return False

    @staticmethod
    def _aggregate_condition_metrics(
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate metrics from a list of individual results."""
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]

        if not successful:
            return {
                "total": len(results),
                "successful": 0,
                "failed": len(failed),
                "accuracy": 0.0,
                "avg_brier_score": None,
                "avg_log_score": None,
            }

        correct_count = sum(1 for r in successful if r.get("is_correct"))
        accuracy = correct_count / len(successful)

        brier_scores = [
            r["brier_score"] for r in successful if r.get("brier_score") is not None
        ]
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        log_scores = [
            r["log_score"] for r in successful if r.get("log_score") is not None
        ]
        avg_log = sum(log_scores) / len(log_scores) if log_scores else None

        return {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "accuracy": accuracy,
            "avg_brier_score": avg_brier,
            "avg_log_score": avg_log,
        }

    @staticmethod
    def _build_comparative_summary(
        condition_results: Dict[str, Dict[str, ConditionResult]],
    ) -> Dict[str, Any]:
        """Build a leaderboard comparing all (condition, model) pairs."""
        leaderboard = []
        for condition_name, model_results in condition_results.items():
            for model_name, result in model_results.items():
                leaderboard.append(
                    {
                        "condition": condition_name,
                        "display_name": result.display_name,
                        "model": model_name,
                        "accuracy": result.accuracy,
                        "avg_brier_score": result.avg_brier_score,
                        "avg_log_score": result.avg_log_score,
                        "successful": result.successful,
                        "total_questions": result.total_questions,
                    }
                )

        # Sort by accuracy (desc), then brier score (asc, lower is better)
        leaderboard.sort(
            key=lambda x: (-x["accuracy"], x["avg_brier_score"] or float("inf"))
        )

        return {"leaderboard": leaderboard}

    def run_auto_benchmark(
        self,
        questions: List[Question],
        models: List[str],
        conditions: Optional[List[ExperimentCondition]] = None,
        slot: str = "mid",
        on_progress: Optional[Callable[[AutoBenchmarkProgress], None]] = None,
        resume: bool = False,
    ) -> AutoBenchmarkResult:
        """Run the full auto-benchmark across all conditions, models, and questions.

        Args:
            questions: Questions to benchmark
            models: Model IDs to test
            conditions: Conditions to run (defaults to all 5)
            slot: Window position for simulated date — 'early' (20%), 'mid' (50%), 'late' (80%)
            on_progress: Progress callback
            resume: Skip already-completed triples

        Returns:
            AutoBenchmarkResult with all results and comparative summary
        """
        if conditions is None:
            conditions = get_conditions()

        start_time = time.time()
        run_id = f"autobench_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Calculate total work
        total_triples = len(conditions) * len(models) * len(questions)
        current_triple = 0

        # Accumulate results: condition_name -> model_name -> list of results
        raw_results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

        for ci, condition in enumerate(conditions):
            cond_name = condition.name.value
            if cond_name not in raw_results:
                raw_results[cond_name] = {}

            for mi, model_name in enumerate(models):
                if model_name not in raw_results[cond_name]:
                    raw_results[cond_name][model_name] = []

                knowledge_cutoff = get_knowledge_cutoff_date(model_name)

                for qi, question in enumerate(questions):
                    current_triple += 1

                    # Resume: skip completed triples
                    if resume and self._check_already_completed(
                        condition, question, model_name
                    ):
                        logger.info(
                            f"Skipping completed: {cond_name}/{model_name}/{question.id}"
                        )
                        # Still need to include in results for accurate counts
                        raw_results[cond_name][model_name].append({
                            "status": "success",
                            "question_id": question.id,
                            "condition": cond_name,
                            "model": model_name,
                            "is_correct": None,  # Will be filled from DB
                            "skipped_resume": True,
                        })
                        continue

                    # Report progress
                    if on_progress:
                        on_progress(
                            AutoBenchmarkProgress(
                                condition_index=ci + 1,
                                condition_total=len(conditions),
                                condition_name=condition.display_name,
                                model_index=mi + 1,
                                model_total=len(models),
                                model_name=model_name,
                                question_index=qi + 1,
                                question_total=len(questions),
                                question_id=question.id,
                                overall_current=current_triple,
                                overall_total=total_triples,
                            )
                        )

                    # Run the single benchmark
                    result = self._run_single(
                        condition=condition,
                        question=question,
                        model_name=model_name,
                        knowledge_cutoff=knowledge_cutoff,
                        slot=slot,
                    )
                    raw_results[cond_name][model_name].append(result)

        # Aggregate results
        condition_results: Dict[str, Dict[str, ConditionResult]] = {}
        for cond_name, model_results in raw_results.items():
            condition_results[cond_name] = {}
            condition = next(
                c for c in conditions if c.name.value == cond_name
            )
            for model_name, results_list in model_results.items():
                metrics = self._aggregate_condition_metrics(results_list)
                condition_results[cond_name][model_name] = ConditionResult(
                    condition_name=cond_name,
                    display_name=condition.display_name,
                    model_name=model_name,
                    total_questions=metrics["total"],
                    successful=metrics["successful"],
                    failed=metrics["failed"],
                    accuracy=metrics["accuracy"],
                    avg_brier_score=metrics["avg_brier_score"],
                    avg_log_score=metrics["avg_log_score"],
                    detailed_results=results_list,
                )

        # Build comparative summary
        comparative_summary = self._build_comparative_summary(condition_results)

        duration = time.time() - start_time

        benchmark_result = AutoBenchmarkResult(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_seconds=duration,
            configuration={
                "conditions": [c.name.value for c in conditions],
                "models": models,
                "question_count": len(questions),
                "slot": slot,
                "resume": resume,
            },
            condition_results=condition_results,
            comparative_summary=comparative_summary,
        )

        # Save results to file
        self._save_results(benchmark_result)

        return benchmark_result

    def _save_results(self, result: AutoBenchmarkResult) -> Path:
        """Save benchmark results to JSON file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{result.run_id}.json"

        # Convert to serializable dict
        output = {
            "auto_benchmark_info": {
                "run_id": result.run_id,
                "timestamp": result.timestamp,
                "duration_seconds": result.duration_seconds,
            },
            "configuration": result.configuration,
            "condition_results": {},
            "comparative_summary": result.comparative_summary,
        }

        for cond_name, model_results in result.condition_results.items():
            output["condition_results"][cond_name] = {}
            for model_name, cond_result in model_results.items():
                output["condition_results"][cond_name][model_name] = {
                    "display_name": cond_result.display_name,
                    "total_questions": cond_result.total_questions,
                    "successful": cond_result.successful,
                    "failed": cond_result.failed,
                    "accuracy": cond_result.accuracy,
                    "avg_brier_score": cond_result.avg_brier_score,
                    "avg_log_score": cond_result.avg_log_score,
                    "detailed_results": cond_result.detailed_results,
                }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)

        logger.info(f"Benchmark results saved to {output_path}")
        return output_path
