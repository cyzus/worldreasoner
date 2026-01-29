"""Abstract base classes for data pipeline stages."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Generic, TypeVar, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from enum import Enum

from src.utils.usage_tracking import UsageTracker, log_usage


TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


class PipelineStageStatus(str, Enum):
    """Status of a pipeline stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStageResult(BaseModel, Generic[TOutput]):
    """Result from a pipeline stage execution.

    Generic type parameter TOutput allows type-safe storage of stage outputs.
    """

    model_config = {"arbitrary_types_allowed": True}

    stage_name: str
    status: PipelineStageStatus
    items_processed: int = 0
    items_output: int = 0
    outputs: List[TOutput] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def duration_seconds(self) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


class PipelineStage(ABC, Generic[TInput, TOutput]):
    """Abstract base class for a pipeline stage with built-in usage tracking."""

    def __init__(
        self, name: str, config: Optional[BaseModel] = None, track_usage: bool = True
    ):
        """Initialize pipeline stage.

        Args:
            name: Name of the stage
            config: Optional configuration for the stage
            track_usage: Whether to enable usage tracking (default: True)
        """
        self.name = name
        self.config = config
        self.track_usage = track_usage
        self._result: Optional[PipelineStageResult] = None

        if track_usage:
            self._usage_tracker = UsageTracker()

    @abstractmethod
    async def process(self, inputs: List[TInput]) -> List[TOutput]:
        """Process inputs and produce outputs.

        Args:
            inputs: List of input items to process

        Returns:
            List of output items
        """
        pass

    async def process_batch(
        self, inputs: List[TInput], batch_size: int
    ) -> List[TOutput]:
        """Process inputs in batches to handle large datasets.

        Args:
            inputs: List of input items to process
            batch_size: Maximum items per batch

        Returns:
            List of all output items from all batches
        """
        if not inputs:
            return []

        if batch_size <= 0:
            # No batching, process all at once
            return await self.process(inputs)

        all_outputs = []

        # Process in batches
        for i in range(0, len(inputs), batch_size):
            batch = inputs[i : i + batch_size]

            try:
                batch_outputs = await self.process(batch)
                all_outputs.extend(batch_outputs)
            except Exception as e:
                # Log error but continue with other batches
                print(f"Error processing batch {i // batch_size + 1}: {e}")
                continue

        return all_outputs

    async def execute_batched(
        self, inputs: List[TInput], batch_size: int
    ) -> PipelineStageResult[TOutput]:
        """Execute the stage with batching for large datasets.

        Args:
            inputs: List of input items to process
            batch_size: Maximum items per batch

        Returns:
            PipelineStageResult with aggregated execution metadata and outputs
        """
        started_at = datetime.now(timezone.utc)
        status = PipelineStageStatus.RUNNING
        error_message = None

        try:
            # Process in batches
            all_outputs = await self.process_batch(inputs, batch_size)

            status = PipelineStageStatus.COMPLETED

        except Exception as e:
            status = PipelineStageStatus.FAILED
            all_outputs = []
            error_message = str(e)

        completed_at = datetime.now(timezone.utc)

        result = PipelineStageResult[TOutput](
            stage_name=self.name,
            status=status,
            items_processed=len(inputs),
            items_output=len(all_outputs),
            outputs=all_outputs,
            started_at=started_at,
            completed_at=completed_at,
            error_message=error_message,
        )

        self._result = result
        return result

    async def execute(self, inputs: List[TInput]) -> PipelineStageResult[TOutput]:
        """Execute the stage with error handling and metrics.

        Args:
            inputs: List of input items to process

        Returns:
            PipelineStageResult with execution metadata and outputs
        """
        result = PipelineStageResult[TOutput](
            stage_name=self.name,
            status=PipelineStageStatus.RUNNING,
            items_processed=len(inputs),
            started_at=datetime.now(timezone.utc),
        )

        try:
            outputs = await self.process(inputs)
            result.status = PipelineStageStatus.COMPLETED
            result.items_output = len(outputs)
            result.outputs = outputs
            result.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            result.status = PipelineStageStatus.FAILED
            result.error_message = str(e)
            result.completed_at = datetime.now(timezone.utc)
            raise
        finally:
            self._result = result

        return result

    def get_result(self) -> Optional[PipelineStageResult]:
        """Get the last execution result."""
        return self._result

    def track_agent_usage(self, agent) -> None:
        """Track usage from agent execution.

        Args:
            agent: Agent instance after execution
        """
        if not self.track_usage:
            return

        metrics = agent.get_last_usage()
        if metrics:
            self._usage_tracker.add_usage(metrics)
            log_usage(metrics, context=self.name)

    def finalize_usage_tracking(self) -> None:
        """Log final usage summary."""
        if self.track_usage and self._usage_tracker.total_calls > 0:
            self._usage_tracker.log_summary(context=self.name)


class Pipeline(ABC):
    """Abstract base class for a data pipeline."""

    def __init__(self, name: str):
        """Initialize pipeline.

        Args:
            name: Name of the pipeline
        """
        self.name = name
        self.stages: List[PipelineStage] = []
        self._results: List[PipelineStageResult] = []

    def add_stage(self, stage: PipelineStage) -> None:
        """Add a stage to the pipeline.

        Args:
            stage: Pipeline stage to add
        """
        self.stages.append(stage)

    @abstractmethod
    async def run(self) -> List[PipelineStageResult]:
        """Run the pipeline.

        Returns:
            List of results from each stage
        """
        pass

    def get_results(self) -> List[PipelineStageResult]:
        """Get results from all stages."""
        return self._results

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of pipeline execution.

        Returns:
            Dictionary with execution summary
        """
        total_duration = sum(r.duration_seconds() or 0 for r in self._results)

        return {
            "pipeline_name": self.name,
            "total_stages": len(self.stages),
            "completed_stages": sum(
                1 for r in self._results if r.status == PipelineStageStatus.COMPLETED
            ),
            "failed_stages": sum(
                1 for r in self._results if r.status == PipelineStageStatus.FAILED
            ),
            "total_duration_seconds": total_duration,
            "stage_results": [
                {
                    "name": r.stage_name,
                    "status": r.status,
                    "items_processed": r.items_processed,
                    "items_output": r.items_output,
                    "duration_seconds": r.duration_seconds(),
                }
                for r in self._results
            ],
        }
