"""Causal reasoning stage - identifies causal relationships using hindsight."""

import asyncio
from typing import List, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.pipelines.base import PipelineStage
from src.domain.models import Question, Article, CausalHypothesis, Event
from src.agents.factory import AgentFactory
from src.tools import ArticleRetrievalTool, CausalReasonerTool
from src.core.collectors import ResultCollector
from src.pipelines.prompts import HindsightAnalysisPrompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage
from src.core.database import GenericDatabase


class CausalReasoningConfig(BaseModel):
    """Configuration for causal reasoning."""

    min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept hypothesis",
    )
    min_strength: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum causal strength"
    )
    require_evidence: bool = Field(
        default=True, description="Must cite evidence articles"
    )
    max_causal_depth: int = Field(
        default=3, description="Max depth of causal graph paths"
    )
    max_related_events: int = Field(
        default=30,
        ge=1,
        description="Maximum number of related events to provide as context",
    )


class CausalReasoningStage(
    PipelineStage[Tuple[Question, List[Article]], CausalHypothesis]
):
    """Identifies causal relationships using hindsight evidence.

    This stage:
    1. Takes resolved questions paired with their evidence articles
    2. Uses LLM with hindsight to analyze what caused the outcome
    3. Extracts structured causal hypotheses with confidence scores
    4. Validates hypotheses against evidence
    """

    def __init__(
        self, config: CausalReasoningConfig, db_path: str = "worldreasoner.db"
    ):
        """Initialize causal reasoning stage.

        Args:
            config: Causal reasoning configuration
            db_path: Path to database for article retrieval
        """
        super().__init__(name="CausalReasoning", config=config)

        # Database for retrieving additional articles
        self.db = GenericDatabase(db_path)

        # Tools/agents will be created per-analysis to avoid shared-state issues
        self.article_retrieval_tool = ArticleRetrievalTool(db_path=db_path)

        # Prompt generator
        self.prompts = HindsightAnalysisPrompts()

        # Usage tracking (aggregates across all questions)
        self.usage_tracker = UsageTracker()

    async def process(
        self, inputs: List[Tuple[Question, List[Article]]]
    ) -> List[CausalHypothesis]:
        """Identify causal relationships for question-evidence pairs.

        Args:
            inputs: List of (Question, List[Article]) tuples

        Returns:
            List of causal hypotheses
        """
        logger.info(f"Identifying causal relationships for {len(inputs)} questions")

        all_hypotheses = []

        for idx, (question, evidence_articles) in enumerate(inputs, 1):
            logger.debug(f"[{idx}/{len(inputs)}] Analyzing: {question.id}")

            # Validate input
            if not evidence_articles:
                logger.warning(f"No evidence articles for {question.id}, skipping")
                continue

            if not question.resolution_date or question.ground_truth is None:
                logger.warning(
                    f"Question {question.id} not properly resolved, skipping"
                )
                continue

            # Analyze causal relationships
            try:
                hypotheses = await self._analyze_causality(question, evidence_articles)
                all_hypotheses.extend(hypotheses)
                logger.info(
                    f"Identified {len(hypotheses)} causal hypotheses for {question.id}"
                )
            except Exception as e:
                logger.error(f"Failed to analyze {question.id}: {e}")
                continue

        # Filter hypotheses by quality thresholds
        filtered = self._filter_hypotheses(all_hypotheses)
        logger.info(
            f"Generated {len(all_hypotheses)} hypotheses, {len(filtered)} passed quality filters"
        )

        # Log usage summary for this stage
        if self.usage_tracker.total_calls > 0:
            self.usage_tracker.log_summary(context="CausalReasoning")

        return filtered

    async def _analyze_causality(
        self, question: Question, evidence_articles: List[Article]
    ) -> List[CausalHypothesis]:
        """Analyze causality for a single question with evidence.

        Args:
            question: Resolved question
            evidence_articles: Evidence articles for this question

        Returns:
            List of causal hypotheses
        """
        # Create a per-analysis collector and agent to avoid cross-talk when running concurrently
        collector = ResultCollector[CausalHypothesis]()
        causal_tool = CausalReasonerTool(
            collector=collector, db_path=self.db.db_path, question_id=question.id
        )
        agent = AgentFactory.create_base_agent(
            tools=[causal_tool, self.article_retrieval_tool], is_code=True
        )

        # Load related events from database to provide valid event IDs
        # Pass evidence article IDs to filter events
        evidence_article_ids = [article.id for article in evidence_articles]
        related_events = self._load_related_events(question, evidence_article_ids)

        # Generate hindsight analysis instruction
        current_date = datetime.now(timezone.utc)
        instruction = self.prompts.get_hindsight_analysis_instruction(
            current_date=current_date,
            question=question,
            evidence_articles=evidence_articles,
            min_confidence=self.config.min_confidence,
            min_strength=self.config.min_strength,
            related_events=related_events,
            max_causal_depth=self.config.max_causal_depth,
        )

        logger.debug(f"Running causal analysis agent for {question.id}")

        try:
            # Run the agent in a thread pool to avoid blocking the event loop
            result = await asyncio.to_thread(agent.run, instruction)
            logger.debug(f"Agent completed: {result}")

            # Track token usage
            usage_metrics = agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context=f"CausalReasoning - {question.id}")
        except Exception as e:
            logger.error(f"Agent error for {question.id}: {e}")
            # Continue anyway - may have collected some hypotheses

        # Get hypotheses collected during this run
        new_hypotheses = collector.get_all()

        # Validate each hypothesis
        validated_hypotheses = []
        for hypothesis in new_hypotheses:
            if self._validate_hypothesis(hypothesis, evidence_articles):
                validated_hypotheses.append(hypothesis)
            else:
                logger.warning(
                    f"Hypothesis {hypothesis.id} failed validation "
                    f"(source: {hypothesis.source_event_id} -> target: {hypothesis.target_event_id})"
                )

        return validated_hypotheses

    def _validate_hypothesis(
        self, hypothesis: CausalHypothesis, evidence_articles: List[Article]
    ) -> bool:
        """Validate a causal hypothesis.

        Args:
            hypothesis: Hypothesis to validate
            evidence_articles: Available evidence articles

        Returns:
            True if hypothesis is valid
        """
        # Check confidence and strength thresholds
        if not hypothesis.meets_thresholds(
            min_confidence=self.config.min_confidence,
            min_strength=self.config.min_strength,
        ):
            logger.debug(
                f"Hypothesis {hypothesis.id} below thresholds "
                f"(conf: {hypothesis.confidence}, str: {hypothesis.strength})"
            )
            return False

        # Check evidence requirement
        if self.config.require_evidence and not hypothesis.has_evidence():
            logger.debug(f"Hypothesis {hypothesis.id} missing evidence citations")
            return False

        # Validate evidence article IDs exist
        available_ids = {article.id for article in evidence_articles}
        cited_ids = set(hypothesis.evidence_article_ids)

        # Check if at least one cited article is available
        if self.config.require_evidence and not cited_ids.intersection(available_ids):
            logger.debug(
                f"Hypothesis {hypothesis.id} cites unavailable articles: {cited_ids}"
            )
            return False

        # Check reasoning is substantive
        if len(hypothesis.reasoning) < 20:
            logger.debug(f"Hypothesis {hypothesis.id} has insufficient reasoning")
            return False

        return True

    def _filter_hypotheses(
        self, hypotheses: List[CausalHypothesis]
    ) -> List[CausalHypothesis]:
        """Filter hypotheses by quality and deduplication.

        Args:
            hypotheses: List of hypotheses to filter

        Returns:
            Filtered hypotheses
        """
        # Remove duplicates (same source -> target with same relation type)
        seen = set()
        unique = []

        for hypothesis in hypotheses:
            key = (
                hypothesis.source_event_id,
                hypothesis.target_event_id,
                hypothesis.relation_type,
            )

            if key in seen:
                logger.debug(f"Duplicate hypothesis: {key}")
                continue

            seen.add(key)
            unique.append(hypothesis)

        # Sort by confidence (descending)
        unique.sort(key=lambda h: h.confidence, reverse=True)

        return unique

    def _load_related_events(
        self, question: Question, evidence_article_ids: List[str] = None
    ) -> List[Event]:
        """Load events that could be potential causal sources.

        Priority order:
        1. Question's explicit target_event_id and related_event_ids
        2. Events extracted from THIS question's evidence articles
        3. Events linked to THIS question via metadata
        4. Only as last resort: same-domain events (filtered by evidence article overlap)

        Args:
            question: The question being analyzed
            evidence_article_ids: IDs of articles collected as evidence for this question

        Returns:
            List of related events ordered by recency
        """
        try:
            related_events = []
            evidence_article_ids = evidence_article_ids or []
            evidence_article_ids_set = set(evidence_article_ids)

            # Priority 1: Question's explicit event references
            explicit_event_ids = []
            if question.target_event_id:
                explicit_event_ids.append(question.target_event_id)
            explicit_event_ids.extend(question.related_event_ids or [])

            for event_id in explicit_event_ids:
                event = self.db.get(Event, event_id)
                if event:
                    related_events.append(event)
                    logger.debug(f"Added explicit event: {event_id}")

            # Priority 2 & 3: Events linked to this question via metadata or evidence articles
            all_events = self.db.get_many(Event, filters={})

            for event in all_events:
                # Skip if already added
                if event.id in explicit_event_ids:
                    continue

                # Check if event metadata references this question
                if event.metadata and question.id in event.metadata.get(
                    "related_question_ids", []
                ):
                    related_events.append(event)
                    logger.debug(f"Added question-linked event: {event.id}")
                    continue

                # Check if event is linked to any of the evidence articles
                event_article_ids = set(event.article_ids or [])
                if evidence_article_ids_set and event_article_ids.intersection(
                    evidence_article_ids_set
                ):
                    # Only include if event occurred before resolution
                    if (
                        event.occurred_date
                        and event.occurred_date < question.resolution_date
                    ):
                        related_events.append(event)
                        logger.debug(f"Added evidence-linked event: {event.id}")

            # If we have no related events, fall back to same-domain (but still filter by evidence)
            if not related_events and question.domain:
                logger.debug(
                    f"No direct event links found, falling back to domain filter: {question.domain}"
                )
                domain_events = self.db.get_many(
                    Event, filters={"domain": question.domain}
                )

                for event in domain_events:
                    # Only include if linked to evidence articles or occurred before resolution
                    event_article_ids = set(event.article_ids or [])
                    has_evidence_link = bool(
                        evidence_article_ids_set
                        and event_article_ids.intersection(evidence_article_ids_set)
                    )

                    if has_evidence_link or (
                        event.occurred_date
                        and event.occurred_date < question.resolution_date
                    ):
                        related_events.append(event)

            # Remove duplicates and sort by recency
            seen_ids = set()
            unique_events = []
            for event in related_events:
                if event.id not in seen_ids:
                    seen_ids.add(event.id)
                    unique_events.append(event)

            unique_events.sort(
                key=lambda e: e.occurred_date
                or e.predicted_date
                or datetime.now(timezone.utc),
                reverse=True,
            )
            result = unique_events[: self.config.max_related_events]

            logger.info(
                f"Loaded {len(result)} related events for question {question.id}"
            )
            return result

        except Exception as e:
            logger.warning(f"Failed to load related events: {e}")
            return []
