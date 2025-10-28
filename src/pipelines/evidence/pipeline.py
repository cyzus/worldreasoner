"""Evidence generation pipeline for WorldReasoner.

This pipeline builds causal explanations with hindsight:
1. Collect evidence articles AFTER outcomes are known (per question)
2. Identify causal relationships using hindsight (per question)
3. Build validated causal graphs

Uses async processing with per-question analysis to preserve context and enable parallelism.
"""

import asyncio
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from ..base import Pipeline, PipelineStageResult, PipelineStageStatus
from ..stages import (
    DatabasePersistenceStage,
    DatabasePersistenceConfig,
    HindsightEvidenceCollectionStage,
    EvidenceCollectionConfig,
    CausalReasoningStage,
    CausalReasoningConfig,
    CausalGraphBuildingStage,
    CausalGraphConfig,
)
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig
from src.domain.models import Question, Article, CausalHypothesis, Event
from src.core.database import GenericDatabase
from src.utils.logging import logger


class EvidencePipeline(Pipeline):
    """Pipeline for building causal explanations with hindsight.

    Flow: Resolved Questions → Evidence Articles → Causal Hypotheses → Enhanced Events

    This pipeline:
    - Collects evidence articles AFTER outcomes are known
    - Uses hindsight to identify true causal factors
    - Builds validated causal graphs
    - Creates ground truth explanations for evaluation
    """

    def __init__(
        self,
        evidence_config: EvidencePipelineConfig,
        database_config: DatabaseConfig,
        enable_persistence: bool = True,
        max_concurrent_questions: int = 3,
    ):
        """Initialize the evidence pipeline.

        Args:
            evidence_config: Configuration for evidence pipeline
            database_config: Database connection configuration
            enable_persistence: Whether to save to database
            max_concurrent_questions: Max number of questions to process in parallel (default: 3)
        """
        super().__init__(name="EvidencePipeline")

        self.evidence_config = evidence_config
        self.database_config = database_config
        self.enable_persistence = enable_persistence
        self.max_concurrent_questions = max_concurrent_questions

        # Semaphore to limit concurrent question processing
        self.semaphore = asyncio.Semaphore(max_concurrent_questions)

        db_path = database_config.db_path

        # Stage 1: Hindsight Evidence Collection
        evidence_collection_config = EvidenceCollectionConfig(
            evidence_window_days=evidence_config.evidence_window_days,
            min_evidence_articles=evidence_config.min_evidence_articles,
            include_expert_analysis=evidence_config.include_expert_analysis,
            min_resolution_age_days=evidence_config.min_resolution_age_days,
        )
        self.evidence_stage = HindsightEvidenceCollectionStage(
            evidence_collection_config,
            db_path=db_path
        )

        # Stage 2: Causal Reasoning
        causal_reasoning_config = CausalReasoningConfig(
            min_confidence=evidence_config.causal_confidence_threshold,
            min_strength=evidence_config.causal_strength_threshold,
            require_evidence=evidence_config.require_evidence,
            max_causal_depth=evidence_config.max_causal_depth,
        )
        self.reasoning_stage = CausalReasoningStage(
            causal_reasoning_config,
            db_path=db_path
        )

        # Stage 3: Causal Graph Building
        graph_config = CausalGraphConfig(
            allow_cycles=evidence_config.allow_causal_cycles,
            validate_temporal_ordering=evidence_config.validate_temporal_ordering,
            max_links_per_event=evidence_config.max_links_per_event,
        )
        self.graph_stage = CausalGraphBuildingStage(
            graph_config,
            db_path=db_path
        )

        # Add stages
        self.add_stage(self.evidence_stage)
        self.add_stage(self.reasoning_stage)
        self.add_stage(self.graph_stage)

        # Persistence stages
        if enable_persistence:
            persist_config = DatabasePersistenceConfig(
                batch_size=database_config.batch_size,
                db_path=db_path
            )
            self.article_persist = DatabasePersistenceStage(persist_config, "article")
            self.hypothesis_persist = DatabasePersistenceStage(persist_config, "causal_hypothesis")
            self.event_persist = DatabasePersistenceStage(persist_config, "event")

        # Storage for pipeline outputs
        self.resolved_questions: List[Question] = []
        self.evidence_articles: List[Article] = []
        self.causal_hypotheses: List[CausalHypothesis] = []
        self.enhanced_events: List[Event] = []

    async def run(
        self,
        resolved_questions: Optional[List[Question]] = None
    ) -> List[PipelineStageResult]:
        """Run the evidence pipeline with per-question async processing.

        Args:
            resolved_questions: Optional list of resolved questions.
                               If None, loads from database.

        Returns:
            List of results from each stage
        """
        self._results = []

        try:
            # Get resolved questions
            if resolved_questions is None:
                resolved_questions = self._load_resolved_questions()

            self.resolved_questions = resolved_questions

            if not self.resolved_questions:
                logger.warning("No resolved questions found")
                return self._results

            logger.info(
                f"Processing {len(self.resolved_questions)} questions "
                f"with max {self.max_concurrent_questions} in parallel"
            )

            # Process each question through the pipeline (stages 1-2)
            # Stage 3 (graph building) happens after collecting all hypotheses
            question_tasks = [
                self._process_single_question(question)
                for question in self.resolved_questions
            ]

            # Run question processing tasks in parallel with concurrency limit
            question_results = await asyncio.gather(
                *question_tasks,
                return_exceptions=True
            )

            # Collect results and hypotheses
            successful_count = 0
            failed_count = 0
            for i, result in enumerate(question_results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Question {self.resolved_questions[i].id} processing failed: {result}"
                    )
                    failed_count += 1
                else:
                    self.evidence_articles.extend(result.get("evidence_articles", []))
                    self.causal_hypotheses.extend(result.get("causal_hypotheses", []))
                    successful_count += 1

            logger.info(
                f"Per-question processing complete: {successful_count} successful, {failed_count} failed"
            )

            if not self.causal_hypotheses:
                logger.warning("No causal hypotheses generated")
                return self._results

            logger.info(f"Total: {len(self.evidence_articles)} evidence articles, "
                       f"{len(self.causal_hypotheses)} causal hypotheses")

            # Stage 3: Build Causal Graph (after all question processing)
            logger.info("Stage 3: Building causal graph...")
            graph_result = await self.graph_stage.execute(self.causal_hypotheses)
            self._results.append(graph_result)
            self.enhanced_events = graph_result.outputs

            if not self.enhanced_events:
                logger.warning("No events enhanced")
                return self._results

            logger.info(f"Enhanced {len(self.enhanced_events)} events with causal links")

            # Persist enhanced events
            if self.enable_persistence and self.enhanced_events:
                logger.info("Persisting enhanced events...")
                persist_result = await self.event_persist.execute(self.enhanced_events)
                self._results.append(persist_result)

            logger.info("Evidence Pipeline completed successfully!")

        except Exception as e:
            if self._results:
                self._results[-1].error_message = str(e)
            logger.error(f"Evidence Pipeline failed: {e}")
            raise

        return self._results

    async def _process_single_question(self, question: Question) -> dict:
        """Process a single question through stages 1 and 2.

        This method:
        1. Collects evidence for THIS question only
        2. Performs causal reasoning with that evidence
        3. Persists results immediately
        4. Returns evidence and hypotheses for aggregation

        Args:
            question: The question to process

        Returns:
            Dictionary with 'evidence_articles' and 'causal_hypotheses' lists

        Raises:
            Exception: Propagates errors for asyncio.gather to handle
        """
        async with self.semaphore:
            logger.info(f"Processing question: {question.id}")
            evidence_articles = []
            causal_hypotheses = []

            try:
                # Stage 1: Collect evidence for this question only
                logger.debug(f"[{question.id}] Collecting evidence...")
                evidence_result = await self.evidence_stage.execute([question])
                evidence_articles = evidence_result.outputs

                if not evidence_articles:
                    logger.warning(f"[{question.id}] No evidence articles collected")
                    return {"evidence_articles": [], "causal_hypotheses": []}

                logger.info(f"[{question.id}] Collected {len(evidence_articles)} evidence articles")

                # Persist evidence articles immediately
                if self.enable_persistence:
                    await self.article_persist.execute(evidence_articles)

                # Stage 2: Causal reasoning with collected evidence
                logger.debug(f"[{question.id}] Performing causal reasoning...")
                question_evidence_pair = (question, evidence_articles)
                reasoning_result = await self.reasoning_stage.execute([question_evidence_pair])
                causal_hypotheses = reasoning_result.outputs

                if not causal_hypotheses:
                    logger.warning(f"[{question.id}] No causal hypotheses generated")
                    return {
                        "evidence_articles": evidence_articles,
                        "causal_hypotheses": []
                    }

                logger.info(f"[{question.id}] Generated {len(causal_hypotheses)} causal hypotheses")

                # Persist hypotheses immediately
                if self.enable_persistence:
                    await self.hypothesis_persist.execute(causal_hypotheses)

                logger.info(f"[{question.id}] Processing complete")

                return {
                    "evidence_articles": evidence_articles,
                    "causal_hypotheses": causal_hypotheses
                }

            except Exception as e:
                logger.error(f"[{question.id}] Error during processing: {e}")
                raise

    def _load_resolved_questions(self) -> List[Question]:
        """Load resolved questions from database that haven't been processed yet.

        Returns:
            List of resolved questions that are ready for evidence collection
        """
        db = GenericDatabase(self.database_config.db_path)
        current_date = datetime.now(timezone.utc)

        # Calculate date range
        min_age = timedelta(days=self.evidence_config.min_resolution_age_days)
        max_age = timedelta(days=self.evidence_config.max_resolution_age_days) if self.evidence_config.max_resolution_age_days else None

        min_resolution_date = current_date - max_age if max_age else None
        max_resolution_date = current_date - min_age

        # Get all questions
        all_questions = db.get_many(Question, filters={})

        # Get all existing causal hypotheses to check which questions were already processed
        processed_question_ids = set()
        if self.evidence_config.skip_already_processed:
            try:
                existing_hypotheses = db.get_many(CausalHypothesis, filters={})
                processed_question_ids = {h.question_id for h in existing_hypotheses}
            except Exception as e:
                # Table might not exist on first run - that's okay
                logger.debug(f"Could not load existing hypotheses (first run?): {e}")
                processed_question_ids = set()

        # Filter for resolved questions in date range
        resolved = []
        skipped_already_processed = 0

        for q in all_questions:
            # Must have resolution date and ground truth
            if not q.resolution_date or q.ground_truth is None:
                continue

            # Must be past resolution date
            if q.resolution_date >= current_date:
                continue

            # Check age constraints
            if q.resolution_date > max_resolution_date:
                continue  # Too recent

            if min_resolution_date and q.resolution_date < min_resolution_date:
                continue  # Too old

            # Filter by domain if specified
            if self.evidence_config.domain_filter and q.domain != self.evidence_config.domain_filter:
                continue

            # Skip if already processed by evidence pipeline (if configured)
            if self.evidence_config.skip_already_processed and q.id in processed_question_ids:
                skipped_already_processed += 1
                logger.debug(f"Skipping already processed question: {q.id}")
                continue

            resolved.append(q)

        # Apply max_questions limit if configured
        if self.evidence_config.max_questions is not None:
            resolved = resolved[:self.evidence_config.max_questions]

        logger.info(
            f"Loaded {len(resolved)} resolved questions "
            f"(min_age: {self.evidence_config.min_resolution_age_days}d, "
            f"max_age: {self.evidence_config.max_resolution_age_days}d"
            f"{f', limit: {self.evidence_config.max_questions}' if self.evidence_config.max_questions else ''})"
        )

        if skipped_already_processed > 0:
            logger.info(f"Skipped {skipped_already_processed} already processed questions")

        return resolved

    def get_summary(self) -> dict:
        """Get a summary of pipeline results.

        Returns:
            Dictionary with pipeline statistics
        """
        return {
            "resolved_questions": len(self.resolved_questions),
            "evidence_articles": len(self.evidence_articles),
            "causal_hypotheses": len(self.causal_hypotheses),
            "enhanced_events": len(self.enhanced_events),
            "stages_completed": len([r for r in self._results if r.status == PipelineStageStatus.COMPLETED]),
            "stages_failed": len([r for r in self._results if r.status == PipelineStageStatus.FAILED]),
        }
