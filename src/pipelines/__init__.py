"""Pipeline infrastructure for WorldReasoner.

Provides base classes and utilities for building data processing pipelines.
"""

from .base import (
    Pipeline,
    PipelineStage,
    PipelineStageResult,
    PipelineStageStatus,
)

__all__ = [
    # Base classes
    "Pipeline",
    "PipelineStage",
    "PipelineStageResult",
    "PipelineStageStatus",
]
