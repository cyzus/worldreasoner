"""Pipeline execution API routes.

Provides endpoints for running pipelines in the background with progress tracking.
"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    WebSocket,
    HTTPException,
    WebSocketDisconnect,
)
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum
import asyncio
import uuid
from datetime import datetime

from src.core.database import GenericDatabase
from src.utils.logging import logger
from src.api.routes.database import get_current_db_path

router = APIRouter()

# Import unified pipeline types
from src.pipelines.types import PipelineType

# ============================================================================
# Models
# ============================================================================


class JobStatus(str, Enum):
    """Pipeline job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineJobRequest(BaseModel):
    """Request to start a pipeline job."""

    question_ids: List[str] = []
    pipeline_type: PipelineType
    config: Dict[str, Any] = {}


class PipelineJobResponse(BaseModel):
    """Pipeline job status response."""

    job_id: str
    status: JobStatus
    pipeline_type: PipelineType
    progress: float  # 0.0 to 1.0
    current_question: Optional[str] = None
    question_ids: List[str] = []  # Added field
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
    # Check for duplicate jobs
    request_qids_set = set(request.question_ids)
    for existing_job in jobs.values():
        if existing_job.status in [JobStatus.PENDING, JobStatus.RUNNING]:
            if existing_job.pipeline_type == request.pipeline_type:
                # For jobs without question_ids (e.g. auto_benchmark), just check type
                if not request.question_ids and not existing_job.question_ids:
                    logger.warning(
                        f"Duplicate job attempt blocked: {existing_job.job_id} already running"
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=f"Similar job {existing_job.job_id} is already {existing_job.status.value}",
                    )
                # Check for same set of questions
                elif set(existing_job.question_ids) == request_qids_set:
                    logger.warning(
                        f"Duplicate job attempt blocked: {existing_job.job_id} already processing these questions"
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=f"Similar job {existing_job.job_id} is already {existing_job.status.value}",
                    )

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    job = PipelineJobResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        pipeline_type=request.pipeline_type,
        progress=0.0,
        question_ids=request.question_ids,  # Populate field
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

    logger.info(
        f"Created pipeline job {job_id} for {len(request.question_ids)} questions"
    )
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
            detail=f"Job {job_id} is still {job.status.value}. Wait for completion.",
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

            if job.status in [
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ]:
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
    from src.services.question_service import QuestionService

    db = GenericDatabase(get_current_db_path())
    service = QuestionService(db)

    results = {
        "cleared": [],
        "failed": [],
    }

    for qid in request.question_ids:
        try:
            service.clear_evidence(qid, cascade=request.cascade)
            results["cleared"].append(qid)
        except Exception as e:
            results["failed"].append({"id": qid, "error": str(e)})

    return results


@router.post("/questions/clear-graph")
async def clear_questions_graph(request: ClearEvidenceRequest):
    """Clear only graph data (events, hypotheses) for questions, keeping articles and explanation."""
    db_path = get_current_db_path()
    db = GenericDatabase(db_path)
    from src.services.question_service import QuestionService

    service = QuestionService(db)
    results = {"cleared": [], "failed": []}

    for qid in request.question_ids:
        try:
            service.clear_graph(qid)
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
        from src.pipelines.executor import PipelineExecutor
        from src.config import get_config

        executor = PipelineExecutor(get_config(), db_path=get_current_db_path())

        # Progress callback
        def on_progress(progress):
            job.current_question = progress.question_id
            job.processed_count = progress.current
            # Update total_count if provided in progress (crucial for collection jobs where initial count is 0)
            if progress.total > 0:
                job.total_count = progress.total
            job.progress = (
                progress.current / progress.total if progress.total > 0 else 0.0
            )
            job.message = progress.message
            job.updated_at = datetime.utcnow().isoformat()

        # Execute pipeline
        result = await executor.execute(
            pipeline_type,
            question_ids,
            on_progress=on_progress,
            **config,
        )
        
        # In decoupled V2 architecture, Evidence pipeline only extracts NL explanations.
        # If we successfully ran the evidence pipeline, we should automatically trigger 
        # the graph builder pipeline to build the structured graph.
        if pipeline_type == PipelineType.EVIDENCE and len(result.processed) > 0:
            job.message = f"Building graphs for {len(result.processed)} questions..."
            job.updated_at = datetime.utcnow().isoformat()
            try:
                from src.pipelines.graph_builder.pipeline import GraphBuilderPipeline
                from src.config import get_config
                from src.core.database import GenericDatabase
                from src.domain.models import Question

                db_path = get_current_db_path()
                graph_pipeline = GraphBuilderPipeline(
                    db_path=db_path,
                    model_id=get_config().llm.model,
                )
                db = GenericDatabase(db_path)
                
                graph_success = 0
                for item in result.processed:
                    q = db.get(Question, item["id"])
                    if q and q.causal_explanation:
                        success = graph_pipeline._process_single_question(q)
                        if success:
                            graph_success += 1
                            
                job.results["graphs_built"] = graph_success
                
            except Exception as e:
                logger.error(f"Auto graph builder failed: {e}")
                # Don't fail the job if just the graph building failed, 
                # they still got the evidence explanation.

        # Determine job status based on results
        # Determine job status based on results
        if len(result.failed) > 0 and len(result.processed) == 0:
            # All attempts failed (or no results generated despite errors)
            job.status = JobStatus.FAILED
            job.message = "All items failed to process"
        elif len(result.failed) > 0:
            # Some failures but some success
            job.status = JobStatus.COMPLETED
            job.message = f"Completed with {len(result.failed)} failures"
        else:
            # All succeeded (or at least no recorded failures)
            job.status = JobStatus.COMPLETED
            job.message = f"Successfully processed {len(result.processed)} items"

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
