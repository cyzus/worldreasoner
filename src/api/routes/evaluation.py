"""API routes for forecast evaluation."""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

from src.core.database import GenericDatabase
from src.domain.evaluation.evaluator import ForecastEvaluator
from src.api.routes.database import get_current_db_path
from src.utils.logging import logger

router = APIRouter()


class EvaluationReportResponse(BaseModel):
    """Response with evaluation summary statistics."""

    total_forecasts: int
    overall_accuracy: float = 0.0
    avg_brier_score: Optional[float] = None
    avg_log_score: Optional[float] = None
    by_question_type: Dict[str, Any] = {}
    by_mode: Dict[str, Any] = {}
    calibration: Optional[Dict[str, Any]] = None
    model_info: Dict[str, Any] = {}
    evaluation_timestamp: str = ""
    message: Optional[str] = None
    # Reasoning graph metrics — populated after evaluate_reasoning_graphs.py runs
    reasoning_metrics: Dict[str, Optional[float]] = {}
    reasoning_metrics_n: int = 0


class RunEvaluationRequest(BaseModel):
    """Request to run batch evaluation."""

    update_forecasts: bool = True


@router.get("/report", response_model=EvaluationReportResponse)
async def get_evaluation_report():
    """Get current evaluation metrics."""
    try:
        db_path = get_current_db_path()
        evaluator = ForecastEvaluator(db_path)

        # We need to fetch all forecasts that HAVE been evaluated
        # The evaluator's generate_evaluation_report expects a list of EvaluationResult objects
        # But we can reconstruct them from the stored forecasts in DB

        from src.domain.models import Forecast, Question
        from src.domain.evaluation.evaluator import EvaluationResult

        db = GenericDatabase(db_path)
        forecasts = db.get_many(Forecast)

        # Filter for evaluated forecasts
        evaluated_forecasts = [f for f in forecasts if f.is_correct is not None]

        # Use only the most recent forecast per question per mode
        latest_forecasts_map = {}
        for f in evaluated_forecasts:
            # Handle mode being an object or string
            mode_val = f.mode.value if hasattr(f.mode, "value") else str(f.mode)
            key = (f.question_id, mode_val)

            if key not in latest_forecasts_map:
                latest_forecasts_map[key] = f
            else:
                if f.timestamp > latest_forecasts_map[key].timestamp:
                    latest_forecasts_map[key] = f

        # Use the filtered list for report generation
        final_forecasts = list(latest_forecasts_map.values())

        results = []
        for f in final_forecasts:
            # We need the question for ground truth and type
            question = db.get(Question, f.question_id)
            if not question:
                continue

            results.append(
                EvaluationResult(
                    forecast_id=f.id,
                    question_id=f.question_id,
                    is_correct=f.is_correct,
                    accuracy=1.0 if f.is_correct else 0.0,
                    brier_score=f.brier_score,
                    log_score=f.log_score,
                    prediction=f.prediction,
                    ground_truth=question.ground_truth,
                    confidence=f.confidence,
                    question_type=question.question_type.value,
                    evaluation_metadata=f.evaluation_metadata or {},
                )
            )

        report = evaluator.generate_evaluation_report(results)

        if "evaluation_timestamp" not in report:
            report["evaluation_timestamp"] = datetime.now().isoformat()

        # Aggregate reasoning graph metrics from evaluation_metadata.reasoning_eval
        # (written back by scripts/benchmark/evaluate_reasoning_graphs.py)
        import json as _json
        from statistics import mean as _mean

        REASONING_KEYS = [
            "event_f1", "event_recall", "event_precision",
            "accessible_event_f1", "exact_source_precision",
            "key_event_recall", "key_event_precision",
            "temporal_mae_days", "market_signal_recall",
            "edge_recall", "edge_precision",
        ]
        buckets: dict[str, list[float]] = {k: [] for k in REASONING_KEYS}
        for f in final_forecasts:
            try:
                meta = _json.loads(f.evaluation_metadata) if isinstance(f.evaluation_metadata, str) else (f.evaluation_metadata or {})
            except (ValueError, TypeError):
                meta = {}
            re = meta.get("reasoning_eval", {})
            for k in REASONING_KEYS:
                v = re.get(k)
                if isinstance(v, (int, float)) and v == v:  # exclude NaN
                    buckets[k].append(float(v))

        report["reasoning_metrics"] = {
            k: round(_mean(v), 4) if v else None
            for k, v in buckets.items()
        }
        report["reasoning_metrics_n"] = min((len(v) for v in buckets.values() if v), default=0)

        return report

    except Exception as e:
        logger.error(f"Error generating evaluation report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate evaluation report: {str(e)}"
        )


@router.post("/run")
async def run_evaluation(
    request: RunEvaluationRequest, background_tasks: BackgroundTasks
):
    """Trigger batch evaluation of all resolved questions."""

    def _run_evaluation_task(db_path: str, update: bool):
        try:
            logger.info(f"Starting background evaluation task on {db_path}")
            evaluator = ForecastEvaluator(db_path)
            results = evaluator.evaluate_all_resolved(update_forecasts=update)
            logger.info(
                f"Background evaluation complete: {len(results)} forecasts evaluated"
            )
        except Exception as e:
            logger.error(f"Error in background evaluation task: {e}", exc_info=True)

    db_path = get_current_db_path()
    background_tasks.add_task(_run_evaluation_task, db_path, request.update_forecasts)

    return {"message": "Evaluation task started in background"}
