"""Question collection pipeline.

Orchestrates goal-oriented collection from multiple sources (Polymarket, news).
"""

from .orchestrator import QuestionCollectionOrchestrator, OrchestratorConfig
from .runner_base import QuestionSourceRunner, CollectionResult
from .runner_polymarket import PolymarketRunner
from .runner_news import NewsBasedRunner
from .stage_articles import (
    ArticleSource,
    ArticleCollectionConfig,
    ArticleCollectionStage,
)
from .stage_news_questions import NewsQuestionGenerationStage
from .stage_quality import QuestionQualityRankingStage
from .refresh_polymarket import refresh_polymarket_ground_truth, RefreshResult

__all__ = [
    "QuestionCollectionOrchestrator",
    "OrchestratorConfig",
    "QuestionSourceRunner",
    "CollectionResult",
    "PolymarketRunner",
    "NewsBasedRunner",
    "ArticleSource",
    "ArticleCollectionConfig",
    "ArticleCollectionStage",
    "NewsQuestionGenerationStage",
    "QuestionQualityRankingStage",
    "refresh_polymarket_ground_truth",
    "RefreshResult",
]
