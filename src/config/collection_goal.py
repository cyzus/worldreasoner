"""Collection goal configuration for WorldReasoner.

Defines targets for question collection with distribution requirements.
"""

from enum import Enum
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field
import yaml
from ..domain.models.question import QuestionType
from ..domain.models.domain import Domain


class TimeHorizon(str, Enum):
    """Time horizon classification for forecasting questions.

    Based on the duration between when a question becomes forecastable
    (estimated_start_time) and its resolution_date.
    """

    SHORT = "short"  # Up to 7 days
    MEDIUM = "medium"  # 7 days to 90 days (1 week to ~3 months)
    LONG = "long"  # More than 90 days (3+ months)

    @classmethod
    def classify(cls, days: float) -> "TimeHorizon":
        """Classify a duration in days into a time horizon.

        Args:
            days: Number of days between start and resolution

        Returns:
            TimeHorizon classification
        """
        if days <= 7:
            return cls.SHORT
        elif days <= 90:
            return cls.MEDIUM
        else:
            return cls.LONG

    @classmethod
    def get_day_range(cls, horizon: "TimeHorizon") -> Tuple[int, int]:
        """Get the (min_days, max_days) range for a time horizon.

        Args:
            horizon: Time horizon to get range for

        Returns:
            Tuple of (min_days, max_days)
        """
        if horizon == cls.SHORT:
            return (0, 7)
        elif horizon == cls.MEDIUM:
            return (7, 90)
        else:
            return (90, 365 * 5)  # Up to 5 years for long


class QualityRequirements(BaseModel):
    """Quality constraints for collected questions."""

    min_difficulty: int = Field(
        default=2, ge=1, le=5, description="Minimum difficulty level (1-5)"
    )
    max_difficulty: int = Field(
        default=5, ge=1, le=5, description="Maximum difficulty level (1-5)"
    )
    min_resolution_days: int = Field(
        default=7,
        description="Days from now: positive = future, negative = past (e.g., -90 = resolved up to 90 days ago)",
    )
    max_resolution_days: int = Field(
        default=365,
        description="Maximum days until resolution (negative for past dates)",
    )
    require_resolution_criteria: bool = Field(
        default=True, description="Questions must have clear resolution criteria"
    )
    min_confidence_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for questions needing validation",
    )


class CollectionGoal(BaseModel):
    """Defines the target for question collection.

    Specifies total questions needed and their distribution across
    question types and categories.
    """

    total_questions: int = Field(
        default=100, ge=1, description="Total number of questions to collect"
    )

    # Distribution by question type (minimum counts)
    type_distribution: Dict[QuestionType, int] = Field(
        default={
            QuestionType.BINARY: 40,
            QuestionType.MCQ: 30,
            QuestionType.QUANTITY: 20,
            QuestionType.TIMEFRAME: 10,
        },
        description="Minimum count for each question type (can collect more to reach total)",
    )

    # Distribution by category/domain
    category_distribution: Dict[Domain, int] = Field(
        default={
            Domain.FINANCE: 25,
            Domain.TECH: 25,
            Domain.POLITICS: 20,
            Domain.SCIENCE: 15,
            Domain.SPORTS: 10,
            Domain.GENERAL: 5,
        },
        description="Minimum count for each category (can collect more to reach total)",
    )

    # Distribution by time horizon (optional)
    time_horizon_distribution: Optional[Dict[TimeHorizon, int]] = Field(
        default=None,
        description="Minimum count for each time horizon. Based on duration between estimated_start_time and resolution_date. None = no time horizon constraint.",
    )

    # Quality constraints
    quality: QualityRequirements = Field(
        default_factory=QualityRequirements,
        description="Quality requirements for collected questions",
    )

    # Ground truth requirement
    require_ground_truth: bool = Field(
        default=True,
        description="If true, collect resolved questions with known outcomes. If false, collect future predictions.",
    )

    # Source priorities and minimums
    source_minimums: Dict[str, int] = Field(
        default={"polymarket": 40, "news": 30},
        description="Minimum questions to collect from each source during initial collection phase",
    )

    def validate_distributions(self) -> bool:
        """Validate that distribution minimums don't exceed total_questions."""
        type_sum = sum(self.type_distribution.values())
        category_sum = sum(self.category_distribution.values())

        if type_sum > self.total_questions:
            raise ValueError(
                f"Type distribution minimums sum to {type_sum}, which exceeds total_questions {self.total_questions}"
            )

        if category_sum > self.total_questions:
            raise ValueError(
                f"Category distribution minimums sum to {category_sum}, which exceeds total_questions {self.total_questions}"
            )

        if self.time_horizon_distribution:
            horizon_sum = sum(self.time_horizon_distribution.values())
            if horizon_sum > self.total_questions:
                raise ValueError(
                    f"Time horizon distribution minimums sum to {horizon_sum}, which exceeds total_questions {self.total_questions}"
                )

        return True

    @classmethod
    def from_yaml(cls, path: str) -> "CollectionGoal":
        """Load collection goal from YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            CollectionGoal instance
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def to_yaml(self, path: str) -> None:
        """Save collection goal to YAML file.

        Args:
            path: Path to save YAML configuration
        """
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)
