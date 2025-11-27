"""Collection goal configuration for WorldReasoner.

Defines targets for question collection with distribution requirements.
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field
import yaml


class QualityRequirements(BaseModel):
    """Quality constraints for collected questions."""

    min_difficulty: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Minimum difficulty level (1-5)"
    )
    max_difficulty: int = Field(
        default=5,
        ge=1,
        le=5,
        description="Maximum difficulty level (1-5)"
    )
    min_resolution_days: int = Field(
        default=7,
        description="Days from now: positive = future, negative = past (e.g., -90 = resolved up to 90 days ago)"
    )
    max_resolution_days: int = Field(
        default=365,
        description="Maximum days until resolution (negative for past dates)"
    )
    require_resolution_criteria: bool = Field(
        default=True,
        description="Questions must have clear resolution criteria"
    )
    min_confidence_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for questions needing validation"
    )


class CollectionGoal(BaseModel):
    """Defines the target for question collection.

    Specifies total questions needed and their distribution across
    question types and categories.
    """

    total_questions: int = Field(
        default=100,
        ge=1,
        description="Total number of questions to collect"
    )

    # Distribution by question type (exact counts)
    type_distribution: Dict[str, int] = Field(
        default={
            "boolean": 40,
            "multiple_choice": 30,
            "quantity": 20,
            "timeframe": 10
        },
        description="Target count for each question type"
    )

    # Distribution by category/domain
    category_distribution: Dict[str, int] = Field(
        default={
            "finance": 25,
            "technology": 25,
            "politics": 20,
            "science": 15,
            "sports": 10,
            "other": 5
        },
        description="Target count for each category"
    )

    # Quality constraints
    quality: QualityRequirements = Field(
        default_factory=QualityRequirements,
        description="Quality requirements for collected questions"
    )

    # Ground truth requirement
    require_ground_truth: bool = Field(
        default=True,
        description="If true, collect resolved questions with known outcomes. If false, collect future predictions."
    )

    # Tolerance (allow 90% of target as "good enough")
    distribution_tolerance: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Tolerance for distribution matching (0.9 = accept 90% of target)"
    )

    # Source priorities and quotas
    source_quotas: Dict[str, int] = Field(
        default={
            "polymarket": 40,
            "metaculus": 30,
            "news": 30
        },
        description="Maximum questions to collect from each source"
    )

    def validate_distributions(self) -> bool:
        """Validate that distributions sum to total_questions."""
        type_sum = sum(self.type_distribution.values())
        category_sum = sum(self.category_distribution.values())

        if type_sum != self.total_questions:
            raise ValueError(
                f"Type distribution sums to {type_sum}, expected {self.total_questions}"
            )

        if category_sum != self.total_questions:
            raise ValueError(
                f"Category distribution sums to {category_sum}, expected {self.total_questions}"
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
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def to_yaml(self, path: str) -> None:
        """Save collection goal to YAML file.

        Args:
            path: Path to save YAML configuration
        """
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(
                self.model_dump(),
                f,
                default_flow_style=False,
                sort_keys=False
            )
