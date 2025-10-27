"""Pipeline configuration for WorldReasoner."""

from datetime import date, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field


class QuestionPipelineConfig(BaseModel):
    """Configuration for question generation pipeline."""
    
    # Question generation limits
    max_questions: int = Field(default=10, description="Maximum questions to generate")
    questions_per_domain: Optional[int] = Field(
        default=None, 
        description="Max questions per domain (None = unlimited)"
    )
    
    # Question characteristics
    difficulty_levels: List[int] = Field(
        default=[1, 2, 3, 4, 5],
        description="Allowed difficulty levels (1-5)"
    )
    time_horizons: List[str] = Field(
        default=["short", "medium", "long"],
        description="Allowed time horizons"
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
    forecast_horizon_days: int = Field(
        default=30,
        description="How many days ahead to forecast"
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
    
    # Causal graph settings
    min_causal_links: int = Field(
        default=1,
        description="Minimum causal links for a question"
    )
    causal_confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for causal relationships"
    )
    
    # Data filtering
    exclude_synthetic: bool = Field(
        default=False,
        description="Exclude synthetic data"
    )
    require_ground_truth: bool = Field(
        default=True,
        description="Only generate questions with verifiable outcomes"
    )
    
    # Batch processing settings (for handling large datasets)
    article_batch_size: int = Field(
        default=50,
        description="Maximum articles to process in a single batch for event identification"
    )
    event_batch_size: int = Field(
        default=20,
        description="Maximum events to process in a single batch for question generation"
    )


# Alias for backward compatibility
QuestionConfig = QuestionPipelineConfig


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
        description="Maximum length of causal chains to trace"
    )

    # Graph building settings
    allow_causal_cycles: bool = Field(
        default=False,
        description="Whether to allow cycles in the causal graph"
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
    domain_filter: Optional[str] = Field(
        default=None,
        description="Filter to specific domain (e.g., 'tech', 'finance')"
    )
