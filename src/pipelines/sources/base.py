"""Base abstraction for question sources.

Defines the interface that all question sources must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from src.domain.models import Question
from src.config.collection_goal import QualityRequirements
from src.utils.logging import logger


class CollectionResult(BaseModel):
    """Result from a question collection operation."""

    source_name: str
    questions: List[Question] = Field(default_factory=list)
    requested_count: int
    actual_count: int
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-set actual_count if not provided
        if "actual_count" not in data:
            self.actual_count = len(self.questions)


class QuestionSourceRunner(ABC):
    """Abstract base class for question source runners.

    Each source (prediction markets, news, finance APIs) implements this interface
    to provide questions in a standardized way.
    """

    def __init__(self, source_name: str):
        """Initialize source runner.

        Args:
            source_name: Identifier for this source (e.g., "polymarket", "news")
        """
        self.source_name = source_name

    @abstractmethod
    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
    ) -> CollectionResult:
        """Collect questions from this source.

        Args:
            count: Target number of questions to collect
            type_filter: Only collect these question types (e.g., ["boolean", "mcq"])
            category_filter: Only collect these categories (e.g., ["finance", "tech"])
            quality_requirements: Quality constraints for collected questions

        Returns:
            CollectionResult with collected questions and metadata
        """
        pass

    async def can_provide(
        self,
        question_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        """Check if this source can provide questions of given type/category.

        Args:
            question_type: Question type to check (e.g., "boolean")
            category: Category to check (e.g., "finance")

        Returns:
            True if source can provide matching questions
        """
        # Default implementation - assume source can provide anything
        # Subclasses can override to indicate specific capabilities
        return True

    def _filter_questions(
        self,
        questions: List[Question],
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
    ) -> List[Question]:
        """Filter questions based on criteria.

        Args:
            questions: Questions to filter
            type_filter: Allowed question types
            category_filter: Allowed categories
            quality_requirements: Quality constraints

        Returns:
            Filtered list of questions
        """
        filtered = questions

        # Filter by type
        if type_filter:
            filtered = [q for q in filtered if q.question_type in type_filter]

        # Filter by category
        if category_filter:
            filtered = [
                q for q in filtered
                if q.metadata.get("category", "other") in category_filter
            ]

        # Filter by quality requirements
        if quality_requirements:
            filtered = self._apply_quality_filter(filtered, quality_requirements)

        return filtered

    def _apply_quality_filter(
        self,
        questions: List[Question],
        requirements: QualityRequirements,
    ) -> List[Question]:
        """Apply quality filters to questions.

        Args:
            questions: Questions to filter
            requirements: Quality requirements

        Returns:
            Questions meeting quality requirements
        """
        from datetime import datetime, timezone, timedelta

        filtered = []
        now = datetime.now(timezone.utc)

        for question in questions:
            # Check difficulty
            if question.difficulty:
                if not (requirements.min_difficulty <= question.difficulty <= requirements.max_difficulty):
                    continue

            # Check resolution criteria
            if requirements.require_resolution_criteria:
                if not question.resolution_criteria:
                    continue

            # Check resolution date range
            if question.resolution_date:
                days_until_resolution = (question.resolution_date - now).days

                if days_until_resolution < requirements.min_resolution_days:
                    continue
                if days_until_resolution > requirements.max_resolution_days:
                    continue

            filtered.append(question)

        return filtered

    def _tag_questions_with_source(self, questions: List[Question]) -> None:
        """Tag questions with source metadata.

        Args:
            questions: Questions to tag (modified in place)
        """
        for question in questions:
            # Initialize metadata if needed
            if not hasattr(question, 'metadata') or question.metadata is None:
                question.metadata = {}

            if "source" not in question.metadata:
                question.metadata["source"] = self.source_name

    async def _enhance_with_agent(self, questions: List[Question]) -> List[Question]:
        """Use LLM agent to enhance questions with better categorization.

        This method is shared by market question sources (Polymarket, Metaculus, etc.)
        to categorize questions using an agent with the MarketQuestionEnhancerTool.

        Args:
            questions: Questions to enhance

        Returns:
            Enhanced questions with updated domain and category
        """
        from src.agents.factory import AgentFactory
        from src.pipelines.stages.tools.market_question_enhancer import MarketQuestionEnhancerTool
        from src.domain.models.domain import Domain
        from datetime import datetime, timezone
        import json

        try:
            # Create question lookup dict
            question_dict = {q.id: q for q in questions}

            # Create enhancement tool
            enhancer_tool = MarketQuestionEnhancerTool(questions=question_dict)

            # Create agent using factory
            agent = AgentFactory.create_base_agent(tools=[enhancer_tool])

            current_date = datetime.now(timezone.utc)

            # Process ONE question at a time to avoid JSON concatenation issues with Gemini
            # Gemini concatenates multiple tool calls even when asked not to
            for idx, q in enumerate(questions, 1):
                # Initialize metadata if needed
                if not hasattr(q, 'metadata') or q.metadata is None:
                    q.metadata = {}

                # Safely handle tags that might be None
                tags = q.metadata.get('tags') or []
                tags_list = tags[:5] if isinstance(tags, list) else []

                instruction = f"""Categorize this prediction market question using the market_question_enhancer tool.

Question ID: {q.id}
Question: {q.question_text}
Criteria: {q.resolution_criteria[:100] if q.resolution_criteria else 'N/A'}...
Tags: {', '.join(tags_list) if tags_list else 'none'}

Available domains: finance, tech, politics, health, climate, culture, business, sports, general

Analyze the question and call market_question_enhancer ONCE with:
- question_id: "{q.id}"
- domain: (choose the single best domain from list above)
- reasoning: (brief explanation)"""

                # Run agent on this single question
                logger.info(f"Categorizing question {idx}/{len(questions)}: {q.question_text[:50]}...")
                result = agent.run(instruction)
                logger.debug(f"Result: {str(result)[:100]}")

            logger.info(f"Agent enhancement complete: {len(question_dict)} questions categorized")

            # Questions are modified in place via the tool
            return list(question_dict.values())

        except Exception as e:
            import traceback
            logger.error(f"Agent enhancement error: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            # Return questions with default domain
            for question in questions:
                if not hasattr(question, 'domain') or question.domain is None:
                    question.domain = Domain.GENERAL
                if not hasattr(question, 'metadata') or question.metadata is None:
                    question.metadata = {}
                if "category" not in question.metadata:
                    question.metadata["category"] = "other"
            return questions
