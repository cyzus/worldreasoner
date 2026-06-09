"""Unified pipeline types and enums.

Single source of truth for pipeline types, progress tracking, and results.
Eliminates duplicate definitions across CLI and backend API.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


class PipelineType(str, Enum):
    """Available pipeline types."""

    COLLECTION = "collection"
    NEWS_COLLECTION = "news_collection"
    EVIDENCE = "evidence"
    ADAPTIVE_EVIDENCE = "adaptive_evidence"
    FORECAST = "forecast"
    EVALUATION = "evaluation"
    BENCHMARK = "benchmark"
    AUTO_BENCHMARK = "auto_benchmark"
    GRAPH_BUILDER = "graph_builder"
    REASONING_EVAL = "reasoning_eval"


@dataclass
class PipelineProgress:
    """Progress update from pipeline execution."""

    current: int
    total: int
    question_id: Optional[str]
    stage: str
    message: str


@dataclass
class PipelineResult:
    """Result of pipeline execution."""

    processed: List[Dict[str, Any]]
    failed: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]
    duration_seconds: float

    @property
    def success_count(self) -> int:
        return len(self.processed)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)
