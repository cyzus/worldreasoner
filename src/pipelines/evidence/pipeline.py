"""Evidence generation pipeline for WorldReasoner.

This pipeline builds causal explanations with hindsight:
0. Identify target events for all questions (batch processing)
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
    TargetEventIdentificationStage,
    TargetEventIdentificationConfig,
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
from src.utils.usage_tracking import UsageTracker


class EvidencePipeline(Pipeline):
    """Pipeline for building causal explanations with hindsight.

    Flow: Resolved Questions → Target Events (batch) → Evidence Articles → Causal Hypotheses → Graph

    This pipeline:
    - Identifies target events for all questions upfront (batch processing)
    - Collects evidence articles AFTER outcomes are known
    - Uses hindsight to identify true causal factors
    - Saves causal hypotheses to the graph database
    - Creates ground truth explanations for evaluation
    """

    def __init__(
        self,
        evidence_config: EvidencePipelineConfig,
        database_config: DatabaseConfig,
        enable_persistence: bool = True,
        max_concurrent_questions: int = 1,
        min_quality_score: Optional[float] = None,
    ):
        """Initialize the evidence pipeline.

        Args:
            evidence_config: Configuration for evidence pipeline
            database_config: Database connection configuration
            enable_persistence: Whether to save to database
            max_concurrent_questions: Max number of questions to process in parallel
            min_quality_score: If set, only process questions with a quality score >= this value
        """
        super().__init__(name="EvidencePipeline")

        self.evidence_config = evidence_config
        self.database_config = database_config
        self.enable_persistence = enable_persistence
        self.max_concurrent_questions = max_concurrent_questions
        self.min_quality_score = min_quality_score

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

        # Stage 1.5: Target Event Identification (for questions without target events)
        target_event_config = TargetEventIdentificationConfig(
            similarity_threshold=0.75,
            create_if_not_found=True,
        )
        self.target_event_stage = TargetEventIdentificationStage(
            target_event_config,
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
            validate_temporal_ordering=evidence_config.validate_temporal_ordering,
            max_links_per_event=evidence_config.max_links_per_event,
        )
        self.graph_stage = CausalGraphBuildingStage(
            graph_config,
            db_path=db_path
        )

        # Add stages
        self.add_stage(self.evidence_stage)
        self.add_stage(self.target_event_stage)
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

        # Storage for pipeline outputs
        self.resolved_questions: List[Question] = []
        self.evidence_articles: List[Article] = []
        self.causal_hypotheses: List[CausalHypothesis] = []

        # DB stats captured during question loading (for summaries/logging)
        self.db_total_questions = 0
        self.db_resolved_questions = 0
        self.db_unprocessed_questions = 0

        # Pipeline-level usage tracking
        self.usage_tracker = UsageTracker()

    async def run(
        self,
        resolved_questions: Optional[List[Question]] = None,
        min_quality_score: Optional[float] = None,
    ) -> List[PipelineStageResult]:
        """Run the evidence pipeline with per-question async processing.

        Args:
            resolved_questions: Optional list of resolved questions.
                               If None, loads from database.
            min_quality_score: Overrides the instance's min_quality_score for this run.

        Returns:
            List of results from each stage
        """
        self._results = []

        # Allow overriding the quality score threshold at runtime
        if min_quality_score is not None:
            self.min_quality_score = min_quality_score
            
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

            # Stage 0: Batch identify target events for questions that don't have them
            # This happens BEFORE evidence collection so all questions have target events
            questions_needing_events = [q for q in self.resolved_questions if not q.target_event_id]
            if questions_needing_events:
                logger.info(f"Identifying target events for {len(questions_needing_events)} questions (batch processing)...")
                # Pass empty article lists since we haven't collected evidence yet
                question_article_pairs = [(q, []) for q in questions_needing_events]
                target_event_result = await self.target_event_stage.execute(question_article_pairs)

                # Update questions in the main list with the returned questions
                if target_event_result.outputs:
                    updated_questions_map = {q.id: q for q in target_event_result.outputs}
                    for i, question in enumerate(self.resolved_questions):
                        if question.id in updated_questions_map:
                            self.resolved_questions[i] = updated_questions_map[question.id]

                    self._results.append(target_event_result)
                    identified_count = sum(1 for q in target_event_result.outputs if q.target_event_id)
                    logger.info(f"Target events identified: {identified_count}/{len(questions_needing_events)}")
                else:
                    logger.warning("Target event identification returned no results")

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
                    # Collect stage results (stages 1 and 2)
                    self._results.extend(result.get("stage_results", []))
                    successful_count += 1

            logger.info(
                f"Per-question processing complete: {successful_count} successful, {failed_count} failed"
            )

            if not self.causal_hypotheses:
                logger.error("No causal hypotheses generated - pipeline failed")
                # Mark the overall pipeline as failed
                if self._results:
                    self._results[-1].status = PipelineStageStatus.FAILED
                    self._results[-1].error_message = "No causal hypotheses generated from any question"
                return self._results

            logger.info(f"Total: {len(self.evidence_articles)} evidence articles, "
                       f"{len(self.causal_hypotheses)} causal hypotheses")

            # Stage 3: Build Causal Graph (after all question processing)
            # Note: Hypotheses are already saved by graph building stage
            logger.info("Stage 3: Building causal graph...")
            graph_result = await self.graph_stage.execute(self.causal_hypotheses)

            # Mark as failed if no results
            saved_hypotheses = graph_result.outputs
            if not saved_hypotheses:
                graph_result.status = PipelineStageStatus.FAILED
                graph_result.error_message = "No causal hypotheses saved to graph"
                logger.error("Stage 3: No causal hypotheses saved to graph - pipeline failed")
                self._results.append(graph_result)
                return self._results

            self._results.append(graph_result)
            logger.info(f"Saved {len(saved_hypotheses)} causal hypotheses to graph")

            # Aggregate usage from all stages
            self._aggregate_stage_usage()

            # Log pipeline-level summary
            logger.info("=" * 60)
            logger.info("EVIDENCE PIPELINE SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Questions processed: {len(self.resolved_questions)}")
            logger.info(f"Evidence articles collected: {len(self.evidence_articles)}")
            logger.info(f"Causal hypotheses generated: {len(self.causal_hypotheses)}")
            self.usage_tracker.log_summary(context="EvidencePipeline TOTAL")
            logger.info("=" * 60)

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
            Dictionary with 'evidence_articles', 'causal_hypotheses', and stage results

        Raises:
            Exception: Propagates errors for asyncio.gather to handle
        """
        async with self.semaphore:
            logger.info(f"Processing question: {question.id}")
            evidence_articles = []
            causal_hypotheses = []
            stage_results = []

            try:
                # Stage 1: Collect evidence for this question only
                logger.debug(f"[{question.id}] Collecting evidence...")
                evidence_result = await self.evidence_stage.execute([question])
                evidence_articles = evidence_result.outputs

                # Mark as failed if no results
                if not evidence_articles:
                    evidence_result.status = PipelineStageStatus.FAILED
                    evidence_result.error_message = "No evidence articles collected"
                    logger.warning(f"[{question.id}] No evidence articles collected - terminating processing")

                stage_results.append(evidence_result)

                if not evidence_articles:
                    return {
                        "evidence_articles": [],
                        "causal_hypotheses": [],
                        "stage_results": stage_results
                    }

                logger.info(f"[{question.id}] Collected {len(evidence_articles)} evidence articles")

                # Persist evidence articles immediately
                if self.enable_persistence:
                    await self.article_persist.execute(evidence_articles)

                # Stage 2: Causal reasoning with collected evidence
                # Note: Target event identification now happens in batch before evidence collection
                logger.debug(f"[{question.id}] Performing causal reasoning...")
                question_evidence_pair = (question, evidence_articles)
                reasoning_result = await self.reasoning_stage.execute([question_evidence_pair])
                causal_hypotheses = reasoning_result.outputs

                # Mark as failed if no results
                if not causal_hypotheses:
                    reasoning_result.status = PipelineStageStatus.FAILED
                    reasoning_result.error_message = "No causal hypotheses generated"
                    logger.warning(f"[{question.id}] No causal hypotheses generated - terminating processing")

                stage_results.append(reasoning_result)

                if not causal_hypotheses:
                    return {
                        "evidence_articles": evidence_articles,
                        "causal_hypotheses": [],
                        "stage_results": stage_results
                    }

                logger.info(f"[{question.id}] Generated {len(causal_hypotheses)} causal hypotheses")

                # Persist hypotheses immediately
                if self.enable_persistence:
                    await self.hypothesis_persist.execute(causal_hypotheses)

                logger.info(f"[{question.id}] Processing complete")

                return {
                    "evidence_articles": evidence_articles,
                    "causal_hypotheses": causal_hypotheses,
                    "stage_results": stage_results
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

        # Capture DB stats
        self.db_total_questions = len(all_questions)
        resolved_with_ground_truth = [q for q in all_questions if q.resolution_date and q.ground_truth is not None]
        self.db_resolved_questions = len(resolved_with_ground_truth)

        # Get all existing causal hypotheses to check which questions were already processed
        # Always load this - needed both for skip mode AND force-reprocess mode
        processed_question_ids = set()
        try:
            existing_hypotheses = db.get_many(CausalHypothesis, filters={})
            # Collect all question IDs from discovered_by_question_ids lists
            for h in existing_hypotheses:
                processed_question_ids.update(h.discovered_by_question_ids)
        except Exception as e:
            # Table might not exist on first run - that's okay
            logger.debug(f"Could not load existing hypotheses (first run?): {e}")
            processed_question_ids = set()

        # Count unprocessed: resolved questions that haven't been processed yet
        unprocessed_count = 0
        for q in resolved_with_ground_truth:
            if q.id not in processed_question_ids:
                unprocessed_count += 1
        self.db_unprocessed_questions = unprocessed_count

        # Filter for resolved questions in date range
        resolved = []
        skipped_already_processed = 0
        skipped_low_quality = 0

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

            # Filter by domains if specified
            if self.evidence_config.domains and q.domain not in self.evidence_config.domains:
                continue

            # Skip if quality score is below threshold
            if self.min_quality_score is not None:
                if q.quality_score is None or q.quality_score < self.min_quality_score:
                    continue

            # Skip if marked to skip evidence processing (low quality, noisy, etc.)
            if q.skip_evidence:
                skipped_low_quality += 1
                logger.debug(f"Skipping question marked for skip_evidence: {q.id} - {q.skip_reason}")
                continue

            # Handle already-processed questions (but don't clear yet)
            if q.id in processed_question_ids:
                if self.evidence_config.skip_already_processed:
                    # Skip mode: don't reprocess
                    skipped_already_processed += 1
                    logger.debug(f"Skipping already processed question: {q.id}")
                    continue
                # else: include in candidates for reprocessing (will clear after applying limits)

            resolved.append(q)

        # Sort questions based on mode
        if not self.evidence_config.skip_already_processed:
            # Force-reprocess mode: prioritize already-processed questions first
            # (the whole point is to reprocess them!)
            resolved.sort(key=lambda q: (q.id not in processed_question_ids, -(q.quality_score or 0.0)))
            logger.info("Prioritizing already-processed questions for reprocessing")
        elif self.min_quality_score is not None:
            # Normal mode with quality filter: sort by quality score only
            resolved.sort(key=lambda q: q.quality_score or 0.0, reverse=True)
            logger.info(f"Prioritizing questions by quality score (min_score={self.min_quality_score}).")

        # Apply max_questions limit if configured
        if self.evidence_config.max_questions is not None:
            resolved = resolved[:self.evidence_config.max_questions]

        # Now clear evidence for any questions being reprocessed (after applying limits)
        for q in resolved:
            if q.id in processed_question_ids:
                self._clear_evidence_for_question(q.id, db)
                # Remove from processed set so it gets reprocessed
                processed_question_ids.discard(q.id)
                logger.info(f"Cleared old evidence for reprocessing: {q.id}")

        logger.info(
            f"Loaded {len(resolved)} resolved questions "
            f"(min_age: {self.evidence_config.min_resolution_age_days}d, "
            f"max_age: {self.evidence_config.max_resolution_age_days}d"
            f"{f', limit: {self.evidence_config.max_questions}' if self.evidence_config.max_questions else ''})"
        )

        # Report DB-level stats to help users understand what's available
        logger.info(
            f"Questions in DB: total={self.db_total_questions}, "
            f"resolved={self.db_resolved_questions}, "
            f"unprocessed={self.db_unprocessed_questions}"
        )

        if skipped_already_processed > 0:
            logger.info(f"Skipped {skipped_already_processed} already processed questions")

        if skipped_low_quality > 0:
            logger.info(f"Skipped {skipped_low_quality} low-quality questions (marked skip_evidence)")

        return resolved

    def _clear_evidence_for_question(self, question_id: str, db: GenericDatabase) -> dict:
        """Clear evidence pipeline data for a question before reprocessing.

        This removes:
        - Articles collected for this question
        - Events extracted for this question (but NOT the target event)
        - Causal hypotheses discovered by this question

        The target event is preserved to avoid re-identifying it.

        Args:
            question_id: Question ID to clear evidence for
            db: Database instance

        Returns:
            Summary of deleted items
        """
        deleted = {"articles": 0, "events": 0, "hypotheses": 0}

        # Get the question to access its target event ID
        question = db.get(Question, question_id)
        target_event_id = question.target_event_id if question else None

        # Find and delete articles collected for this question
        all_articles = db.get_many(Article)
        for article in all_articles:
            # Check explicit provenance field
            if article.collected_for_question_id == question_id:
                db.delete(Article, article.id)
                deleted["articles"] += 1
            # Fallback: check metadata for pre-migration data
            elif (article.collected_for_question_id is None and
                  article.metadata.get('related_question_ids') and
                  question_id in article.metadata['related_question_ids']):
                db.delete(Article, article.id)
                deleted["articles"] += 1

        # Find and delete events extracted for this question (EXCEPT target event)
        all_events = db.get_many(Event)
        for event in all_events:
            # Don't delete the target event - it's needed for causal graph
            if target_event_id and event.id == target_event_id:
                continue

            # Check explicit provenance field
            if event.extracted_for_question_id == question_id:
                db.delete(Event, event.id)
                deleted["events"] += 1
            # Fallback: check metadata for pre-migration data
            elif (event.extracted_for_question_id is None and
                  event.metadata.get('related_question_ids') and
                  question_id in event.metadata['related_question_ids']):
                db.delete(Event, event.id)
                deleted["events"] += 1

        # Find and handle causal hypotheses
        all_hypotheses = db.get_many(CausalHypothesis)
        for hyp in all_hypotheses:
            if question_id in hyp.discovered_by_question_ids:
                if len(hyp.discovered_by_question_ids) == 1:
                    # Only this question discovered it - delete
                    db.delete(CausalHypothesis, hyp.id)
                    deleted["hypotheses"] += 1
                else:
                    # Multiple questions discovered it - just remove this question
                    hyp.discovered_by_question_ids.remove(question_id)
                    db.save(CausalHypothesis, hyp)

        logger.debug(
            f"Cleared evidence for {question_id}: "
            f"{deleted['articles']} articles, {deleted['events']} events, "
            f"{deleted['hypotheses']} hypotheses"
        )

        return deleted

    def get_summary(self) -> dict:
        """Get a summary of pipeline results.

        Returns:
            Dictionary with pipeline statistics
        """
        return {
            "resolved_questions": len(self.resolved_questions),
            "evidence_articles": len(self.evidence_articles),
            "causal_hypotheses": len(self.causal_hypotheses),
            "stages_completed": len([r for r in self._results if r.status == PipelineStageStatus.COMPLETED]),
            "stages_failed": len([r for r in self._results if r.status == PipelineStageStatus.FAILED]),
            # DB-level stats captured during question loading
            "db_total_questions": self.db_total_questions,
            "db_resolved_questions": self.db_resolved_questions,
            "db_unprocessed_questions": self.db_unprocessed_questions,
        }

    def _aggregate_stage_usage(self) -> None:
        """Aggregate token usage from all pipeline stages."""
        # Collect usage from each stage that tracks it
        if hasattr(self.evidence_stage, 'usage_tracker'):
            for metrics in self.evidence_stage.usage_tracker.usage_records:
                self.usage_tracker.add_usage(metrics)

        if hasattr(self.reasoning_stage, 'usage_tracker'):
            for metrics in self.reasoning_stage.usage_tracker.usage_records:
                self.usage_tracker.add_usage(metrics)
