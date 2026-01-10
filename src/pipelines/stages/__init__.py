"""Pipeline stages for WorldReasoner."""

# Question Pipeline Stages
from .article_collection import (
    ArticleSource,
    ArticleCollectionConfig,
    ArticleCollectionStage,
)
from .news_question_generation import NewsQuestionGenerationStage




# Evidence Pipeline Stages
from .target_event_identification import (
    TargetEventIdentificationStage,
    TargetEventIdentificationConfig,
)

from .causal_reasoning import (
    CausalReasoningStage,
    CausalReasoningConfig,
)
from .graph_building import (
    CausalGraphBuildingStage,
    CausalGraphConfig,
)

# Shared Stages
from src.core.collectors import ResultCollector

__all__ = [
    # Question Pipeline Stages
    "ArticleSource",
    "ArticleCollectionConfig",
    "ArticleCollectionStage",
    "NewsQuestionGenerationStage",

    # Evidence Pipeline Stages
    "TargetEventIdentificationStage",
    "TargetEventIdentificationConfig",
    "CausalReasoningStage",
    "CausalReasoningConfig",
    "CausalGraphBuildingStage",
    "CausalGraphConfig",
    # Shared Stages
    "ResultCollector",
]
