"""Auto-benchmark service for running ablation study experiments.

Orchestrates running all experimental conditions x models x questions,
producing comparative results for the research paper.
"""

import asyncio
import gc
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.config import Config, get_config
from src.core.database import GenericDatabase
from src.domain.evaluation.conditions import (
    ExperimentCondition,
    get_conditions,
)
from src.domain.evaluation.evaluator import ForecastEvaluator
from src.domain.models import Forecast, Question
from src.domain.models.question_helpers import (
    ForecastSlot,
    get_forecast_date_for_slot,
)
from src.pipelines.prompts.forecast import get_forecast_instructions
from src.core.llm import get_knowledge_cutoff_date
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
        max_questions: Optional[int] = None,
        source: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[Question]:
        """Get resolved questions suitable for benchmarking.

        Args:
            question_ids: If provided, only these questions (must be resolved)
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
                    logger.warning(
                        f"Question {qid} not found or not resolved, skipping"
                    )
        else:
            all_questions = self.db.get_many(Question)
            now = datetime.now(timezone.utc)
            questions = [
                q
                for q in all_questions
                if q.ground_truth is not None
                and q.resolution_date is not None
                and q.resolution_date <= now
                and q.graph_built
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

        # Filter by evidence satisfaction — same logic as frontend (QuestionMonitorService)
        from src.services.question_monitor_service import QuestionMonitorService

        monitor = QuestionMonitorService(self.db)
        satisfied_ids = monitor.get_processed_question_ids(questions)
        before_count = len(questions)
        questions = [q for q in questions if q.id in satisfied_ids]
        filtered_count = before_count - len(questions)
        if filtered_count > 0:
            logger.info(
                f"Filtered {filtered_count} questions without satisfied evidence "
                f"({len(questions)} remaining)"
            )

        questions = sorted(questions, key=lambda q: q.id)

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
            setup = get_forecast_date_for_slot(question, slot=forecast_slot)
            return setup["simulated_date"]
        except (ValueError, KeyError):
            # Fallback: use resolution_date - 1 day
            logger.warning(
                f"Could not compute slot-based date for question {question.id}, "
                "falling back to resolution_date - 1 day"
            )
            return question.resolution_date - timedelta(days=1)

    @staticmethod
    def _close_mcp_client(agent: Any) -> None:
        """Close a ForecastAgent MCP client and drain Windows pipe transports."""
        mcp_client = getattr(agent, "mcp_client", None)
        adapter = getattr(mcp_client, "_adapter", None)
        if adapter is None:
            return

        try:
            if adapter.task and not adapter.task.done():
                adapter.loop.call_soon_threadsafe(adapter.task.cancel)
            adapter.thread.join(timeout=15)
            if not adapter.loop.is_closed():
                adapter.loop.run_until_complete(adapter.loop.shutdown_asyncgens())
                # Force GC so Proactor pipe transport __del__ runs while the loop
                # is still open; the sleep then drains any resulting callbacks.
                gc.collect()
                adapter.loop.run_until_complete(asyncio.sleep(0))
                adapter.loop.close()
        except Exception as e:
            logger.warning(f"Failed to close MCP client cleanly: {e}")

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

        simulated_date = self._compute_simulated_date(question, condition, slot)

        # Create config copy with overridden model
        config = deepcopy(self.config)
        config.llm.model = model_name

        # Get condition-specific prompt with question embedded (saves one agent step)
        prompt = get_forecast_instructions(
            mode=condition.mode,
            enable_causal_tools=condition.enable_causal_tools,
            condition_name=condition.name.value,
            question=question,
        )

        # Create and run forecast agent
        agent = None
        try:
            agent = ForecastAgent(
                question=question,
                simulated_date=simulated_date.isoformat(),
                knowledge_cutoff=knowledge_cutoff,
                config=config,
                db_path=self.db_path,
                mode=condition.mode,
                enable_causal_tools=condition.enable_causal_tools,
                max_steps=condition.max_steps,
                benchmark_condition=condition.name.value,
            )
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
        finally:
            if agent is not None:
                self._close_mcp_client(agent)

        # Retrieve the forecast from DB by session_id (safe under parallel execution)
        forecasts = self.db.get_many(Forecast, filters={"session_id": agent.session_id})
        if not forecasts:
            return {
                "status": "error",
                "error": "No forecast was created",
                "question_id": question.id,
                "condition": condition.name.value,
                "model": model_name,
            }

        latest_forecast = forecasts[0]

        # Tag the forecast with the slot label before evaluation is persisted
        existing_meta = latest_forecast.evaluation_metadata or {}
        latest_forecast.evaluation_metadata = {**existing_meta, "slot": slot}

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
    def _load_json_cell(value: Any) -> Any:
        """Decode JSON cells from direct sqlite reads, falling back to raw value."""
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    @staticmethod
    def _resume_result_from_row(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        """Convert an evaluated forecast DB row into a benchmark result."""
        meta = AutoBenchmarkService._load_json_cell(row["evaluation_metadata"]) or {}
        condition = meta.get("benchmark_condition")
        model = meta.get("benchmark_model")
        if not condition or not model or row["is_correct"] is None:
            return None

        return {
            "status": "success",
            "question_id": row["question_id"],
            "forecast_id": row["id"],
            "condition": condition,
            "model": model,
            "slot": meta.get("slot", "mid"),
            "prediction": AutoBenchmarkService._load_json_cell(row["prediction"]),
            "confidence": row["confidence"],
            "is_correct": bool(row["is_correct"]),
            "accuracy": 1.0 if bool(row["is_correct"]) else 0.0,
            "brier_score": row["brier_score"],
            "log_score": row["log_score"],
            "simulated_date": row["simulated_date"],
            "skipped_resume": True,
        }

    def _load_completed_resume_results(
        self,
    ) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
        """Load latest evaluated benchmark forecasts for resume aggregation."""
        completed: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        latest_timestamps: Dict[Tuple[str, str, str], str] = {}

        conn = sqlite3.connect(str(self.db.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, question_id, prediction, confidence, is_correct, "
                "brier_score, log_score, simulated_date, timestamp, "
                "evaluation_metadata FROM forecasts "
                "WHERE evaluation_metadata IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            result = self._resume_result_from_row(row)
            if result is None:
                continue
            key = (result["question_id"], result["condition"], result["model"], result["slot"])
            timestamp = row["timestamp"] or ""
            if key not in completed or timestamp > latest_timestamps[key]:
                completed[key] = result
                latest_timestamps[key] = timestamp

        return completed

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
        max_workers: int = 4,
    ) -> AutoBenchmarkResult:
        """Run the full auto-benchmark across all conditions, models, and questions.

        Args:
            questions: Questions to benchmark
            models: Model IDs to test
            conditions: Conditions to run (defaults to all 5)
            slot: Window position for simulated date — 'early' (20%), 'mid' (50%), 'late' (80%)
            on_progress: Progress callback
            resume: Skip already-completed triples
            max_workers: Number of parallel workers (default 4)

        Returns:
            AutoBenchmarkResult with all results and comparative summary
        """
        if conditions is None:
            conditions = get_conditions()

        start_time = time.time()
        run_id = f"autobench_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Build all (condition, model, question) triples
        triples = [
            (ci, condition, mi, model_name, qi, question)
            for ci, condition in enumerate(conditions)
            for mi, model_name in enumerate(models)
            for qi, question in enumerate(questions)
        ]
        total_triples = len(triples)

        # Accumulate results: condition_name -> model_name -> list of results
        raw_results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for condition in conditions:
            raw_results[condition.name.value] = {m: [] for m in models}

        # Pre-fetch completed triples and their stored metrics so resumed runs
        # preserve prior scores in the aggregate instead of counting skipped
        # triples as successes with unknown correctness.
        completed_results: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        if resume:
            completed_results = self._load_completed_resume_results()
            logger.info(
                f"Resume: found {len(completed_results)} already-evaluated triples"
            )

        completed_count = 0

        def _run_triple(args):
            ci, condition, mi, model_name, qi, question = args
            cond_name = condition.name.value
            knowledge_cutoff = get_knowledge_cutoff_date(model_name)

            # Resume from pre-fetched results without a DB query per triple.
            resume_key = (question.id, cond_name, model_name, slot)
            if resume and resume_key in completed_results:
                logger.info(
                    f"Skipping completed: {cond_name}/{model_name}/{question.id}"
                )
                return (
                    ci,
                    condition,
                    mi,
                    model_name,
                    qi,
                    question,
                    cond_name,
                    model_name,
                    completed_results[resume_key],
                )

            result = self._run_single(
                condition=condition,
                question=question,
                model_name=model_name,
                knowledge_cutoff=knowledge_cutoff,
                slot=slot,
            )
            return (
                ci,
                condition,
                mi,
                model_name,
                qi,
                question,
                cond_name,
                model_name,
                result,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_triple, t): t for t in triples}
            for future in as_completed(futures):
                completed_count += 1
                try:
                    (
                        ci,
                        condition,
                        mi,
                        model_name,
                        qi,
                        question,
                        cond_name,
                        mn,
                        result,
                    ) = future.result()
                    raw_results[cond_name][mn].append(result)
                    if on_progress:
                        on_progress(AutoBenchmarkProgress(
                            condition_index=ci + 1,
                            condition_total=len(conditions),
                            condition_name=condition.display_name,
                            model_index=mi + 1,
                            model_total=len(models),
                            model_name=mn,
                            question_index=qi + 1,
                            question_total=len(questions),
                            question_id=question.id,
                            overall_current=completed_count,
                            overall_total=total_triples,
                        ))
                except Exception as e:
                    ci, condition, mi, model_name, qi, question = futures[future]
                    logger.error(f"Triple failed: {condition.name.value}/{model_name}/{question.id}: {e}")
                    raw_results[condition.name.value][model_name].append({
                        "status": "error",
                        "error": str(e),
                        "question_id": question.id,
                        "condition": condition.name.value,
                        "model": model_name,
                    })
                    if on_progress:
                        on_progress(AutoBenchmarkProgress(
                            condition_index=ci + 1,
                            condition_total=len(conditions),
                            condition_name=condition.display_name,
                            model_index=mi + 1,
                            model_total=len(models),
                            model_name=model_name,
                            question_index=qi + 1,
                            question_total=len(questions),
                            question_id=question.id,
                            overall_current=completed_count,
                            overall_total=total_triples,
                        ))

        # Aggregate results
        condition_results: Dict[str, Dict[str, ConditionResult]] = {}
        for cond_name, model_results in raw_results.items():
            condition_results[cond_name] = {}
            condition = next(c for c in conditions if c.name.value == cond_name)
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
