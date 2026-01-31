"""Evidence Pipeline using HindsightAgent multi-agent system.

This pipeline uses managed agents (evidence_collector, causal_analyzer) that can
self-evaluate and iterate to build deep causal graphs.

Features:
- Deeper causal graphs: 3+ levels vs 1 level shallow graphs
- Self-evaluation: Agents assess their own work and iterate
- Adaptive behavior: Handles failures gracefully
- Built-in quality metrics: Article quality, graph quality,depth analysis
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from ..base import Pipeline, PipelineStageResult, PipelineStageStatus
from src.pipelines.prompts import HindsightCausalAnalysisPrompts
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig
from src.domain.models import Question, Article, CausalHypothesis
from src.core.database import GenericDatabase
from src.agents.hindsight_agent import HindsightAgent
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker


class EvidencePipeline(Pipeline):
    """Evidence pipeline using adaptive multi-agent system.

    Flow: Resolved Questions → Agent-based Causal Analysis → Deep Causal Graphs

    This pipeline:
    - Uses HindsightAgent with managed sub-agents (evidence_collector, causal_analyzer)
    - Agents self-evaluate and iterate to improve graph depth (3+ levels)
    - Automatically collects evidence AFTER outcomes are known (hindsight)
    - Creates ground truth explanations with quality metrics
    """

    def __init__(
        self,
        evidence_config: EvidencePipelineConfig,
        database_config: DatabaseConfig,
        enable_persistence: bool = True,
        max_concurrent_questions: int = 1,
        min_quality_score: Optional[float] = None,
        agent_max_steps: int = 30,
        min_graph_depth: int = 3,
    ):
        """Initialize evidence pipeline with agent-based processing.

        Args:
            evidence_config: Configuration for evidence pipeline
            database_config: Database connection configuration
            enable_persistence: Whether to persist results to database
            max_concurrent_questions: Maximum concurrent question processing
            min_quality_score: If set, only process questions with quality score >= this value
            agent_max_steps: Maximum steps for manager agent (default: 30)
            min_graph_depth: Minimum causal chain depth required (default: 3)
        """
        super().__init__(name="EvidencePipeline")

        self.evidence_config = evidence_config
        self.database_config = database_config
        self.enable_persistence = enable_persistence
        self.max_concurrent_questions = max_concurrent_questions
        self.min_quality_score = min_quality_score
        self.agent_max_steps = agent_max_steps
        self.min_graph_depth = min_graph_depth

        # Semaphore to limit concurrent question processing
        self.semaphore = asyncio.Semaphore(max_concurrent_questions)

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

        # Initialize prompt generator
        self.prompts = HindsightCausalAnalysisPrompts()

        logger.info("Adaptive multi-agent evidence pipeline initialized")

    def _create_stage_result(
        self,
        status: PipelineStageStatus,
        items_processed: int,
        items_output: int,
        outputs: List[Any],
        error_message: Optional[str] = None,
    ) -> PipelineStageResult:
        """Create a PipelineStageResult with consistent fields.

        Args:
            status: Status of the stage
            items_processed: Number of items processed
            items_output: Number of items output
            outputs: List of output items
            error_message: Optional error message for failed stages

        Returns:
            PipelineStageResult
        """
        now = datetime.now(timezone.utc)
        return PipelineStageResult(
            stage_name="AgentBasedEvidence",
            status=status,
            items_processed=items_processed,
            items_output=items_output,
            outputs=outputs,
            started_at=now,
            completed_at=now,
            error_message=error_message,
        )

    def _format_question_error(self, question_id: str, error: Any) -> str:
        """Format error message for a failed question.

        Args:
            question_id: ID of the question that failed
            error: Error or failure reason

        Returns:
            Formatted error message
        """
        if isinstance(error, Exception):
            return f"Question {question_id} processing failed: {error}"
        return f"Question {question_id}: {error}"

    async def run(
        self,
        resolved_questions: Optional[List[Question]] = None,
        min_quality_score: Optional[float] = None,
    ) -> List[PipelineStageResult]:
        """Run the evidence pipeline with agent-based async processing.

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
                f"with max {self.max_concurrent_questions} concurrent agents"
            )

            # Process each question with agent-based pipeline
            question_tasks = [
                self._process_single_question(question)
                for question in self.resolved_questions
            ]

            # Run question processing tasks in parallel with concurrency limit
            question_results = await asyncio.gather(
                *question_tasks, return_exceptions=True
            )

            # Collect results and hypotheses
            successful_count = 0
            failed_count = 0
            failure_reasons = []

            for i, result in enumerate(question_results):
                question_id = self.resolved_questions[i].id

                if isinstance(result, Exception):
                    error_msg = self._format_question_error(question_id, result)
                    logger.error(error_msg)
                    failure_reasons.append(error_msg)
                    failed_count += 1
                elif result.get("status") == "failed":
                    failure_reason = result.get("failure_reason", "Unknown error")
                    error_msg = self._format_question_error(question_id, failure_reason)
                    logger.error(error_msg)
                    failure_reasons.append(error_msg)
                    failed_count += 1
                else:
                    self.evidence_articles.extend(result.get("evidence_articles", []))
                    self.causal_hypotheses.extend(result.get("causal_hypotheses", []))
                    successful_count += 1

            logger.info(
                f"Per-question processing complete: {successful_count} successful, {failed_count} failed"
            )

            if not self.causal_hypotheses:
                logger.error("No causal hypotheses generated - pipeline failed")
                error_message = (
                    "; ".join(failure_reasons)
                    if failure_reasons
                    else "No causal hypotheses generated"
                )
                failed_result = self._create_stage_result(
                    status=PipelineStageStatus.FAILED,
                    items_processed=len(self.resolved_questions),
                    items_output=0,
                    outputs=[],
                    error_message=error_message,
                )
                self._results.append(failed_result)
                return self._results

            logger.info(
                f"Total: {len(self.evidence_articles)} evidence articles, "
                f"{len(self.causal_hypotheses)} causal hypotheses"
            )

            # Add a success result for the pipeline runner to detect
            success_result = self._create_stage_result(
                status=PipelineStageStatus.COMPLETED,
                items_processed=len(self.resolved_questions),
                items_output=len(self.causal_hypotheses),
                outputs=self.causal_hypotheses,
            )
            self._results.append(success_result)

            logger.info("Evidence pipeline completed successfully!")

        except Exception as e:
            logger.error(f"Evidence Pipeline failed: {e}")
            raise

        return self._results

    async def _process_single_question(self, question: Question) -> dict:
        """Process a single question using HindsightAgent multi-agent system.

        Creates a new agent per question with provenance context, ensuring
        all articles, events, and hypotheses are properly linked to the question.

        Args:
            question: Question to process

        Returns:
            Dictionary with 'evidence_articles', 'causal_hypotheses', and quality metrics
        """
        async with self.semaphore:
            logger.info(f"[AGENT MODE] Processing question: {question.id}")

            # Get database connection for outcome service
            db = GenericDatabase(self.database_config.db_path)

            # Auto-generate outcome events if not already present
            from src.domain.outcome_event_service import OutcomeEventService

            outcome_service = OutcomeEventService(db)
            outcome_events = outcome_service.get_outcome_events_for_question(
                question.id
            )

            if not outcome_events:
                outcome_events = outcome_service.auto_create_outcome_events(question)
                logger.info(
                    f"[{question.id}] Auto-created {len(outcome_events)} outcome events"
                )
            else:
                logger.debug(
                    f"[{question.id}] Found {len(outcome_events)} existing outcome events"
                )

            # Create agent WITH question context for provenance tracking
            # This ensures all tools know which question they're serving
            hindsight_agent = HindsightAgent(
                db_path=self.database_config.db_path,
                max_steps=self.agent_max_steps,
                question_id=question.id,  # Provenance context
                target_event_id=question.target_event_id,  # Target for causal graph
            )
            logger.debug(f"[{question.id}] Created context-aware HindsightAgent")

            # Construct agent prompt using prompt generator
            # Pass outcome_events so they can be injected into prompt
            prompt = self.prompts.get_agent_prompt(
                question=question,
                min_graph_depth=self.min_graph_depth,
                evidence_window_days=self.evidence_config.evidence_window_days,
                min_evidence_articles=self.evidence_config.min_evidence_articles,
                confidence_threshold=self.evidence_config.causal_confidence_threshold,
                outcome_events=outcome_events,  # NEW: Pass outcomes for prompt injection
            )

            try:
                # Run agent in thread pool to avoid blocking
                # Agent execution is automatically saved to logs/agent_runs/{agent_name}_{question_id}_{timestamp}.json
                logger.debug(f"[{question.id}] Starting HindsightAgent...")
                result = await asyncio.to_thread(
                    hindsight_agent.run, prompt, run_id=question.id
                )
                logger.info(f"[{question.id}] Agent completed successfully")

                # Extract results from database (agent persisted everything)
                db = GenericDatabase(self.database_config.db_path)

                # Get articles and hypotheses for this question
                all_articles = db.get_many(Article)
                all_hypotheses = db.get_many(CausalHypothesis)

                # Filter hypotheses for this question
                question_hypotheses = [
                    h
                    for h in all_hypotheses
                    if question.id in h.discovered_by_question_ids
                ]

                # Get articles referenced by these hypotheses
                evidence_article_ids = set()
                for hyp in question_hypotheses:
                    evidence_article_ids.update(hyp.evidence_article_ids)

                evidence_articles = [
                    a for a in all_articles if a.id in evidence_article_ids
                ]

                logger.info(
                    f"[{question.id}] Agent results: "
                    f"{len(evidence_articles)} articles, "
                    f"{len(question_hypotheses)} hypotheses"
                )

                # Evaluate article quality based on collected evidence articles
                from src.utils.article_analysis import (
                    analyze_timeline,
                    analyze_sources,
                    identify_gaps,
                    calculate_quality,
                )

                article_quality_score = 0.0
                article_coverage = None

                if evidence_articles:
                    # Use comprehensive quality calculation with timeline analysis
                    from src.utils.date_utils import ensure_timezone_aware

                    # Pass coverage_start for expected coverage window calculation
                    coverage_start = (
                        ensure_timezone_aware(question.estimated_start_time)
                        if question.estimated_start_time
                        else None
                    )
                    timeline_data = analyze_timeline(
                        evidence_articles,
                        question.resolution_date,
                        coverage_start=coverage_start,
                    )
                    source_data = analyze_sources(evidence_articles)
                    gaps = identify_gaps(timeline_data)

                    quality_metrics = calculate_quality(
                        evidence_articles,
                        timeline_data,
                        source_data,
                        gaps,
                        coverage_start=coverage_start,
                    )

                    article_quality_score = quality_metrics["score"]

                    # Structure result for compatibility with existing code
                    article_coverage = {
                        "quality": quality_metrics,
                        "article_count": len(evidence_articles),
                        "sources": {"unique_sources": source_data["unique_sources"]},
                        "coverage_end_date": question.resolution_date,
                        "timeline": timeline_data,
                        "gaps": gaps,
                    }

                    logger.info(
                        f"[{question.id}] Article quality: {article_quality_score:.2f} "
                        f"({article_coverage['article_count']} articles, "
                        f"{article_coverage['sources']['unique_sources']} sources, "
                        f"{len(gaps)} time gaps)"
                    )
                else:
                    logger.warning(
                        f"[{question.id}] No evidence articles collected - article quality: 0.0"
                    )

                # Evaluate graph quality using shared utilities
                from src.utils.graph_analysis import calculate_graph_quality

                graph_quality_score = 0.0
                max_depth = 0

                if question_hypotheses:
                    # Determine target event ID (use existing or infer from graph)
                    target_event_id = question.target_event_id

                    if not target_event_id:
                        # Use shared utility to infer target from graph
                        from src.utils.graph_analysis import infer_target_event_id

                        inferred_id = infer_target_event_id(question_hypotheses)

                        if inferred_id:
                            target_event_id = inferred_id
                            logger.info(
                                f"[{question.id}] Inferred target event from graph: {target_event_id}"
                            )

                            # Update the question in DB with the inferred target event
                            try:
                                question.target_event_id = target_event_id
                                db.save(Question, question)
                                logger.debug(
                                    f"[{question.id}] Updated question with inferred target event"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"[{question.id}] Failed to persist inferred target event: {e}"
                                )
                        else:
                            # Fallback if no specific sink (e.g. cycles)
                            # Pick arbitrary target to allow graph analysis to proceed
                            all_targets = set(
                                h.target_event_id for h in question_hypotheses
                            )
                            if all_targets:
                                target_event_id = list(all_targets)[0]
                                logger.warning(
                                    f"[{question.id}] Circular graph detected? Using arbitrary target: {target_event_id}"
                                )

                    # Calculate graph quality using shared utility
                    quality_metrics = calculate_graph_quality(
                        hypotheses=question_hypotheses,
                        target_event_id=target_event_id,
                        min_depth_for_full_score=self.min_graph_depth,
                    )

                    graph_quality_score = quality_metrics["quality_score"]
                    max_depth = quality_metrics["max_depth"]

                    logger.info(
                        f"[{question.id}] Graph quality: {graph_quality_score:.2f} "
                        f"(depth: {max_depth}, events: {quality_metrics['event_count']}, "
                        f"hypotheses: {quality_metrics['hypothesis_count']})"
                    )
                else:
                    logger.warning(
                        f"[{question.id}] No causal hypotheses generated - graph quality: 0.0"
                    )

                # Check if pipeline should be marked as failed based on quality
                status_message = None
                if article_quality_score == 0.0:
                    status_message = (
                        "Failed: Article quality is zero (no/insufficient articles)"
                    )
                    logger.error(f"[{question.id}] {status_message}")
                elif graph_quality_score == 0.0:
                    status_message = "Failed: Graph quality is zero (no/insufficient causal hypotheses)"
                    logger.error(f"[{question.id}] {status_message}")
                elif max_depth < self.min_graph_depth:
                    status_message = f"Failed: Graph depth ({max_depth}) below minimum ({self.min_graph_depth})"
                    logger.error(f"[{question.id}] {status_message}")

                # If failed, return empty results to signal failure
                if status_message:
                    return {
                        "evidence_articles": [],
                        "causal_hypotheses": [],
                        "stage_results": [],
                        "agent_output": result,
                        "status": "failed",
                        "failure_reason": status_message,
                        "article_quality": article_quality_score,
                        "graph_quality": graph_quality_score,
                        "graph_depth": max_depth,
                    }

                # Success
                return {
                    "evidence_articles": evidence_articles,
                    "causal_hypotheses": question_hypotheses,
                    "stage_results": [],  # Agent mode doesn't have stages
                    "agent_output": result,
                    "status": "success",
                    "article_quality": article_quality_score,
                    "graph_quality": graph_quality_score,
                    "graph_depth": max_depth,
                }

            except Exception as e:
                logger.error(f"[{question.id}] Agent processing failed: {e}")
                # Return empty result on failure
                return {
                    "evidence_articles": [],
                    "causal_hypotheses": [],
                    "stage_results": [],
                    "status": "failed",
                    "failure_reason": str(e),
                }

    def _load_resolved_questions(self) -> List[Question]:
        """Load resolved questions from database that haven't been processed yet.

        Returns:
            List of resolved questions that are ready for evidence collection
        """
        db = GenericDatabase(self.database_config.db_path)
        current_date = datetime.now(timezone.utc)

        # Calculate date range
        min_age = timedelta(days=self.evidence_config.min_resolution_age_days)
        max_age = (
            timedelta(days=self.evidence_config.max_resolution_age_days)
            if self.evidence_config.max_resolution_age_days
            else None
        )

        min_resolution_date = current_date - max_age if max_age else None
        max_resolution_date = current_date - min_age

        # Get all questions
        all_questions = db.get_many(Question, filters={})

        # Capture DB stats
        self.db_total_questions = len(all_questions)
        resolved_with_ground_truth = [
            q for q in all_questions if q.resolution_date and q.ground_truth is not None
        ]
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
            if (
                self.evidence_config.domains
                and q.domain not in self.evidence_config.domains
            ):
                continue

            # Skip if quality score is below threshold
            if self.min_quality_score is not None:
                if q.quality_score is None or q.quality_score < self.min_quality_score:
                    continue

            # Skip if marked to skip evidence processing (low quality, noisy, etc.)
            if q.skip_evidence:
                skipped_low_quality += 1
                logger.debug(
                    f"Skipping question marked for skip_evidence: {q.id} - {q.skip_reason}"
                )
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
            resolved.sort(
                key=lambda q: (
                    q.id not in processed_question_ids,
                    -(q.quality_score or 0.0),
                )
            )
            logger.info("Prioritizing already-processed questions for reprocessing")
        elif self.min_quality_score is not None:
            # Normal mode with quality filter: sort by quality score only
            resolved.sort(key=lambda q: q.quality_score or 0.0, reverse=True)
            logger.info(
                f"Prioritizing questions by quality score (min_score={self.min_quality_score})."
            )

        # Apply max_questions limit if configured
        if self.evidence_config.max_questions is not None:
            resolved = resolved[: self.evidence_config.max_questions]

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
            logger.info(
                f"Skipped {skipped_already_processed} already processed questions"
            )

        if skipped_low_quality > 0:
            logger.info(
                f"Skipped {skipped_low_quality} low-quality questions (marked skip_evidence)"
            )

        return resolved

    def _clear_evidence_for_question(
        self, question_id: str, db: GenericDatabase
    ) -> dict:
        """Clear evidence pipeline data for a question before reprocessing.

        Uses QuestionService to avoid circular dependency with CLI layer.

        Args:
            question_id: Question ID to clear evidence for
            db: Database instance

        Returns:
            Summary of deleted items with counts
        """
        from src.domain.question_service import QuestionService

        service = QuestionService(db)
        deleted = service.clear_evidence(question_id, cascade=True)

        logger.debug(
            f"Cleared evidence for {question_id}: "
            f"{deleted['articles']} articles, {deleted['events']} events, "
            f"{deleted['hypotheses']} hypotheses"
        )

        return deleted

    def get_summary(self) -> Dict[str, Any]:
        """Get pipeline execution summary with agent-specific info.

        Returns:
            Dictionary with summary statistics
        """
        return {
            "resolved_questions": len(self.resolved_questions),
            "evidence_articles": len(self.evidence_articles),
            "causal_hypotheses": len(self.causal_hypotheses),
            # DB-level stats captured during question loading
            "db_total_questions": self.db_total_questions,
            "db_resolved_questions": self.db_resolved_questions,
            "db_unprocessed_questions": self.db_unprocessed_questions,
            # Agent-specific info
            "processing_mode": "adaptive_agents",
            "agent_max_steps": self.agent_max_steps,
            "min_graph_depth": self.min_graph_depth,
        }
