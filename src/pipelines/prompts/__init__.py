"""Prompts module for pipeline stages.

This module provides a centralized, reusable system for generating prompts
used throughout the pipeline stages. It includes:

- Base classes for creating consistent, maintainable prompts
- Template-based prompt generation
- Specialized prompt generators for each stage
"""

from .base import (
    BasePromptGenerator,
    ContextualPromptGenerator,
    PromptTemplate,
)
from .article_collection import ArticleCollectionPrompts
from .event_identification import EventIdentificationPrompts
from .question_generation import QuestionGenerationPrompts
from .hindsight_analysis import HindsightAnalysisPrompts
from .question_categorization import QuestionCategorizationPrompts
from .target_event_identification import TargetEventIdentificationPrompts

__all__ = [
    # Base classes
    "BasePromptGenerator",
    "ContextualPromptGenerator",
    "PromptTemplate",
    # Stage-specific prompts
    "ArticleCollectionPrompts",
    "EventIdentificationPrompts",
    "QuestionGenerationPrompts",
    "HindsightAnalysisPrompts",
    "QuestionCategorizationPrompts",
    "TargetEventIdentificationPrompts",
]
