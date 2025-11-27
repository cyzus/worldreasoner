"""News-based question source runner.

Wraps the existing article → event → question pipeline as a question source.
"""

from typing import List, Optional
from datetime import datetime, timezone

from .base import QuestionSourceRunner, CollectionResult
from src.domain.models import Question
from src.config.collection_goal import QualityRequirements
from src.pipelines.stages import (
    ArticleCollectionStage,
    ArticleCollectionConfig,
    EventIdentificationStage,
    EventIdentificationConfig,
    QuestionGenerationStage,
    DatabasePersistenceStage,
    DatabasePersistenceConfig,
)
from src.config.pipeline import QuestionPipelineConfig
from src.utils.logging import logger


class NewsBasedRunner(QuestionSourceRunner):
    """Question source that uses the news-based pipeline.

    This wraps the existing three-stage pipeline:
    1. ArticleCollectionStage - Collect articles from RSS/web
    2. EventIdentificationStage - Extract events from articles
    3. QuestionGenerationStage - Generate questions from events
    """

    def __init__(
        self,
        article_config: ArticleCollectionConfig,
        event_config: EventIdentificationConfig,
        question_config: QuestionPipelineConfig,
        db_path: str,
    ):
        """Initialize news-based runner.

        Args:
            article_config: Configuration for article collection
            event_config: Configuration for event identification
            question_config: Configuration for question generation
            db_path: Path to database
        """
        super().__init__(source_name="news")

        self.article_config = article_config
        self.event_config = event_config
        self.question_config = question_config
        self.db_path = db_path

        # Initialize pipeline stages
        self.article_stage = ArticleCollectionStage(article_config, db_path=db_path)
        self.event_stage = EventIdentificationStage(event_config, db_path=db_path)
        self.question_stage = QuestionGenerationStage(question_config, db_path=db_path)

        # Initialize persistence stages
        persist_config = DatabasePersistenceConfig(
            db_path=db_path,
            batch_size=50
        )
        self.article_persist = DatabasePersistenceStage(persist_config, "article")
        self.event_persist = DatabasePersistenceStage(persist_config, "event")

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from news sources.

        Runs the full article→event→question pipeline with filtering.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Only collect these categories
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip

        Returns:
            CollectionResult with questions from news sources
        """
        try:
            logger.info(
                f"NewsBasedRunner: Collecting {count} questions "
                f"(types: {type_filter}, categories: {category_filter})"
            )

            # Stage 1: Collect articles
            logger.info("Stage 1: Collecting articles from news sources...")
            article_result = await self.article_stage.execute(
                self.article_config.sources
            )

            if not article_result.outputs:
                logger.warning("No articles collected")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=False,
                    error_message="No articles collected from news sources",
                )

            articles = article_result.outputs
            logger.info(f"Collected {len(articles)} articles")

            # Persist articles
            if articles:
                await self.article_persist.execute(articles)

            # Stage 2: Identify events
            logger.info("Stage 2: Identifying events from articles...")
            event_result = await self.event_stage.execute_batched(
                articles,
                batch_size=self.question_config.article_batch_size
            )

            if not event_result.outputs:
                logger.warning("No events identified from articles")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=False,
                    error_message="No events identified from articles",
                )

            events = event_result.outputs
            logger.info(f"Identified {len(events)} events")

            # Persist events
            if events:
                await self.event_persist.execute(events)

            # Re-persist articles to save event links
            if articles:
                await self.article_persist.execute(articles)

            # Stage 3: Generate questions
            logger.info("Stage 3: Generating questions from events...")
            question_result = await self.question_stage.execute_batched(
                events,
                batch_size=self.question_config.event_batch_size
            )

            if not question_result.outputs:
                logger.warning("No questions generated from events")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=False,
                    error_message="No questions generated from events",
                )

            questions = question_result.outputs
            logger.info(f"Generated {len(questions)} questions")

            # Update events with question links (bidirectional relationship)
            # Questions already have target_event_id and related_event_ids
            # Now add the reverse direction: events pointing to questions
            event_map = {event.id: event for event in events}

            for question in questions:
                # Add this question to all related events
                for event_id in question.related_event_ids:
                    if event_id in event_map:
                        event = event_map[event_id]
                        if 'related_question_ids' not in event.metadata:
                            event.metadata['related_question_ids'] = []
                        if question.id not in event.metadata['related_question_ids']:
                            event.metadata['related_question_ids'].append(question.id)
                            logger.debug(f"Linked event {event_id} to question {question.id}")

            # Re-persist events to save updated question links
            if events:
                await self.event_persist.execute(events)

            # Tag questions with source
            self._tag_questions_with_source(questions)

            # Apply filters
            filtered_questions = self._filter_questions(
                questions,
                type_filter=type_filter,
                category_filter=category_filter,
                quality_requirements=quality_requirements,
            )

            logger.info(
                f"After filtering: {len(filtered_questions)} questions "
                f"(from {len(questions)} total)"
            )

            # Return up to 'count' questions
            final_questions = filtered_questions[:count]

            return CollectionResult(
                source_name=self.source_name,
                questions=final_questions,
                requested_count=count,
                actual_count=len(final_questions),
                success=True,
                metadata={
                    "articles_collected": len(articles),
                    "events_identified": len(events),
                    "questions_generated": len(questions),
                    "questions_after_filter": len(filtered_questions),
                },
            )

        except Exception as e:
            logger.error(f"NewsBasedRunner error: {e}")
            return CollectionResult(
                source_name=self.source_name,
                questions=[],
                requested_count=count,
                actual_count=0,
                success=False,
                error_message=str(e),
            )

    async def can_provide(
        self,
        question_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        """Check if news sources can provide questions of given type/category.

        Args:
            question_type: Question type to check
            category: Category to check

        Returns:
            True (news sources can provide all types/categories)
        """
        # News sources can potentially provide any type of question
        # depending on what's in the news
        return True
