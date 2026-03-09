"""Pipeline configuration for WorldReasoner."""

from datetime import date, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field

class QuestionPipelineConfig(BaseModel):
    """Configuration for question generation pipeline."""

    # Question generation limits
    max_questions: int = Field(default=10, description="Maximum questions to generate")

    # Question characteristics
    difficulty_levels: List[int] = Field(
        default=[1, 2, 3, 4, 5], description="Allowed difficulty levels (1-5)"
    )
    domains: List[str] = Field(
        default=["finance", "politics", "tech", "health", "climate"],
        description="Domains to generate questions for",
    )
    question_types: List[str] = Field(
        default=["binary", "mcq", "quantity", "timeframe"],
        description="Types of questions to generate",
    )

    # Temporal settings
    start_date: date = Field(
        default_factory=lambda: date.today() - timedelta(days=30),
        description="Start date for article collection",
    )
    end_date: date = Field(
        default_factory=date.today, description="End date for article collection"
    )

    # Event identification settings
    min_articles_per_event: int = Field(
        default=3, description="Minimum articles needed to identify an event"
    )
    event_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to consider an event valid",
    )

    require_ground_truth: bool = Field(
        default=True,
        description="If True, generate questions about past events with ground truth. If False, generate future prediction questions.",
    )

    # Batch processing settings (for handling large datasets)
    article_batch_size: int = Field(
        default=20,
        description="Maximum articles to process in a single batch for event identification",
    )
    event_batch_size: int = Field(
        default=20,
        description="Maximum events to process in a single batch for question generation",
    )


class QuestionQualityConfig(BaseModel):
    """Configuration for the Question Quality Ranking stage."""

    enabled: bool = Field(
        default=True, description="Enable/disable the quality ranking stage"
    )
    batch_size: int = Field(
        default=20, description="Number of questions to score in a single batch"
    )
    timeout: int = Field(
        default=180,
        description="Timeout in seconds for quality scoring LLM calls (default 180s for batch processing)",
    )

    # Weights for each dimension in the composite score (must sum to 1.0)
    dimension_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "verifiability": 0.25,  # Most critical - can we verify outcome?
            "interestingness": 0.20,  # Is this engaging and significant?
            "clarity": 0.20,  # Is it unambiguous and well-defined?
            "temporal_validity": 0.15,  # Is the resolution date appropriate?
            "context_sufficiency": 0.10,  # Is there enough background info?
            "difficulty_appropriateness": 0.05,  # Is difficulty rating accurate?
            "format_consistency": 0.05,  # Are fields consistent with type?
        }
    )

    # Thresholds for skipping evidence processing (questions below these are saved but not processed)
    skip_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "composite_score": 0.40,  # Overall quality too low
            "verifiability": 0.40,  # Cannot be objectively verified
            "interestingness": 0.25,  # Boring/noisy/trivial
            "clarity": 0.30,  # Too ambiguous
        }
    )

    # Thresholds for quality warnings (borderline cases that still get processed)
    warning_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "composite_score": 0.55,  # Borderline overall quality
            "critical_dimension": 0.50,  # Any critical dimension (verifiability, interestingness, clarity) below this
        }
    )


class EvidenceSatisfactionConfig(BaseModel):
    """Thresholds for evidence satisfaction (shared across codebase).

    This is the single source of truth for evidence quality thresholds.
    Used by QuestionMonitorService, EvidencePipeline, and prompts.
    """

    min_graph_depth: int = Field(default=3, description="Minimum causal graph depth")
    min_graph_events: int = Field(default=10, description="Minimum events in the causal graph")
    min_articles: int = Field(default=20, description="Minimum evidence articles")
    min_hypotheses: int = Field(default=1, description="Minimum causal hypotheses")
    min_confidence: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Hypothesis confidence threshold"
    )
    min_strength: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Hypothesis strength threshold"
    )


# Default instance — use this to access canonical threshold values in function signatures
SATISFACTION_DEFAULTS = EvidenceSatisfactionConfig()


class EvidencePipelineConfig(BaseModel):
    """Configuration for the Evidence Pipeline (backward-looking causal analysis)."""

    # Satisfaction thresholds (centralized)
    satisfaction: EvidenceSatisfactionConfig = Field(
        default_factory=EvidenceSatisfactionConfig,
        description="Evidence satisfaction thresholds",
    )

    # Evidence collection settings
    evidence_window_days: int = Field(
        default=365,
        description="Days before resolution to collect evidence articles (causal factors)",
    )

    @property
    def min_evidence_articles(self) -> int:
        """Backward-compatible accessor for min_articles."""
        return self.satisfaction.min_articles

    include_expert_analysis: bool = Field(
        default=True, description="Prioritize expert analysis and post-mortem articles"
    )

    # Causal reasoning settings
    causal_confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for accepting causal hypotheses",
    )
    causal_strength_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum causal strength to consider significant",
    )
    require_evidence: bool = Field(
        default=True, description="Causal hypotheses must cite evidence articles"
    )
    validate_temporal_ordering: bool = Field(
        default=True, description="Ensure causes temporally precede effects"
    )
    max_links_per_event: int = Field(
        default=10, description="Maximum causal links per event to prevent bloat"
    )

    # Batch processing settings
    question_batch_size: int = Field(
        default=10, description="Resolved questions to process per batch"
    )
    reasoning_batch_size: int = Field(
        default=20, description="Question-evidence pairs per batch for reasoning"
    )

    # Filtering
    min_resolution_age_days: int = Field(
        default=1,
        description="Minimum days since resolution to process (allow time for analysis)",
    )
    max_resolution_age_days: Optional[int] = Field(
        default=365, description="Maximum days since resolution (None = no limit)"
    )
    max_questions: Optional[int] = Field(
        default=None,
        description="Maximum number of questions to process (None = process all)",
    )
    skip_already_processed: bool = Field(
        default=True,
        description="Skip questions that already have causal hypotheses (set False to force re-process)",
    )
    domains: List[str] = Field(
        default_factory=list,
        description="Filter to specific domains (e.g., ['tech', 'finance']). Empty list = all domains",
    )
