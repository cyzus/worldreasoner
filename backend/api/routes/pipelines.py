"""Pipeline execution API routes.

Provides endpoints for running pipelines in the background with progress tracking.
"""
from fastapi import APIRouter, BackgroundTasks, WebSocket, HTTPException, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum
import asyncio
import uuid
from datetime import datetime

from src.core.database import GenericDatabase
from src.utils.logging import logger
from backend.api.routes.database import get_current_db_path

router = APIRouter()

# ============================================================================
# Models
# ============================================================================

class PipelineType(str, Enum):
    """Available pipeline types."""
    EVIDENCE = "evidence"
    ADAPTIVE_EVIDENCE = "adaptive_evidence"
    FORECAST = "forecast"
    EVALUATION = "evaluation"
    BENCHMARK = "benchmark"

class JobStatus(str, Enum):
    """Pipeline job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PipelineJobRequest(BaseModel):
    """Request to start a pipeline job."""
    question_ids: List[str]
    pipeline_type: PipelineType
    config: Dict[str, Any] = {}

class PipelineJobResponse(BaseModel):
    """Pipeline job status response."""
    job_id: str
    status: JobStatus
    pipeline_type: PipelineType
    progress: float  # 0.0 to 1.0
    current_question: Optional[str] = None
    processed_count: int = 0
    total_count: int = 0
    message: str = ""
    results: Dict[str, Any] = {}
    created_at: str
    updated_at: str

class ClearEvidenceRequest(BaseModel):
    """Request to clear evidence for questions."""
    question_ids: List[str]
    cascade: bool = True

# ============================================================================
# In-Memory Job Store (use Redis for production)
# ============================================================================

jobs: Dict[str, PipelineJobResponse] = {}

# ============================================================================
# Endpoints
# ============================================================================

@router.post("/jobs", response_model=PipelineJobResponse)
async def create_pipeline_job(
    request: PipelineJobRequest,
    background_tasks: BackgroundTasks,
):
    """Start a new pipeline job.

    The job runs in the background. Use GET /jobs/{job_id} or
    WebSocket /jobs/{job_id}/ws to monitor progress.
    """
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    job = PipelineJobResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        pipeline_type=request.pipeline_type,
        progress=0.0,
        total_count=len(request.question_ids),
        message="Job created, waiting to start",
        created_at=now,
        updated_at=now,
    )
    jobs[job_id] = job

    # Run pipeline in background
    background_tasks.add_task(
        run_pipeline_job,
        job_id,
        request.question_ids,
        request.pipeline_type,
        request.config,
    )

    logger.info(f"Created pipeline job {job_id} for {len(request.question_ids)} questions")
    return job

@router.get("/jobs/{job_id}", response_model=PipelineJobResponse)
async def get_job_status(job_id: str):
    """Get current status of a pipeline job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return jobs[job_id]

@router.get("/jobs/{job_id}/results")
async def get_job_results(job_id: str):
    """Get the results of a completed pipeline job.
    
    Returns the results field from the job, which includes:
    - processed: list of successfully processed question IDs
    - failed: list of failed questions with error details
    - skipped: list of skipped questions
    - duration_seconds: total execution time
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    if job.status == JobStatus.PENDING or job.status == JobStatus.RUNNING:
        raise HTTPException(
            status_code=400, 
            detail=f"Job {job_id} is still {job.status.value}. Wait for completion."
        )
    
    return job.results

@router.get("/jobs", response_model=List[PipelineJobResponse])
async def list_jobs(
    status: Optional[JobStatus] = None,
    limit: int = 20,
):
    """List recent pipeline jobs."""
    job_list = list(jobs.values())

    if status:
        job_list = [j for j in job_list if j.status == status]

    # Sort by created_at descending
    job_list.sort(key=lambda j: j.created_at, reverse=True)

    return job_list[:limit]

@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs[job_id]
    if job.status == JobStatus.RUNNING:
        job.status = JobStatus.CANCELLED
        job.message = "Job cancelled by user"
        job.updated_at = datetime.utcnow().isoformat()

    return {"status": "cancelled", "job_id": job_id}

@router.websocket("/jobs/{job_id}/ws")
async def job_progress_websocket(websocket: WebSocket, job_id: str):
    """WebSocket for real-time job progress updates.

    Connect to receive JSON updates as the job progresses.
    Connection closes when job completes or fails.
    """
    await websocket.accept()

    try:
        while True:
            if job_id not in jobs:
                await websocket.send_json({"error": "Job not found"})
                break

            job = jobs[job_id]
            await websocket.send_json(job.dict())

            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass

@router.post("/questions/clear-evidence")
async def clear_questions_evidence(request: ClearEvidenceRequest):
    """Clear evidence data for multiple questions.

    This removes causal hypotheses and optionally cascades to orphaned events.
    """
    from src.cli.core.question_manager import QuestionManager

    db = GenericDatabase(get_current_db_path())
    manager = QuestionManager(db)

    results = {
        "cleared": [],
        "failed": [],
    }

    for qid in request.question_ids:
        try:
            manager.clear_evidence_simple(qid, cascade=request.cascade)
            results["cleared"].append(qid)
        except Exception as e:
            results["failed"].append({"id": qid, "error": str(e)})

    return results

# ============================================================================
# Background Task Runner
# ============================================================================

async def run_pipeline_job(
    job_id: str,
    question_ids: List[str],
    pipeline_type: PipelineType,
    config: Dict[str, Any],
):
    """Execute pipeline job in background."""
    job = jobs[job_id]
    job.status = JobStatus.RUNNING
    job.message = "Starting pipeline"
    job.updated_at = datetime.utcnow().isoformat()

    try:
        from src.cli.core.pipeline_runner import PipelineRunner
        from src.cli.core.pipeline_runner import PipelineType as RunnerPipelineType

        runner = PipelineRunner(db_path=get_current_db_path())

        # Progress callback
        def on_progress(progress):
            job.current_question = progress.question_id
            job.processed_count = progress.current
            job.progress = progress.current / progress.total if progress.total > 0 else 0.0
            job.message = progress.message
            job.updated_at = datetime.utcnow().isoformat()

        # Map pipeline type
        runner_type = RunnerPipelineType(pipeline_type.value)

        # Run pipeline
        result = await runner.run(
            runner_type,
            question_ids,
            on_progress=on_progress,
            **config,
        )

        # Determine job status based on results
        if len(result.failed) == len(question_ids):
            # All questions failed
            job.status = JobStatus.FAILED
            job.message = "All questions failed to process"
        elif len(result.failed) > 0:
            # Some failures
            job.status = JobStatus.COMPLETED
            job.message = f"Completed with {len(result.failed)} failures"
        else:
            # All succeeded
            job.status = JobStatus.COMPLETED
            job.message = f"Successfully processed {len(result.processed)} questions"

        job.progress = 1.0
        job.results = {
            "processed": len(result.processed),
            "failed": len(result.failed),
            "skipped": len(result.skipped),
            "duration_seconds": result.duration_seconds,
            "failed_details": result.failed,  # Include error details
            "processed_details": result.processed,
            "skipped_details": result.skipped,
        }

    except Exception as e:
        logger.error(f"Pipeline job {job_id} failed: {e}")
        job.status = JobStatus.FAILED
        job.message = str(e)
        job.results = {"error": str(e)}

    job.updated_at = datetime.utcnow().isoformat()
