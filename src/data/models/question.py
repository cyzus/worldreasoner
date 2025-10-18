"""Question/forecast task data model."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """Types of forecast questions."""

    BOOLEAN = "boolean"
    MCQ = "mcq"
    QUANTITY = "quantity"
    TIMEFRAME = "timeframe"


class TimeHorizon(str, Enum):
    """Forecast time horizon categories."""

    SHORT = "short"  # 1-7 days
    MEDIUM = "medium"  # 1-6 months
    LONG = "long"  # 6+ months


class Question(BaseModel):
    """Benchmark forecast question.
    
    Questions define the forecasting tasks that LLMs will attempt.
    They include the question text, ground truth answer, and metadata
    about difficulty and temporal constraints.
    """

    # Core identification
    id: str = Field(..., description="Unique question identifier")
    question_text: str = Field(..., min_length=20, description="The forecasting question")
    question_type: QuestionType = Field(..., description="Type of answer expected")
    
    # Classification
    domain: str = Field(..., description="Primary domain (finance|politics|tech|health|climate)")
    difficulty: int = Field(..., ge=1, le=5, description="Difficulty rating 1-5")
    time_horizon: TimeHorizon = Field(..., description="Forecast time range")
    
    # Temporal boundaries
    cutoff_date: datetime = Field(
        ...,
        description="Latest date for information access (simulated 'now')"
    )
    resolution_date: datetime = Field(
        ...,
        description="When ground truth becomes available/verifiable"
    )
    
    # Ground truth (hidden from forecasters during evaluation)
    ground_truth: Any = Field(
        ...,
        description="Actual outcome (type depends on question_type)"
    )
    ground_truth_hash: Optional[str] = Field(
        None,
        description="Cryptographic hash for integrity verification"
    )
    
    # Question-specific metadata
    context: Optional[str] = Field(
        None,
        description="Background information provided to forecaster"
    )
    options: Optional[List[str]] = Field(
        None,
        description="Options for MCQ questions"
    )
    quantity_unit: Optional[str] = Field(
        None,
        description="Unit for quantity questions (e.g., 'USD', 'people', 'GW')"
    )
    quantity_bounds: Optional[Dict[str, float]] = Field(
        None,
        description="Valid range for quantity questions {'min': x, 'max': y}"
    )
    
    # Causal structure
    causal_graph: Optional[Dict[str, Any]] = Field(
        None,
        description="Graph structure of causal relationships"
    )
    
    # Related content
    related_articles: List[str] = Field(
        default_factory=list,
        description="Suggested starting articles for research"
    )
    key_events: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Important events in the causal chain"
    )
    
    # Metadata
    is_synthetic: bool = Field(default=False, description="Whether question uses synthetic data")
    benchmark_suite_id: Optional[str] = Field(
        None,
        description="ID of benchmark suite this question belongs to"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "id": "q_pol_2024_001",
                "question_text": "Will the Republican candidate win the 2024 US Presidential Election?",
                "question_type": "boolean",
                "domain": "politics",
                "difficulty": 4,
                "time_horizon": "short",
                "cutoff_date": "2024-11-04T23:59:59Z",
                "resolution_date": "2024-11-06T00:00:00Z",
                "ground_truth": True,
                "ground_truth_hash": "sha256:abc123...",
                "context": "The 2024 United States presidential election will be held on November 5, 2024.",
                "related_articles": ["art_pol_20240925_001", "art_pol_20240928_042"],
            }
        }

    def validate_prediction(self, prediction: Any) -> bool:
        """Validate that a prediction matches the expected type for this question.
        
        Args:
            prediction: The prediction to validate
            
        Returns:
            True if valid, False otherwise
        """
        if self.question_type == QuestionType.BOOLEAN:
            return isinstance(prediction, bool)
        elif self.question_type == QuestionType.MCQ:
            if self.options:
                return prediction in self.options
            return isinstance(prediction, str)
        elif self.question_type == QuestionType.QUANTITY:
            if isinstance(prediction, dict):
                return "lower" in prediction and "upper" in prediction
            return isinstance(prediction, (int, float))
        elif self.question_type == QuestionType.TIMEFRAME:
            # Could be string (ISO datetime) or dict with range
            return isinstance(prediction, (str, dict))
        return False
