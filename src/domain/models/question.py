"""Question/forecast task data model."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict
from ...core.database import register_model
from .domain import Domain


class QuestionType(str, Enum):
    """Types of forecast questions."""

    BOOLEAN = "boolean"
    MCQ = "mcq"
    QUANTITY = "quantity"
    TIMEFRAME = "timeframe"


@register_model('questions', indexes=['domain', 'difficulty'])
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
    domain: Domain = Field(..., description="Primary domain")
    difficulty: int = Field(..., ge=1, le=5, description="Difficulty rating 1-5")

    # Temporal boundaries
    resolution_date: datetime = Field(
        ...,
        description="When ground truth becomes available/verifiable"
    )
    
    # Ground truth (hidden from forecasters during evaluation)
    ground_truth: Optional[Any] = Field(
        None,
        description="Actual outcome (type depends on question_type). None for unresolved questions."
    )
    ground_truth_hash: Optional[str] = Field(
        None,
        description="Cryptographic hash for integrity verification"
    )
    
    # Event reference (optional - for structured benchmark questions)
    target_event_id: Optional[str] = Field(
        None,
        description="ID of the event this question is asking about (if event-based)"
    )
    related_event_ids: List[str] = Field(
        default_factory=list,
        description="Other relevant events (for multi-event or exploratory questions)"
    )
    
    # Question-specific metadata
    context: Optional[str] = Field(
        None,
        description="Background information provided to forecaster"
    )
    resolution_criteria: Optional[str] = Field(
        None,
        description="Objective rules for how to verify/resolve this question (e.g., 'Based on CoinMarketCap closing price on Dec 31, 2024')"
    )
    resolution_reasoning: Optional[str] = Field(
        None,
        description="Evidence and explanation for why the ground_truth is what it is (only for resolved questions)"
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
    
    # Metadata
    is_synthetic: bool = Field(default=False, description="Whether question uses synthetic data")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    model_config = ConfigDict(
        extra="allow",  # Allow transient fields like cutoff_date during evaluation
        json_schema_extra={
            "example": {
                "id": "q_pol_2024_001",
                "question_text": "Will the Republican candidate win the 2024 US Presidential Election?",
                "question_type": "boolean",
                "domain": "politics",
                "difficulty": 4,
                "resolution_date": "2024-11-06T00:00:00Z",
                "ground_truth": True,
                "ground_truth_hash": "sha256:abc123...",
                "target_event_id": "evt_pol_20241105_001",
                "context": "The 2024 United States presidential election will be held on November 5, 2024.",
            }
        }
    )

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
    
    def set_evaluation_cutoff(self, cutoff_date: datetime) -> 'Question':
        """Set the cutoff date for evaluation/benchmarking (transient, not persisted).

        The cutoff_date simulates the "current time" when a forecaster makes their prediction.
        This is a RUNTIME-ONLY attribute used by the temporal gateway during evaluation.
        It is NOT persisted to the database - it should be set fresh for each evaluation run.

        This should be set during evaluation to ensure fair testing:
        - For past events: Set to before the event occurred (to test forecasting ability)
        - For future events: Set to the evaluation time (what info is available now)

        Args:
            cutoff_date: The information cutoff datetime (timezone-aware)

        Returns:
            Self for method chaining

        Example:
            >>> question.set_evaluation_cutoff(datetime(2024, 11, 1, tzinfo=timezone.utc))
        """
        self.cutoff_date = cutoff_date
        return self

    def get_forecast_context_window(self, db=None, min_context_items: int = 3):
        """Get the valid temporal window for forecasting this question.

        Returns the date range during which a forecast can be made:
        - Start: When sufficient context becomes available (Nth earliest context item)
        - End: When the answer becomes known (resolution_date)

        Args:
            db: Database instance for fetching related events/articles
            min_context_items: Minimum number of context items needed (default: 3)

        Returns:
            (window_start, window_end) datetime tuple

        Example:
            >>> # Opens when 3rd context item available (default)
            >>> start, end = question.get_forecast_context_window(db)
            >>> # Opens when 5th context item available
            >>> start, end = question.get_forecast_context_window(db, min_context_items=5)
        """
        from .question_helpers import calculate_forecast_context_window
        return calculate_forecast_context_window(self, db=db, min_context_items=min_context_items)

    def validate_simulated_date(self, simulated_date: datetime, window_start: datetime, window_end: datetime):
        """Check if a simulated date is valid for forecasting this question.

        Note: Use prepare_forecast() for the complete workflow. This is a lightweight helper.

        Args:
            simulated_date: The proposed simulation date
            window_start: Start of valid forecast window
            window_end: End of valid forecast window

        Returns:
            (is_valid, error_message) tuple

        Example:
            >>> window_start, window_end = question.get_forecast_context_window(db)
            >>> valid, error = question.validate_simulated_date(datetime(2025, 11, 3), window_start, window_end)
            >>> if not valid:
            >>>     raise ValueError(error)
        """
        from .question_helpers import validate_simulated_date
        return validate_simulated_date(self, simulated_date, window_start, window_end)

    def suggest_simulated_date(self, window_start: datetime, window_end: datetime, offset_days_before_resolution: int = 7):
        """Get a suggested simulated date for forecasting this question.

        Note: Use prepare_forecast() for the complete workflow. This is a lightweight helper.

        Args:
            window_start: Start of valid forecast window
            window_end: End of valid forecast window
            offset_days_before_resolution: How many days before resolution to suggest

        Returns:
            Suggested datetime for simulation

        Example:
            >>> window_start, window_end = question.get_forecast_context_window(db)
            >>> simulated_date = question.suggest_simulated_date(window_start, window_end, offset_days_before_resolution=14)
        """
        from .question_helpers import suggest_simulated_date
        return suggest_simulated_date(self, window_start, window_end, offset_days_before_resolution)

    def prepare_forecast(self, db=None, offset_days_before_resolution: int = 0, min_context_items: int = 3):
        """Get all information needed to forecast this question (hides complexity).

        This single method handles all the setup in one pass:
        - Calculates valid forecast window
        - Suggests appropriate simulated date
        - Validates the setup
        - Returns everything needed

        No redundant calculations - everything happens in a single pass.

        Args:
            db: Database instance for fetching context
            offset_days_before_resolution: How many days before resolution to simulate (default: 0)
            min_context_items: Minimum number of context items needed (default: 3)

        Returns:
            dict with keys:
                - window_start: When forecasting window opens
                - window_end: When forecasting window closes
                - simulated_date: Suggested date to use for forecast
                - days_available: Number of days in forecast window

        Raises:
            ValueError: If insufficient context or invalid configuration

        Example:
            >>> setup = question.prepare_forecast(db, offset_days_before_resolution=7)
            >>> agent = ForecastAgent(question, simulated_date=setup['simulated_date'])
        """
        from .question_helpers import prepare_forecast_context
        return prepare_forecast_context(self, db, offset_days_before_resolution, min_context_items)
