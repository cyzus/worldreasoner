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
        default=[1, 2, 3, 4, 5],
        description="Allowed difficulty levels (1-5)"
    )
    domains: List[str] = Field(
        default=["finance", "politics", "tech", "health", "climate"],
        description="Domains to generate questions for"
    )
    question_types: List[str] = Field(
        default=["boolean", "mcq", "quantity", "timeframe"],
        description="Types of questions to generate"
    )
    
    # Temporal settings
    start_date: date = Field(
        default_factory=lambda: date.today() - timedelta(days=30),
        description="Start date for article collection"
    )
    end_date: date = Field(
        default_factory=date.today,
        description="End date for article collection"
    )

    # Event identification settings
    min_articles_per_event: int = Field(
        default=3,
        description="Minimum articles needed to identify an event"
    )
    event_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to consider an event valid"
    )
           
    require_ground_truth: bool = Field(
        default=True,
        description="If True, generate questions about past events with ground truth. If False, generate future prediction questions."
    )
    
    # Batch processing settings (for handling large datasets)
    article_batch_size: int = Field(
        default=20,
        description="Maximum articles to process in a single batch for event identification"
    )
    event_batch_size: int = Field(
        default=20,
        description="Maximum events to process in a single batch for question generation"
    )


class QuestionQualityConfig(BaseModel):
    """Configuration for the Question Quality Ranking stage."""

    enabled: bool = Field(
        default=True,
        description="Enable/disable the quality ranking stage"
    )
    batch_size: int = Field(
        default=20,
        description="Number of questions to score in a single batch"
    )
    timeout: int = Field(
        default=180,
        description="Timeout in seconds for quality scoring LLM calls (default 180s for batch processing)"
    )
    # Weights for each dimension in the composite score
    dimension_weights: dict[str, float] = Field(default_factory=lambda: {
        "interestingness": 1.0,
        "clarity": 1.0,
        "verifiability": 1.0,
        "temporal_validity": 1.0,
        "context_sufficiency": 1.0,
        "difficulty_appropriateness": 1.0,
        "format_consistency": 1.0,
    })


class EvidencePipelineConfig(BaseModel):
    """Configuration for the Evidence Pipeline (backward-looking causal analysis)."""

    # Evidence collection settings
    evidence_window_days: int = Field(
        default=30,
        description="Days before resolution to collect evidence articles (causal factors)"
    )
    min_evidence_articles: int = Field(
        default=5,
        description="Minimum evidence articles per event"
    )
    include_expert_analysis: bool = Field(
        default=True,
        description="Prioritize expert analysis and post-mortem articles"
    )

    # Causal reasoning settings
    causal_confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for accepting causal hypotheses"
    )
    causal_strength_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum causal strength to consider significant"
    )
    require_evidence: bool = Field(
        default=True,
        description="Causal hypotheses must cite evidence articles"
    )
    max_causal_depth: int = Field(
        default=3,
        description="Maximum depth of causal graph paths to trace"
    )

    validate_temporal_ordering: bool = Field(
        default=True,
        description="Ensure causes temporally precede effects"
    )
    max_links_per_event: int = Field(
        default=10,
        description="Maximum causal links per event to prevent bloat"
    )

    # Batch processing settings
    question_batch_size: int = Field(
        default=10,
        description="Resolved questions to process per batch"
    )
    reasoning_batch_size: int = Field(
        default=20,
        description="Question-evidence pairs per batch for reasoning"
    )

    # Filtering
    min_resolution_age_days: int = Field(
        default=1,
        description="Minimum days since resolution to process (allow time for analysis)"
    )
    max_resolution_age_days: Optional[int] = Field(
        default=365,
        description="Maximum days since resolution (None = no limit)"
    )
    max_questions: Optional[int] = Field(
        default=None,
        description="Maximum number of questions to process (None = process all)"
    )
    skip_already_processed: bool = Field(
        default=True,
        description="Skip questions that already have causal hypotheses (set False to force re-process)"
    )
    domains: List[str] = Field(
        default_factory=list,
        description="Filter to specific domains (e.g., ['tech', 'finance']). Empty list = all domains"
    )
