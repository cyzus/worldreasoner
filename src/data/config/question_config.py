"""Question generation configuration for WorldReasoner."""

from datetime import datetime, date, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field


class QuestionConfig(BaseModel):
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





