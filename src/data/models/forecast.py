"""Forecast submission data model."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    
    # Prediction
    prediction: Any = Field(
        ...,
        description="Predicted outcome (type matches question.question_type)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in prediction (0-1, where 1 is most confident)"
    )
    reasoning: str = Field(
        ...,
        min_length=50,
        description="Explanation of the prediction and reasoning process"
    )
    
    # Temporal context
    timestamp: datetime = Field(
        default_factory=datetime.now(datetime.timezone.utc),
        description="When forecast was submitted"
    )
    simulated_date: Optional[datetime] = Field(
        None,
        description="Simulated 'current date' during forecast (for temporal context)"
    )
    
    # Information access log
    articles_accessed: List[str] = Field(
        default_factory=list,
        description="Article IDs accessed during reasoning"
    )
    searches_performed: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Search queries and results metadata"
    )
    
    # Model information
    model_name: Optional[str] = Field(None, description="Name of the model that made the forecast")
    model_version: Optional[str] = Field(None, description="Version of the model")
    
    # Evaluation results (populated after resolution)
    is_correct: Optional[bool] = Field(None, description="Whether prediction was correct")
    brier_score: Optional[float] = Field(None, description="Brier score for probabilistic accuracy")
    log_score: Optional[float] = Field(None, description="Logarithmic score")
    evaluation_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional evaluation metrics and analysis"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "fcst_20240930_001",
                "session_id": "sess_abc123",
                "question_id": "q_pol_2024_001",
                "prediction": True,
                "confidence": 0.65,
                "reasoning": "Based on polling averages in swing states (Pennsylvania, Michigan, Wisconsin), "
                             "demographic trends, and historical voting patterns, the Republican candidate "
                             "appears to have a slight advantage. Recent polls show consistent leads within "
                             "the margin of error.",
                "timestamp": "2024-09-30T18:45:00Z",
                "simulated_date": "2024-09-30T00:00:00Z",
                "articles_accessed": [
                    "art_pol_20240928_001",
                    "art_pol_20240925_042",
                    "art_pol_20240929_018"
                ],
                "searches_performed": [
                    {
                        "query": "US election 2024 polling swing states",
                        "results_count": 15,
                        "timestamp": "2024-09-30T18:30:00Z"
                    }
                ],
                "model_name": "gpt-4",
                "model_version": "gpt-4-0613",
            }
        }

    def get_articles_count(self) -> int:
        """Get count of unique articles accessed."""
        return len(set(self.articles_accessed))

    def get_searches_count(self) -> int:
        """Get count of searches performed."""
        return len(self.searches_performed)

    def get_reasoning_word_count(self) -> int:
        """Get word count of reasoning text."""
        return len(self.reasoning.split())
