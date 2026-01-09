"""Pipeline stages for WorldReasoner."""

# Question Pipeline Stages
from .article_collection import (
    ArticleSource,
    ArticleCollectionConfig,
    ArticleCollectionStage,
)
from .event_identification import (
    EventIdentificationConfig,
    EventIdentificationStage,
)
from .question_generation import QuestionGenerationStage
from .news_question_generation import NewsQuestionGenerationStage

# Evidence Pipeline Stages
from .evidence_collection import (
    HindsightEvidenceCollectionStage,
    EvidenceCollectionConfig,
)
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
    "EventIdentificationConfig",
    "EventIdentificationStage",
    "QuestionGenerationStage",
    "NewsQuestionGenerationStage",
    # Evidence Pipeline Stages
    "HindsightEvidenceCollectionStage",
    "EvidenceCollectionConfig",
    "TargetEventIdentificationStage",
    "TargetEventIdentificationConfig",
    "CausalReasoningStage",
    "CausalReasoningConfig",
    "CausalGraphBuildingStage",
    "CausalGraphConfig",
    # Shared Stages
    "ResultCollector",
]
