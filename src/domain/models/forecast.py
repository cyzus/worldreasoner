"""Forecast submission data model."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from ...core.database import register_model
from .causal_hypothesis import CausalHypothesis


class ForecastMode(str, Enum):
    """Forecasting mode types."""

    KNOWLEDGE_ONLY = "knowledge_only"
    CONTAINER = "container"
    REAL_TIME = "real_time"


@register_model("forecasts", indexes=["question_id", "session_id", "mode", "db"])
class Forecast(BaseModel):
    """LLM forecast submission.

    Represents a prediction made by an LLM for a specific question.
    Includes the prediction, confidence, reasoning, and metadata about
    the information accessed during the forecasting process.
    """

    # Core identification
    id: str = Field(..., description="Unique forecast identifier")
    session_id: str = Field(..., description="Session this forecast belongs to")
    question_id: str = Field(..., description="Question being answered")
    target_event_id: Optional[str] = Field(
        None,
        description="ID of the event being forecasted (denormalized from question)",
    )

    # Prediction
    prediction: Any = Field(
        ..., description="Predicted outcome (type matches question.question_type)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in prediction (0-1, where 1 is most confident)",
    )
    reasoning: str = Field(
        ...,
        min_length=50,
        description="Explanation of the prediction and reasoning process",
    )

    # Causal reasoning (the LLM's mental model)
    identified_events: List[str] = Field(
        default_factory=list,
        description="Event IDs that the LLM identified as relevant",
    )
    causal_hypotheses: List[CausalHypothesis] = Field(
        default_factory=list,
        description="Causal hypotheses the LLM constructed during reasoning (can form a DAG, not just a chain)",
    )

    # Temporal context
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When forecast was submitted",
    )
    simulated_date: Optional[datetime] = Field(
        None,
        description="Simulated 'current date' during forecast (for temporal context)",
    )

    # Information access log
    articles_accessed: List[str] = Field(
        default_factory=list, description="Article IDs accessed during reasoning"
    )
    searches_performed: List[Dict[str, Any]] = Field(
        default_factory=list, description="Search queries and results metadata"
    )

    # Model information
    model_name: Optional[str] = Field(
        None, description="Name of the model that made the forecast"
    )
    model_version: Optional[str] = Field(None, description="Version of the model")

    # Mode and database tracking
    db: Optional[str] = Field(None, description="Database path used for this forecast")
    mode: ForecastMode = Field(
        ForecastMode.CONTAINER, description="Forecasting mode used"
    )
    enabled_tools: List[str] = Field(
        default_factory=list,
        description="Tool categories enabled during forecast (e.g., 'causal_tools', 'web_tools')",
    )

    # Evaluation results (populated after resolution)
    is_correct: Optional[bool] = Field(
        None, description="Whether prediction was correct"
    )
    brier_score: Optional[float] = Field(
        None, description="Brier score for probabilistic accuracy"
    )
    log_score: Optional[float] = Field(None, description="Logarithmic score")
    evaluation_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional evaluation metrics and analysis"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "fcst_20240930_001",
                "session_id": "sess_abc123",
                "question_id": "q_pol_2024_001",
                "target_event_id": "evt_pol_20241105_001",
                "prediction": True,
                "confidence": 0.65,
                "reasoning": "Based on polling averages in swing states (Pennsylvania, Michigan, Wisconsin), "
                "demographic trends, and historical voting patterns, the Republican candidate "
                "appears to have a slight advantage. Recent polls show consistent leads within "
                "the margin of error.",
                "identified_events": [
                    "evt_pol_20240915_poll_shift",
                    "evt_pol_20241020_campaign_strategy",
                    "evt_pol_20241025_debate",
                    "evt_pol_20241105_001",
                ],
                "causal_hypotheses": [
                    {
                        "id": "hyp_forecast_001",
                        "source_event_id": "evt_pol_20240915_poll_shift",
                        "target_event_id": "evt_pol_20241020_campaign_strategy",
                        "relation_type": "causes",
                        "strength": 0.7,
                        "confidence": 0.8,
                        "reasoning": "Poll results influenced campaign spending allocation",
                        "evidence_article_ids": ["art_pol_20240928_001"],
                        "discovered_by_question_ids": [],
                        "identified_by": "llm_forecast",
                        "first_identified_at": "2024-09-30T18:45:00Z",
                        "last_confirmed_at": "2024-09-30T18:45:00Z",
                    },
                    {
                        "id": "hyp_forecast_002",
                        "source_event_id": "evt_pol_20241020_campaign_strategy",
                        "target_event_id": "evt_pol_20241105_001",
                        "relation_type": "enables",
                        "strength": 0.5,
                        "confidence": 0.6,
                        "reasoning": "Increased ad spending in swing states likely to impact voter turnout",
                        "evidence_article_ids": ["art_pol_20240929_018"],
                        "discovered_by_question_ids": [],
                        "identified_by": "llm_forecast",
                        "first_identified_at": "2024-09-30T18:45:00Z",
                        "last_confirmed_at": "2024-09-30T18:45:00Z",
                    },
                    {
                        "id": "hyp_forecast_003",
                        "source_event_id": "evt_pol_20241025_debate",
                        "target_event_id": "evt_pol_20241105_001",
                        "relation_type": "causes",
                        "strength": 0.6,
                        "confidence": 0.7,
                        "reasoning": "Debate performance affects undecided voters",
                        "evidence_article_ids": ["art_pol_20241026_003"],
                        "discovered_by_question_ids": [],
                        "identified_by": "llm_forecast",
                        "first_identified_at": "2024-09-30T18:45:00Z",
                        "last_confirmed_at": "2024-09-30T18:45:00Z",
                    },
                ],
                "timestamp": "2024-09-30T18:45:00Z",
                "simulated_date": "2024-09-30T00:00:00Z",
                "articles_accessed": [
                    "art_pol_20240928_001",
                    "art_pol_20240925_042",
                    "art_pol_20240929_018",
                ],
                "searches_performed": [
                    {
                        "query": "US election 2024 polling swing states",
                        "results_count": 15,
                        "timestamp": "2024-09-30T18:30:00Z",
                    }
                ],
                "model_name": "gpt-4",
                "model_version": "gpt-4-0613",
            }
        }
    )

    def get_articles_count(self) -> int:
        """Get count of unique articles accessed."""
        return len(set(self.articles_accessed))

    def get_searches_count(self) -> int:
        """Get count of searches performed."""
        return len(self.searches_performed)

    def get_reasoning_word_count(self) -> int:
        """Get word count of reasoning text."""
        return len(self.reasoning.split())
