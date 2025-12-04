"""Question source runners for WorldReasoner.

Provides abstraction for collecting questions from various sources:
- Prediction markets (Polymarket, Metaculus)
- News-based pipeline (existing article→event→question flow)
- Finance APIs (earnings, IPOs)
"""

from .base import QuestionSourceRunner, CollectionResult
from .markets import PolymarketRunner
from .news import NewsBasedRunner

__all__ = [
    "QuestionSourceRunner",
    "CollectionResult",
    "PolymarketRunner",
    "NewsBasedRunner",
]
