"""News-based question generation stage (Articles -> Questions)."""

from typing import List, Optional
from datetime import datetime, timezone

from src.pipelines.base import PipelineStage
from src.domain.models import Article, Question
from src.config.pipeline import QuestionPipelineConfig
from src.agents.factory import AgentFactory
from src.tools import QuestionGeneratorTool, ArticleRetrievalTool
from src.core.collectors import ResultCollector
from src.pipelines.prompts import question_generation as question_generation_prompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class NewsQuestionGenerationStage(PipelineStage[Article, Question]):
    """Generates forecast questions directly from articles (skipping event object creation).

    This streamlines the news pipeline: Articles -> [LLM] -> Questions.
    The LLM implicitly identifies events and deduplicates them during question generation.
    """

    def __init__(
        self,
        config: QuestionPipelineConfig,
        article_config: Optional["ArticleCollectionConfig"] = None,
        db_path: Optional[str] = None,
        type_hints: Optional[List[str]] = None,
        category_hints: Optional[List[str]] = None,
        time_horizon_hints: Optional[List[str]] = None,
        existing_question_ids: Optional[set] = None,
        target_count: Optional[int] = None,
    ):
        super().__init__(name="NewsQuestionGeneration", config=config)

        # Store db_path for tools
        self.db_path = db_path

        # Store article config for sources
        self.article_config = article_config

        # Store hints for intelligent generation
        self.type_hints = type_hints
        self.category_hints = category_hints
        self.time_horizon_hints = time_horizon_hints
        self.existing_question_ids = existing_question_ids or set()
        self.target_count = target_count

        # Create result collector
        self.collector = ResultCollector[Question]()

        # Create batch question tool
        self.question_tool = QuestionGeneratorTool(
            collector=self.collector,
            require_ground_truth=config.require_ground_truth,
            existing_question_ids=self.existing_question_ids,
        )

        self.article_retrieval_tool = ArticleRetrievalTool(db_path=db_path)

        self.base_agent = None

        # Usage tracking
        self.usage_tracker = UsageTracker()

    async def process(self, inputs: List[Article]) -> List[Question]:
        """Generate forecast questions from articles.

        Args:
            inputs: List of articles to analyze and generate questions from

        Returns:
            List of NEW questions generated in this batch only
        """
        if not inputs:
            return []

        # Early exit if we already have enough questions
        max_questions = (
            self.target_count
            if self.target_count is not None
            else (self.config.max_questions or 10)
        )
        current_count = len(self.collector.get_all())

        if current_count >= max_questions:
            logger.info(
                f"Already collected {current_count}/{max_questions} questions, skipping batch"
            )
            return []

        remaining_needed = max_questions - current_count

        # Snapshot collector size before this batch so we can return only new items
        count_before = len(self.collector.get_all())

        try:
            # Get current date for context
            current_date = datetime.now(timezone.utc)

            # Determine target domains
            target_domains = (
                self.category_hints if self.category_hints else self.config.domains
            )

            # Filter articles by domain if target_domains is specified
            if target_domains:
                filtered_articles = [
                    article
                    for article in inputs
                    if article.domain.value in target_domains
                ]
                logger.info(
                    f"Filtered {len(inputs)} articles to {len(filtered_articles)} matching domains: {target_domains}"
                )
            else:
                filtered_articles = inputs

            # Apply batch size limit if needed (though batching is usually handled by caller/pipeline)
            # For articles, we might want to cap explicitly to avoid token limits
            max_batch = 15  # Reasonable limit for article summaries in context
            if len(filtered_articles) > max_batch:
                logger.info(
                    f"Capping inputs to {max_batch} articles from {len(filtered_articles)}"
                )
                filtered_articles = filtered_articles[:max_batch]

            if not filtered_articles:
                logger.warning("No articles remain after filtering")
                return []

            # Create agent using factory (only needs question tool)
            self.base_agent = AgentFactory.create_web_agent(
                tools=[self.question_tool, self.article_retrieval_tool],
                is_code=True,
                max_steps=20,
            )

            # Extract sources if available
            sources_list = []
            if self.article_config and self.article_config.sources:
                sources_list = [s.name for s in self.article_config.sources]

            instruction = question_generation_prompts.get_article_instruction(
                current_date=current_date,
                articles=filtered_articles,
                max_questions=remaining_needed,
                domains=target_domains,
                sources=sources_list,  # NEW: Pass trusted sources
                require_ground_truth=self.config.require_ground_truth,
                type_hints=self.type_hints,
                category_hints=self.category_hints,
                time_horizon_hints=self.time_horizon_hints,
            )

            # Run the agent
            result = self.base_agent.run(instruction)

            # Track usage
            usage_metrics = self.base_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context="NewsQuestionGeneration")

            # Agent's response is just a summary
            logger.debug(
                f"Agent response: {result[:200] if isinstance(result, str) else result}"
            )

            # Get only the NEW questions generated in this batch
            all_questions = self.collector.get_all()
            new_questions = all_questions[count_before:]

            if self.usage_tracker.total_calls > 0:
                self.usage_tracker.log_summary(context="NewsQuestionGeneration")

            return new_questions

        except Exception as e:
            logger.error(f"Error generating questions from articles: {e}")
            return []
