"""Goal-oriented question collection orchestrator.

Coordinates multiple question sources to meet collection goals with
distribution requirements.
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.config.collection_goal import CollectionGoal
from src.config.pipeline import QuestionQualityConfig
from src.pipelines.question.sources.base import QuestionSourceRunner, CollectionResult
from .progress import CollectionProgress
from .source_coordinator import SourceCoordinator, SourceRequest
from .gap_analyzer import GapAnalyzer, GapAnalysis
from .gap_filler import GapFiller
from .quota_manager import QuotaManager
from ..stages.question_quality import QuestionQualityRankingStage
from src.domain.models import Question
from src.core.database import GenericDatabase
from src.utils.logging import logger


class OrchestratorConfig(BaseModel):
    """Configuration for the orchestrator."""

    max_iterations: int = Field(
        default=10,
        description="Maximum collection iterations before giving up"
    )
    parallel_sources: bool = Field(
        default=True,
        description="Run sources in parallel when possible"
    )
    save_intermediate_results: bool = Field(
        default=True,
        description="Save questions to DB as they're collected"
    )
    quality_ranking: QuestionQualityConfig = Field(
        default_factory=QuestionQualityConfig,
        description="Configuration for the quality ranking stage"
    )


class OrchestrationResult(BaseModel):
    """Result from orchestrated collection."""

    model_config = {"arbitrary_types_allowed": True}

    goal_met: bool
    questions: List[Question]
    progress: CollectionProgress
    iterations: int
    source_results: Dict[str, List[CollectionResult]] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    duplicates_skipped: int = 0
    missing_types: Dict[str, int] = Field(default_factory=dict)
    missing_categories: Dict[str, int] = Field(default_factory=dict)

    def duration_seconds(self) -> float:
        """Calculate execution duration."""
        return (self.completed_at - self.started_at).total_seconds()


class QuestionCollectionOrchestrator:
    """Orchestrates question collection from multiple sources until goal is met.

    This is the main entry point for goal-oriented question collection.
    It manages multiple question sources, tracks progress, and ensures
    distribution requirements are met.
    """

    def __init__(
        self,
        goal: CollectionGoal,
        sources: Dict[str, QuestionSourceRunner],
        config: Optional[OrchestratorConfig] = None,
        db_path: Optional[str] = None,
    ):
        """Initialize orchestrator.

        Args:
            goal: Collection goal with distribution requirements
            sources: Dict mapping source names to runner instances
            config: Orchestrator configuration
            db_path: Optional database path for saving results
        """
        self.goal = goal
        self.sources = sources
        self.config = config or OrchestratorConfig()
        self.db_path = db_path

        self.progress = CollectionProgress()
        self.source_results: Dict[str, List[CollectionResult]] = {
            name: [] for name in sources.keys()
        }
        self.errors: List[str] = []

        # Initialize DB if path provided
        self.db = GenericDatabase(db_path) if db_path else None

        # Initialize services
        self.coordinator = SourceCoordinator(parallel=self.config.parallel_sources)
        self.gap_analyzer = GapAnalyzer()
        self.quota_manager = QuotaManager(goal)
        self.gap_filler = GapFiller(sources, self.coordinator, goal)

        # Initialize the quality ranking stage if enabled
        if self.config.quality_ranking.enabled:
            self.quality_stage = QuestionQualityRankingStage(
                config=self.config.quality_ranking,
                db_path=self.db_path
            )
        else:
            self.quality_stage = None

        # Track existing question IDs for deduplication
        self.existing_question_ids: set = set()
        self.duplicates_skipped: int = 0

    async def collect_until_goal_met(self) -> OrchestrationResult:
        """Run collection until goal is met or max iterations reached.

        This is the main orchestration loop:
        1. Load existing questions for deduplication
        2. Collect from all sources in priority order
        3. Check if goal is met
        4. If not, identify gaps and do targeted collection
        5. Repeat until goal is met or max iterations

        Returns:
            OrchestrationResult with collected questions and metadata
        """
        started_at = datetime.now(timezone.utc)

        # Load existing questions for deduplication
        if self.db:
            await self._load_existing_questions()

        logger.info("=" * 60)
        logger.info("STARTING GOAL-ORIENTED QUESTION COLLECTION")
        logger.info("=" * 60)
        logger.info(f"Target: {self.goal.total_questions} questions")
        logger.info(f"Type distribution: {self.goal.type_distribution}")
        logger.info(f"Category distribution: {self.goal.category_distribution}")
        logger.info(f"Sources: {list(self.sources.keys())}")
        logger.info("=" * 60)

        iterations = 0

        try:
            # Phase 1: Broad collection from all sources
            while iterations < self.config.max_iterations:
                iterations += 1
                logger.info(f"--- Iteration {iterations}/{self.config.max_iterations} ---")

                # Check if goal already met
                if self.progress.is_goal_met(self.goal):
                    logger.success("Goal met!")
                    break

                # Collect from sources
                await self._collect_from_sources()

                # If we're close but not quite there, try targeted collection
                if self.progress.total >= self.goal.total_questions * 0.8:
                    logger.info("Attempting targeted gap filling...")
                    await self._fill_gaps()

                # Run incremental quality ranking after collection AND gap filling
                # This ensures all questions (including gap-filled ones) get scored
                # Already-scored questions will be skipped automatically
                if self.quality_stage and self.progress.get_questions():
                    logger.info("--- Running Incremental Quality Ranking ---")
                    all_questions = self.progress.get_questions()
                    ranked_questions_result = await self.quality_stage.execute(all_questions)
                    if ranked_questions_result.status == "completed":
                        # Update progress with scored questions
                        self.progress.set_questions(ranked_questions_result.outputs)
                        # Count how many are marked to skip
                        skip_count = sum(1 for q in ranked_questions_result.outputs if q.skip_evidence)
                        keep_count = len(ranked_questions_result.outputs) - skip_count
                        logger.info(f"Quality filter: keeping {keep_count}, skipping {skip_count} low-quality questions")
                    else:
                        logger.warning("Incremental quality ranking failed, continuing without it")

                # Save intermediate results
                if self.config.save_intermediate_results and self.db:
                    self._save_to_database()

            # Final check
            goal_met = self.progress.is_goal_met(self.goal)

            if not goal_met:
                logger.warning(
                    f"Goal not fully met after {iterations} iterations. "
                    f"Collected {self.progress.total}/{self.goal.total_questions}"
                )

            # Final save
            if self.db:
                self._save_to_database()

            completed_at = datetime.now(timezone.utc)

            # Report missing items
            missing = self._report_missing_items()

            logger.info("=" * 60)
            logger.info("COLLECTION COMPLETE")
            logger.info("=" * 60)
            # Don't log detailed summary here - main script will do it
            logger.info(f"Duration: {(completed_at - started_at).total_seconds():.1f}s")
            if self.duplicates_skipped > 0:
                logger.info(f"Duplicates skipped: {self.duplicates_skipped}")
            logger.info("=" * 60)

            return OrchestrationResult(
                goal_met=goal_met,
                questions=self.progress.get_questions(),
                progress=self.progress,
                iterations=iterations,
                source_results=self.source_results,
                errors=self.errors,
                started_at=started_at,
                completed_at=completed_at,
                duplicates_skipped=self.duplicates_skipped,
                missing_types=missing.get("types", {}),
                missing_categories=missing.get("categories", {}),
            )

        except Exception as e:
            logger.error(f"Orchestration error: {e}")
            self.errors.append(str(e))

            return OrchestrationResult(
                goal_met=False,
                questions=self.progress.get_questions(),
                progress=self.progress,
                iterations=iterations,
                source_results=self.source_results,
                errors=self.errors,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

    async def _collect_from_sources(self) -> None:
        """Collect from all sources based on quotas and needs."""

        # Calculate needed categories and types once for all sources
        category_gaps = self.progress.get_category_gaps(self.goal)
        type_gaps = self.progress.get_type_gaps(self.goal)
        needed_types = [qtype for qtype, gap in type_gaps.items() if gap > 0] if type_gaps else None

        if category_gaps:
            logger.debug(f"Category gaps to fill: {category_gaps}")
        else:
            logger.debug("No category gaps - all categories satisfied")

        # Build requests for each source
        requests = []
        for source_name, runner in self.sources.items():
            needed = self.quota_manager.calculate_needed_from_source(
                source_name, self.progress
            )

            if needed <= 0:
                logger.debug(f"No more questions needed from '{source_name}'")
                continue

            requests.append(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=needed,
                    type_filter=needed_types,
                    category_filter=category_gaps or None,
                    quality_requirements=self.goal.quality,
                    existing_question_ids=self.existing_question_ids,
                )
            )

        # Execute collection through coordinator
        results = await self.coordinator.collect_from_sources(requests)

        # Process results
        for result in results:
            self.source_results[result.source_name].append(result)

            if result.success and result.questions:
                # Filter duplicates
                unique_questions = self._filter_duplicates(result.questions)
                if unique_questions:
                    self.progress.add_questions(unique_questions)

        # Collect any errors from coordinator
        if self.coordinator.errors:
            self.errors.extend(self.coordinator.errors)
            self.coordinator.errors.clear()  # Clear for next iteration







    async def _fill_gaps(self) -> None:
        """Targeted collection to fill specific gaps in distribution."""

        # Analyze gaps
        analysis = self.gap_analyzer.analyze(self.progress, self.goal)

        if not analysis.has_gaps:
            logger.info("No gaps to fill")
            return

        # Fill gaps using GapFiller service
        gap_questions = await self.gap_filler.fill_gaps(
            analysis=analysis,
            progress=self.progress,
            existing_question_ids=self.existing_question_ids,
        )

        if gap_questions:
            # Filter duplicates and add to progress
            unique_questions = self._filter_duplicates(gap_questions)
            if unique_questions:
                self.progress.add_questions(unique_questions)
                logger.info(f"Gap filling collected {len(unique_questions)} questions")

        # Reset exhausted sources for next iteration
        self.gap_filler.reset_exhausted()

    def _save_to_database(self) -> None:
        """Save collected questions to database."""
        if not self.db:
            logger.debug("No database configured, skipping save")
            return

        questions = self.progress.get_questions()
        if not questions:
            logger.debug("No questions to save")
            return

        try:
            saved_count = 0
            for question in questions:
                self.db.save(Question, question)
                saved_count += 1
            logger.info(f"Saved {saved_count} questions to database ({self.db_path})")
            logger.debug(f"Sample saved IDs: {[q.id for q in questions[:3]]}")
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.errors.append(f"Database save error: {e}")

    async def _load_existing_questions(self) -> None:
        """Load existing questions from database for deduplication and progress tracking."""
        if not self.db:
            logger.info("No database configured, skipping deduplication")
            return

        try:
            # Use get_many() to retrieve all questions
            existing = self.db.get_many(Question, ids=None, filters=None)
            self.existing_question_ids = {q.id for q in existing}
            
            # CRITICAL: Add existing questions to progress tracker
            # This ensures the orchestrator knows about previous runs
            if existing:
                logger.info(f"Loaded {len(existing)} existing questions from database")
                self.progress.add_questions(existing)
                logger.info(f"Progress tracker initialized with {self.progress.total} questions")
                logger.debug(f"Sample existing IDs: {list(self.existing_question_ids)[:3]}")
            else:
                logger.info("No existing questions found in database")
        except Exception as e:
            logger.warning(f"Could not load existing questions: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _filter_duplicates(self, questions: List[Question]) -> List[Question]:
        """Filter out questions that already exist in database.

        Args:
            questions: Questions to filter

        Returns:
            Non-duplicate questions only
        """
        if not self.existing_question_ids:
            return questions

        filtered = []
        for q in questions:
            if q.id in self.existing_question_ids:
                self.duplicates_skipped += 1
                logger.debug(f"Skipping duplicate: {q.id}")
            else:
                filtered.append(q)
                # Add to existing set to avoid duplicates within same run
                self.existing_question_ids.add(q.id)

        if len(questions) != len(filtered):
            logger.info(f"Filtered out {len(questions) - len(filtered)} duplicate questions")

        return filtered

    def _report_missing_items(self) -> Dict[str, any]:
        """Generate report of missing types and categories.

        Returns:
            Dict with missing types and categories
        """
        # Use GapAnalyzer for consistent gap analysis
        analysis = self.gap_analyzer.analyze(self.progress, self.goal)

        missing = {
            "types": analysis.type_gaps,
            "categories": analysis.category_gaps,
        }

        if missing["types"] or missing["categories"]:
            logger.info("=" * 60)
            logger.info("MISSING ITEMS REPORT")
            logger.info("=" * 60)

            if missing["types"]:
                logger.info("Missing question types:")
                for qtype, count in missing["types"].items():
                    target = self.goal.type_distribution.get(qtype, 0)
                    collected = target - count
                    logger.info(f"  {qtype:15} {collected:3}/{target:3} ({count} short)")

            if missing["categories"]:
                logger.info("Missing categories:")
                for cat, count in missing["categories"].items():
                    target = self.goal.category_distribution.get(cat, 0)
                    collected = target - count
                    logger.info(f"  {cat:15} {collected:3}/{target:3} ({count} short)")

            logger.info("=" * 60)

        return missing
