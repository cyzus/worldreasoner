"""Base abstraction for question sources.

Defines the interface that all question sources must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Union
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
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from this source.

        Args:
            count: Target number of questions to collect
            type_filter: Only collect these question types (e.g., ["boolean", "mcq"])
            category_filter: Dict mapping categories to number still needed (e.g., {"finance": 1, "tech": 2})
            quality_requirements: Quality constraints for collected questions
            existing_question_ids: Set of existing IDs to skip (for deduplication)

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
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
    ) -> List[Question]:
        """Filter questions based on criteria.

        Args:
            questions: Questions to filter
            type_filter: Allowed question types
            category_filter: Dict mapping allowed categories to number needed
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
            allowed_categories = category_filter.keys()
            filtered = [
                q for q in filtered
                if q.metadata.get("category", "other") in allowed_categories
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

        skip_difficulty = 0
        skip_criteria = 0
        skip_date_too_old = 0
        skip_date_too_recent = 0

        for question in questions:
            # Check difficulty
            if question.difficulty:
                if not (requirements.min_difficulty <= question.difficulty <= requirements.max_difficulty):
                    skip_difficulty += 1
                    continue

            # Check resolution criteria
            if requirements.require_resolution_criteria:
                if not question.resolution_criteria:
                    skip_criteria += 1
                    continue

            # Check resolution date range
            # Skip date filtering for questions with ground truth (already resolved)
            has_ground_truth = question.ground_truth is not None
            if question.resolution_date and not has_ground_truth:
                days_until_resolution = (question.resolution_date - now).days

                if days_until_resolution < requirements.min_resolution_days:
                    skip_date_too_old += 1
                    logger.debug(f"Filtered {question.id}: too old ({days_until_resolution} days < {requirements.min_resolution_days})")
                    continue
                if days_until_resolution > requirements.max_resolution_days:
                    skip_date_too_recent += 1
                    logger.debug(f"Filtered {question.id}: too recent ({days_until_resolution} days > {requirements.max_resolution_days})")
                    continue

            filtered.append(question)

        if questions:
            logger.info(f"Quality filter: {len(filtered)}/{len(questions)} kept, skipped: {skip_difficulty} difficulty, {skip_criteria} criteria, {skip_date_too_old} too old, {skip_date_too_recent} too recent")

        return filtered

    def _tag_questions_with_source(self, questions: List[Question]) -> None:
        """Tag questions with source metadata.

        Args:
            questions: Questions to tag (modified in place)
        """
        for question in questions:
            # Set the source field on the question
            question.source = self.source_name

            # Initialize metadata if needed
            if not hasattr(question, 'metadata') or question.metadata is None:
                question.metadata = {}

            if "source" not in question.metadata:
                question.metadata["source"] = self.source_name

            # Set category from domain for progress tracking
            if "category" not in question.metadata:
                question.metadata["category"] = question.domain.value

    async def _enhance_with_agent(self, questions: List[Question]) -> List[Question]:
        """Use LLM to enhance questions with better categorization.

        Uses direct LLM with batching for speed.

        Args:
            questions: Questions to enhance

        Returns:
            Enhanced questions with updated domain and category
        """
        from src.domain.models.domain import Domain
        from src.llm import LiteLLMClient
        from src.config import get_config
        from src.pipelines.prompts import QuestionCategorizationPrompts
        from src.utils.llm_utils import parse_json_response

        try:
            # Get LLM config and create client
            config = get_config()
            llm_client = LiteLLMClient(config.llm.model_dump(exclude_none=True))

            # Create prompt generator
            prompt_generator = QuestionCategorizationPrompts()

            # Batch categorize - 10 questions at a time for speed
            batch_size = 10

            for batch_idx in range(0, len(questions), batch_size):
                batch = questions[batch_idx:batch_idx + batch_size]

                # Generate prompt using the prompt generator
                prompt = prompt_generator.get_instruction(questions=batch)

                logger.info(f"Categorizing batch {batch_idx//batch_size + 1} ({len(batch)} questions)...")

                # Call LLM with structured JSON output
                messages = [{"role": "user", "content": prompt}]
                response_text = await llm_client.acomplete(
                    messages=messages,
                    response_format={"type": "json_object"}
                )

                # Parse JSON response using utility
                response_json = parse_json_response(response_text)

                # Handle both array and object formats
                if isinstance(response_json, list):
                    categorizations = response_json
                elif isinstance(response_json, dict) and "categorizations" in response_json:
                    categorizations = response_json["categorizations"]
                else:
                    categorizations = response_json

                # Apply categorizations
                cat_dict = {c['id']: c['domain'] for c in categorizations}

                for q in batch:
                    if q.id in cat_dict:
                        domain_str = cat_dict[q.id]
                        try:
                            q.domain = Domain(domain_str)
                            if not hasattr(q, 'metadata') or q.metadata is None:
                                q.metadata = {}
                            q.metadata["category"] = domain_str
                        except ValueError:
                            logger.warning(f"Invalid domain '{domain_str}' for {q.id}, using general")
                            q.domain = Domain.GENERAL
                            q.metadata["category"] = "general"

            logger.info(f"Batch categorization complete: {len(questions)} questions")
            return questions

        except Exception as e:
            import traceback
            logger.error(f"Categorization error: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            # Return questions with default domain
            for question in questions:
                if not hasattr(question, 'domain') or question.domain is None:
                    question.domain = Domain.GENERAL
                if not hasattr(question, 'metadata') or question.metadata is None:
                    question.metadata = {}
                if "category" not in question.metadata:
                    question.metadata["category"] = "general"
            return questions
