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
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from this source.

        Args:
            count: Target number of questions to collect
            type_filter: Only collect these question types (e.g., ["boolean", "mcq"])
            category_filter: Only collect these categories (e.g., ["finance", "tech"])
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
        import json

        try:
            # Get LLM config and create client
            config = get_config()
            llm_client = LiteLLMClient(config.llm.model_dump(exclude_none=True))

            # Batch categorize - 10 questions at a time for speed
            batch_size = 10

            for batch_idx in range(0, len(questions), batch_size):
                batch = questions[batch_idx:batch_idx + batch_size]

                # Build batch prompt
                questions_text = []
                for idx, q in enumerate(batch, 1):
                    tags = q.metadata.get('tags', []) if hasattr(q, 'metadata') and q.metadata else []
                    tags_list = tags[:3] if isinstance(tags, list) else []
                    questions_text.append(
                        f"{idx}. ID: {q.id}\n"
                        f"   Q: {q.question_text}\n"
                        f"   Tags: {', '.join(tags_list) if tags_list else 'none'}"
                    )

                prompt = f"""Categorize these prediction market questions into domains.

Questions:
{chr(10).join(questions_text)}

Available domains: finance, tech, politics, health, climate, culture, business, sports, general

Return JSON array with format:
[{{"id": "question_id", "domain": "domain_name"}}, ...]

Only return the JSON array, nothing else."""

                logger.info(f"Categorizing batch {batch_idx//batch_size + 1} ({len(batch)} questions)...")

                # Call LLM
                messages = [{"role": "user", "content": prompt}]
                response_text = await llm_client.acomplete(messages)
                response_text = response_text.strip()

                # Parse response
                # Remove markdown code blocks if present
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                    response_text = response_text.strip()

                categorizations = json.loads(response_text)

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
