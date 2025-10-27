"""Evidence generation pipeline for WorldReasoner.

This pipeline builds causal explanations with hindsight:
1. Collect evidence articles AFTER outcomes are known
2. Identify causal relationships using hindsight
3. Build validated causal graphs
"""

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
    ):
        """Initialize the evidence pipeline.

        Args:
            evidence_config: Configuration for evidence pipeline
            database_config: Database connection configuration
            enable_persistence: Whether to save to database
        """
        super().__init__(name="EvidencePipeline")

        self.evidence_config = evidence_config
        self.database_config = database_config
        self.enable_persistence = enable_persistence

        db_path = database_config.db_path

        # Stage 1: Hindsight Evidence Collection
        evidence_collection_config = EvidenceCollectionConfig(
            evidence_window_days=evidence_config.evidence_window_days,
            min_evidence_articles=evidence_config.min_evidence_articles,
            include_expert_analysis=evidence_config.include_expert_analysis,
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
        """Run the evidence pipeline.

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

            logger.info(f"Processing {len(self.resolved_questions)} resolved questions")

            # Stage 1: Collect Hindsight Evidence
            logger.info("Stage 1: Collecting hindsight evidence...")
            evidence_result = await self.evidence_stage.execute_batched(
                self.resolved_questions,
                batch_size=self.evidence_config.question_batch_size
            )
            self._results.append(evidence_result)
            self.evidence_articles = evidence_result.outputs

            if not self.evidence_articles:
                logger.warning("No evidence articles collected")
                return self._results

            logger.info(f"Collected {len(self.evidence_articles)} evidence articles")

            # Persist evidence articles
            if self.enable_persistence and self.evidence_articles:
                logger.info("Persisting evidence articles...")
                persist_result = await self.article_persist.execute(self.evidence_articles)
                self._results.append(persist_result)

            # Prepare inputs for Stage 2: pair questions with their evidence
            question_evidence_pairs = self._pair_questions_with_evidence()

            if not question_evidence_pairs:
                logger.warning("No question-evidence pairs created")
                return self._results

            logger.info(f"Created {len(question_evidence_pairs)} question-evidence pairs")

            # Stage 2: Causal Reasoning
            logger.info("Stage 2: Identifying causal relationships...")
            reasoning_result = await self.reasoning_stage.execute_batched(
                question_evidence_pairs,
                batch_size=self.evidence_config.reasoning_batch_size
            )
            self._results.append(reasoning_result)
            self.causal_hypotheses = reasoning_result.outputs

            if not self.causal_hypotheses:
                logger.warning("No causal hypotheses generated")
                return self._results

            logger.info(f"Generated {len(self.causal_hypotheses)} causal hypotheses")

            # Persist hypotheses
            if self.enable_persistence and self.causal_hypotheses:
                logger.info("Persisting causal hypotheses...")
                persist_result = await self.hypothesis_persist.execute(self.causal_hypotheses)
                self._results.append(persist_result)

            # Stage 3: Build Causal Graph
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

    def _pair_questions_with_evidence(self) -> List[Tuple[Question, List[Article]]]:
        """Pair each question with its evidence articles.

        Returns:
            List of (Question, List[Article]) tuples
        """
        pairs = []

        for question in self.resolved_questions:
            # Find evidence articles related to this question
            related_articles = [
                article for article in self.evidence_articles
                if (
                    # Check if question ID is in related_question_ids metadata
                    question.id in article.metadata.get('related_question_ids', [])
                    # Or check if target event is in article's event_ids
                    or (question.target_event_id and question.target_event_id in article.event_ids)
                )
            ]

            if related_articles:
                pairs.append((question, related_articles))
            else:
                logger.warning(f"No evidence articles found for question {question.id}")

        return pairs

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
