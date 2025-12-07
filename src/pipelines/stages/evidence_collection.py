"""Hindsight evidence collection stage for Evidence Pipeline."""

import asyncio
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field, model_validator

from src.pipelines.base import PipelineStage
from src.domain.models import Question, Article, Event
from src.agents.factory import AgentFactory
from src.tools import BatchArticleCollectorTool, BatchEventIdentifierTool, ArticleRetrievalTool
from src.core.collectors import ResultCollector
from src.pipelines.prompts import HindsightAnalysisPrompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class EvidenceCollectionConfig(BaseModel):
    """Configuration for evidence collection."""

    evidence_window_days: int = Field(
        default=30,
        ge=1,
        description="Days before resolution to collect evidence (causal factors)"
    )
    # Optional explicit window bounds (if provided they take precedence)
    evidence_start_date: Optional[datetime] = Field(
        default=None,
        description="Optional explicit start date for evidence collection (ISO datetime). If set, overrides default start calculation."
    )
    evidence_end_date: Optional[datetime] = Field(
        default=None,
        description="Optional explicit end date for evidence collection (ISO datetime). If set, overrides default end calculation."
    )
    min_evidence_articles: int = Field(
        default=5,
        description="Minimum articles to collect per question"
    )
    include_expert_analysis: bool = Field(
        default=True,
        description="Prioritize analysis articles discussing causal factors"
    )
    # Minimum days since resolution to allow evidence collection for a question
    min_resolution_age_days: int = Field(
        default=1,
        ge=0,
        description="Minimum days since resolution required to collect evidence for a question (0 = allow same-day)"
    )

    @model_validator(mode='after')
    def check_start_end(self):
        """Validate that evidence_end_date is not before evidence_start_date at config time.

        This is a config-level validation: it cannot know per-question resolution dates,
        but it ensures the configured explicit window bounds are consistent.
        """
        start = self.evidence_start_date
        end = self.evidence_end_date
        if start is not None and end is not None and end < start:
            raise ValueError('evidence_end_date must be the same or after evidence_start_date')
        return self


class HindsightEvidenceCollectionStage(PipelineStage[Question, Article]):
    """Collects evidence articles published BEFORE event resolution.

    This stage uses hindsight (knowing the outcome) to intelligently search
    for and identify articles from BEFORE the event that discussed the
    factors that actually caused the outcome.

    Key concept:
    - We have HINDSIGHT (know the outcome that occurred on resolution_date)
    - We search articles from BEFORE resolution_date
    - We look for factors that were present/discussed before the event
    - These pre-event factors are the potential causes we want to identify
    """

    def __init__(
        self,
        config: EvidenceCollectionConfig,
        db_path: str = "worldreasoner.db"
    ):
        """Initialize hindsight evidence collection stage.

        Args:
            config: Evidence collection configuration
            db_path: Path to database for deduplication
        """
        super().__init__(name="HindsightEvidenceCollection", config=config)

        self.db_path = db_path

        # Note: Tools/collectors/agents are instantiated per-question to avoid
        # shared mutable state when this stage is executed concurrently.

        # Prompt generators
        self.hindsight_prompts = HindsightAnalysisPrompts()

        # Usage tracking (aggregates across all questions)
        self.usage_tracker = UsageTracker()

    async def process(self, inputs: List[Question]) -> List[Article]:
        """Collect hindsight evidence for resolved questions.

        Args:
            inputs: List of resolved questions

        Returns:
            List of evidence articles collected
        """
        logger.info(f"Collecting hindsight evidence for {len(inputs)} resolved questions")

        all_articles = []

        for idx, question in enumerate(inputs, 1):
            logger.info(f"[{idx}/{len(inputs)}] Processing question: {question.id}")

            # Validate question is resolved
            if not question.resolution_date:
                logger.warning(f"Question {question.id} has no resolution_date, skipping")
                continue

            if question.ground_truth is None:
                logger.warning(f"Question {question.id} has no ground_truth, skipping")
                continue

            # Check if resolution is too recent (allow time for analysis to be published)
            days_since_resolution = (datetime.now(timezone.utc) - question.resolution_date).days
            if days_since_resolution < self.config.min_resolution_age_days:
                logger.info(
                    f"Question {question.id} resolved too recently ({days_since_resolution} days), skipping (min required: {self.config.min_resolution_age_days}d)"
                )
                continue

            # Collect evidence for this question
            try:
                articles = await self._collect_evidence_for_question(question)
                all_articles.extend(articles)
                logger.info(f"Collected {len(articles)} evidence articles for {question.id}")
            except Exception as e:
                logger.error(f"Failed to collect evidence for {question.id}: {e}")
                continue

        logger.info(f"Collected total of {len(all_articles)} evidence articles")

        # Log usage summary for this stage
        if self.usage_tracker.total_calls > 0:
            self.usage_tracker.log_summary(context="HindsightEvidenceCollection")

        return all_articles

    async def _collect_evidence_for_question(self, question: Question) -> List[Article]:
        """Collect evidence articles for a single resolved question.

        Args:
            question: Resolved question

        Returns:
            List of evidence articles
        """
        # Instantiate per-question collector, tool, and agent to avoid cross-talk
        article_collector = ResultCollector[Article]()
        article_tool = BatchArticleCollectorTool(
            db_path=self.db_path,
            collector=article_collector,
            default_domain=(question.domain.value if hasattr(question.domain, 'value') and question.domain else 'general')
        )
        web_agent = AgentFactory.create_web_agent(tools=[article_tool])

        # Generate evidence collection instruction including temporal guidance
        current_date = datetime.now(timezone.utc)

        # Compute evidence window using helper (keeps logic testable)
        start_date, end_date = self._compute_evidence_window(question)

        # Let the prompt generator include the temporal guidance (centralized in prompts)
        full_instruction = self.hindsight_prompts.get_evidence_collection_instruction(
            current_date=current_date,
            question=question,
            min_articles=self.config.min_evidence_articles,
            start_date=start_date,
            end_date=end_date,
            evidence_window_days=self.config.evidence_window_days,
        )

        logger.debug(f"Running evidence collection agent for {question.id}")

        try:
            # Run the agent in a thread pool to avoid blocking the event loop
            result = await asyncio.to_thread(web_agent.run, full_instruction)
            logger.debug(f"Agent completed: {result}")

            # Track token usage
            usage_metrics = web_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context=f"EvidenceCollection - {question.id}")
        except Exception as e:
            logger.error(f"Agent error for {question.id}: {e}")
            # Continue anyway - may have collected some articles

        # Get articles collected during this run (isolated collector)
        new_articles = article_collector.get_all()

        # Tag articles with provenance and persist updates
        if new_articles:
            from src.core.database import GenericDatabase
            db = GenericDatabase(self.db_path)

            for article in new_articles:
                # Set explicit provenance field (indexed, queryable)
                article.collected_for_question_id = question.id

                # Also store in metadata for backward compatibility
                article.metadata['evidence_type'] = 'hindsight'
                article.metadata['related_question_ids'] = [question.id]

                # Link to target event if possible
                if question.target_event_id and question.target_event_id not in article.event_ids:
                    article.event_ids.append(question.target_event_id)

                # Persist updated article with provenance and event links
                try:
                    db.save(Article, article)
                    logger.debug(f"Updated article {article.id} with question provenance")
                except Exception as e:
                    logger.warning(f"Failed to update article {article.id}: {e}")

        # Extract intermediate events from articles using LLM
        await self._extract_events_from_articles(new_articles, question)
        logger.info(f"Extracted intermediate events from {len(new_articles)} articles for {question.id}")

        return new_articles

    def _compute_evidence_window(self, question: Question):
        """Compute (start_date, end_date) for evidence collection based on config and question.

        Rules:
        - If config provides both explicit start/end, use them (config-level validation ensures end >= start).
        - If config provides start only, compute end = start + (evidence_window_days - 1), capped at resolution-1.
        - If no explicit start, anchor end = resolution - 1 and start = resolution - evidence_window_days.
        - After computing, clamp end to resolution-1 if it is on/after resolution, and ensure end >= start.
        """
        # Read optional start/end from config (prefer datetimes; pydantic will parse ISO strings)
        start_dt = self.config.evidence_start_date
        end_dt = self.config.evidence_end_date

        # Resolution-based candidate end (must be at least one day prior to resolution)
        resolution_minus_one = question.resolution_date - timedelta(days=1)

        if start_dt and end_dt:
            start_date = start_dt
            end_date = end_dt
        elif start_dt and not end_dt:
            start_date = start_dt
            end_date = start_dt + timedelta(days=self.config.evidence_window_days - 1)
            if end_date > resolution_minus_one:
                logger.debug(
                    f"Computed end_date {end_date.isoformat()} exceeds resolution-1 {resolution_minus_one.isoformat()} for question {question.id}; capping to resolution-1"
                )
                end_date = resolution_minus_one
        else:
            # No explicit start provided in config: anchor to resolution
            end_date = resolution_minus_one
            start_date = question.resolution_date - timedelta(days=self.config.evidence_window_days)

        # If end_date is on/after resolution_date, clamp to resolution_minus_one
        if end_date >= question.resolution_date:
            logger.warning(
                f"Evidence end_date {end_date.isoformat()} is on/after resolution_date {question.resolution_date.isoformat()} for question {question.id}; clamping to resolution-1"
            )
            end_date = resolution_minus_one

        # Ensure end_date is not before start_date
        if end_date < start_date:
            logger.warning(
                f"Computed end_date {end_date.isoformat()} is before start_date {start_date.isoformat()} for question {question.id}; clamping end_date to start_date"
            )
            end_date = start_date

        return start_date, end_date

    async def _extract_events_from_articles(self, articles: List[Article], question: Question) -> None:
        """Extract intermediate events from articles using LLM agent.

        The agent analyzes articles and uses the event_identifier tool to extract
        significant events that could serve as causal sources.

        Args:
            articles: Evidence articles to extract events from
            question: The question context (for domain and metadata)
        """
        if not articles:
            return

        # Instantiate per-question event collector, tool, and agent
        event_collector = ResultCollector[Event]()
        event_tool = BatchEventIdentifierTool(collector=event_collector, db_path=self.db_path)
        article_retrieval_tool = ArticleRetrievalTool(db_path=self.db_path)
        event_agent = AgentFactory.create_base_agent(tools=[event_tool, article_retrieval_tool])

        # Generate event extraction instruction using centralized prompt
        current_date = datetime.now(timezone.utc)
        instruction = self.hindsight_prompts.get_evidence_extraction_instruction(
            current_date=current_date,
            articles=articles,
            question_domain=question.domain or "general"
        )

        logger.debug(f"Running event extraction agent for {len(articles)} articles")

        try:
            # Run the agent in a thread pool to avoid blocking the event loop
            result = await asyncio.to_thread(event_agent.run, instruction)
            logger.debug(f"Event extraction agent completed: {result}")

            # Track token usage
            usage_metrics = event_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context=f"EventExtraction - {question.id}")
        except Exception as e:
            logger.warning(f"Event extraction agent error: {e}")
            # Continue anyway - may have collected some events

        # Get events collected during this run
        new_events = event_collector.get_all()

        # Persist extracted events to database
        if new_events:
            from src.core.database import GenericDatabase
            db = GenericDatabase(self.db_path)

            for event in new_events:
                # Set explicit provenance field (indexed, queryable)
                event.extracted_for_question_id = question.id

                # Link to source article if possible (first article in event's article_ids)
                if event.article_ids:
                    event.source_article_id = event.article_ids[0]

                # Also store in metadata for backward compatibility
                if 'related_question_ids' not in event.metadata:
                    event.metadata['related_question_ids'] = []
                if question.id not in event.metadata['related_question_ids']:
                    event.metadata['related_question_ids'].append(question.id)
                event.metadata['extracted_for_evidence'] = True

                # Save event to database
                try:
                    db.save(Event, event)
                    logger.debug(f"Persisted extracted event: {event.id}")
                except Exception as e:
                    logger.warning(f"Failed to persist event {event.id}: {e}")

            logger.info(f"Extracted and persisted {len(new_events)} intermediate events")
