"""Pipeline infrastructure for WorldReasoner.

Provides base classes and utilities for building data processing pipelines.
"""

from .base import (
    Pipeline,
    PipelineStage,
    PipelineStageResult,
    PipelineStageStatus,
)

# Re-export stages for convenience
from .stages import *

__all__ = [
    # Base classes
    "Pipeline",
    "PipelineStage",
    "PipelineStageResult",
    "PipelineStageStatus",
]
