"""Question monitoring API endpoints.

Provides REST API for monitoring question status for evidence and forecasting.
"""

from typing import Optional
from dataclasses import asdict
from fastapi import APIRouter, Query, HTTPException, Depends

from src.core.database import GenericDatabase
from src.config import get_config
from src.services.question_monitor_service import QuestionMonitorService
from .database import get_current_db_path

router = APIRouter()


def get_database():
    """Dependency to get database instance."""
    return GenericDatabase(get_current_db_path())


def get_monitor_service(
    db: GenericDatabase = Depends(get_database),
) -> QuestionMonitorService:
    """Dependency to get monitor service instance."""
    return QuestionMonitorService(db)


@router.get("/evidence-needs")
async def get_evidence_needs(
    min_quality: Optional[float] = Query(None, description="Minimum quality score"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    service: QuestionMonitorService = Depends(get_monitor_service),
):
    """Get questions that need evidence collection.

    Returns questions that are resolved, not skipped, and don't have
    sufficient evidence yet.
    """
    questions = service.get_evidence_needs(
        min_quality_score=min_quality, domain=domain, limit=limit
    )

    return {
        "success": True,
        "count": len(questions),
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "domain": q.domain.value
                if hasattr(q.domain, "value")
                else str(q.domain),
                "quality_score": q.quality_score,
                "resolution_date": q.resolution_date.isoformat()
                if q.resolution_date
                else None,
            }
            for q in questions
        ],
    }


@router.get("/questions/{question_id}/satisfaction")
async def get_satisfaction(
    question_id: str,
    service: QuestionMonitorService = Depends(get_monitor_service),
):
    """Check evidence satisfaction status for a question.

    Returns whether the question has sufficient evidence for forecasting
    and details about what requirements are met/missing.
    """
    try:
        satisfaction = service.check_satisfaction(question_id)
        return {"success": True, **asdict(satisfaction)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/questions/{question_id}/forecast-readiness")
async def get_forecast_readiness(
    question_id: str,
    service: QuestionMonitorService = Depends(get_monitor_service),
):
    """Get forecast readiness and available modes for a question.

    Returns available forecast modes based on evidence status and
    temporal constraints, plus recommended mode and tool configuration.
    """
    try:
        readiness = service.get_forecast_readiness(question_id)
        return {
            "success": True,
            "available_modes": [m.value for m in readiness.available_modes],
            "recommended_mode": readiness.recommended_mode.value,
            "tool_config": {
                mode: asdict(config) for mode, config in readiness.tool_config.items()
            },
            "evidence_status": asdict(readiness.evidence_status),
            "temporal_status": readiness.temporal_status,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-stats")
async def get_model_stats(
    model_name: Optional[str] = Query(None, description="Filter to specific model"),
    service: QuestionMonitorService = Depends(get_monitor_service),
):
    """Get LLM model usage statistics from forecasts.

    Returns forecast counts, accuracy, and average confidence per model.
    """
    stats = service.get_model_usage_stats(model_name=model_name)

    return {"success": True, "count": len(stats), "models": [asdict(s) for s in stats]}
