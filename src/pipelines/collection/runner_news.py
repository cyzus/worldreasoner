"""News-based question source runner.

Wraps the existing article -> question pipeline as a question source.
"""

from typing import List, Optional, Dict, Union

from .runner_base import QuestionSourceRunner, CollectionResult
from src.config.collection_goal import QualityRequirements
from .stage_articles import ArticleCollectionStage, ArticleCollectionConfig
from .stage_news_questions import NewsQuestionGenerationStage
from src.config.pipeline import QuestionPipelineConfig
from src.utils.logging import logger


class NewsBasedRunner(QuestionSourceRunner):
    """Question source that uses the news-based pipeline.

    This wraps the simplified two-stage pipeline:
    1. ArticleCollectionStage - Collect articles from RSS/web
    2. NewsQuestionGenerationStage - Generate questions directly from articles
    """

    def __init__(
        self,
        article_config: ArticleCollectionConfig,
        question_config: QuestionPipelineConfig,
        db_path: str,
    ):
        """Initialize news-based runner.

        Args:
            article_config: Configuration for article collection
            question_config: Configuration for question generation
            db_path: Path to database
        """
        super().__init__(source_name="news")

        self.article_config = article_config
        self.question_config = question_config
        self.db_path = db_path

        # Initialize pipeline stages
        self.article_stage = ArticleCollectionStage(article_config, db_path=db_path)
        # Event stage removed.
        # Use NewsQuestionGenerationStage for direct Article -> Question generation
        self.question_stage = NewsQuestionGenerationStage(
            question_config, article_config=article_config, db_path=db_path
        )

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
        time_horizon_hints: Optional[List[str]] = None,
    ) -> CollectionResult:
        """Collect questions from news sources.

        Runs the full article->event->question pipeline with filtering.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Dict mapping categories to number still needed
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip
            time_horizon_hints: Priority time horizons needed (e.g., ["medium"])

        Returns:
            CollectionResult with questions from news sources
        """
        try:
            logger.info(
                f"NewsBasedRunner: Collecting {count} questions "
                f"(types: {type_filter}, categories: {category_filter})"
            )
            logger.debug(
                f"NewsBasedRunner received category_filter: type={type(category_filter)}, value={category_filter}"
            )

            # Stage 1: Collect articles (filter sources by needed categories)
            logger.info("Stage 1: Collecting articles from news sources...")

            # Filter sources to match needed categories and update config domains
            sources_to_use = self.article_config.sources
            # Use 'is not None' instead of truthy check to handle empty dicts
            if category_filter is not None:
                if isinstance(category_filter, dict):
                    filter_keys = list(category_filter.keys())
                else:
                    filter_keys = list(category_filter) if category_filter else []

                # Only filter sources if we have specific categories to target
                if filter_keys:
                    filtered_sources = [
                        source
                        for source in self.article_config.sources
                        if source.domain in filter_keys
                    ]
                    if filtered_sources:
                        sources_to_use = filtered_sources
                        # Update the article stage config to focus on missing domains
                        self.article_stage.config.domains = filter_keys
                        logger.info(
                            f"Filtering to {len(sources_to_use)} sources matching categories: {filter_keys}"
                        )
                    else:
                        logger.warning(
                            f"No sources match categories {filter_keys}, using all sources"
                        )
                else:
                    # Empty dict/list means no gaps - don't filter sources but clear domains
                    logger.debug(
                        "Empty category_filter - no specific categories needed"
                    )
                    self.article_stage.config.domains = []

            article_result = await self.article_stage.execute(
                sources_to_use, category_filter=category_filter
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
            # Filter articles by category if hints provided
            if category_filter is not None and articles:
                if isinstance(category_filter, dict):
                    filter_keys = list(category_filter.keys())
                else:
                    filter_keys = list(category_filter) if category_filter else []

                # Only filter if we have specific categories
                if filter_keys:
                    filtered_articles = [
                        article for article in articles if article.domain in filter_keys
                    ]
                    if filtered_articles:
                        logger.info(
                            f"Filtered to {len(filtered_articles)} articles matching categories: {filter_keys}"
                        )
                        articles = filtered_articles
                    else:
                        logger.warning(
                            f"No articles match categories {filter_keys}, keeping all {len(articles)} articles"
                        )

            # Stage 2: Generate questions directly from articles
            logger.info("Stage 2: Generating questions from articles...")

            # Pass type/category hints to guide generation intelligently
            # Create new stage instance with hints for this specific run
            question_stage_with_hints = NewsQuestionGenerationStage(
                self.question_config,
                article_config=self.article_config,
                db_path=self.db_path,
                type_hints=type_filter,  # Tell agent which types we need
                category_hints=category_filter,  # Tell agent which categories we need
                time_horizon_hints=time_horizon_hints,  # Tell agent which time horizons we need
                existing_question_ids=existing_question_ids,  # Skip duplicates early
                target_count=count,  # Tell stage exactly how many questions we need
            )

            # Use article_batch_size for processing articles
            question_result = await question_stage_with_hints.execute_batched(
                articles, batch_size=self.question_config.article_batch_size or 10
            )

            if not question_result.outputs:
                logger.warning("No questions generated from articles")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=False,
                    error_message="No questions generated from articles",
                )

            questions = question_result.outputs
            logger.info(f"Generated {len(questions)} questions")

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

            # Note: filtered_questions should already be <= count since we passed target_count
            # to QuestionGenerationStage. Just use them as-is (no slicing needed).
            final_questions = filtered_questions

            # Note: Bidirectional event<->question links are now handled by BatchQuestionGeneratorTool
            # The tool updates event.metadata['related_question_ids'] when creating questions

            return CollectionResult(
                source_name=self.source_name,
                questions=final_questions,
                requested_count=count,
                actual_count=len(final_questions),
                success=True,
                metadata={
                    "articles_collected": len(articles),
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
