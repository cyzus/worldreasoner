"""Abstract base classes for data pipeline stages."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Generic, TypeVar, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from enum import Enum


TInput = TypeVar('TInput')
TOutput = TypeVar('TOutput')


class PipelineStageStatus(str, Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStageResult(BaseModel):
    """Result from a pipeline stage execution."""
    stage_name: str
    status: PipelineStageStatus
    items_processed: int = 0
    items_output: int = 0
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
    """Abstract base class for a pipeline stage."""
    
    def __init__(self, name: str, config: Optional[BaseModel] = None):
        """Initialize pipeline stage.
        
        Args:
            name: Name of the stage
            config: Optional configuration for the stage
        """
        self.name = name
        self.config = config
        self._result: Optional[PipelineStageResult] = None
    
    @abstractmethod
    async def process(self, inputs: List[TInput]) -> List[TOutput]:
        """Process inputs and produce outputs.
        
        Args:
            inputs: List of input items to process
            
        Returns:
            List of output items
        """
        pass
    
    async def execute(self, inputs: List[TInput]) -> PipelineStageResult:
        """Execute the stage with error handling and metrics.
        
        Args:
            inputs: List of input items to process
            
        Returns:
            PipelineStageResult with execution metadata
        """
        result = PipelineStageResult(
            stage_name=self.name,
            status=PipelineStageStatus.RUNNING,
            items_processed=len(inputs),
            started_at=datetime.now(timezone.utc)
        )
        
        try:
            outputs = await self.process(inputs)
            result.status = PipelineStageStatus.COMPLETED
            result.items_output = len(outputs)
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
        total_duration = sum(
            r.duration_seconds() or 0 
            for r in self._results
        )
        
        return {
            "pipeline_name": self.name,
            "total_stages": len(self.stages),
            "completed_stages": sum(
                1 for r in self._results 
                if r.status == PipelineStageStatus.COMPLETED
            ),
            "failed_stages": sum(
                1 for r in self._results 
                if r.status == PipelineStageStatus.FAILED
            ),
            "total_duration_seconds": total_duration,
            "stage_results": [
                {
                    "name": r.stage_name,
                    "status": r.status,
                    "items_processed": r.items_processed,
                    "items_output": r.items_output,
                    "duration_seconds": r.duration_seconds()
                }
                for r in self._results
            ]
        }
