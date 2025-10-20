"""Pipeline infrastructure for WorldReasoner.

Provides base classes and utilities for building data processing pipelines.
"""

from .base import (
    Pipeline,
    PipelineStage,
    PipelineStageResult,
    PipelineStageStatus,
)

# Import specific pipelines
from .question.pipeline import QuestionPipeline

# Re-export stages for convenience
from .stages import *

__all__ = [
    # Base classes
    "Pipeline",
    "PipelineStage",
    "PipelineStageResult",
    "PipelineStageStatus",
    # Pipelines
    "QuestionPipeline",
]
