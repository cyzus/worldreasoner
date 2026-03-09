"""Goal-oriented question collection orchestrator.

Coordinates multiple question sources to meet collection goals with
distribution requirements.
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.config.collection_goal import CollectionGoal
from src.config.pipeline import QuestionQualityConfig
from .runner_base import QuestionSourceRunner, CollectionResult
from .progress import CollectionProgress
from .coordinator import SourceCoordinator, SourceRequest
from .gap_analyzer import GapAnalyzer
from .gap_filler import GapFiller
from .stage_quality import QuestionQualityRankingStage
from src.domain.models import Question
from src.core.database import GenericDatabase
from src.utils.logging import logger


class OrchestratorConfig(BaseModel):
    """Configuration for the orchestrator."""

    max_iterations: int = Field(
        default=10, description="Maximum collection iterations before giving up"
    )
    parallel_sources: bool = Field(
        default=True, description="Run sources in parallel when possible"
    )
    save_intermediate_results: bool = Field(
        default=True, description="Save questions to DB as they're collected"
    )
    quality_ranking: QuestionQualityConfig = Field(
        default_factory=QuestionQualityConfig,
        description="Configuration for the quality ranking stage",
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
        self.gap_filler = GapFiller(sources, self.coordinator, goal)

        # Initialize the quality ranking stage if enabled
        if self.config.quality_ranking.enabled:
            self.quality_stage = QuestionQualityRankingStage(
                config=self.config.quality_ranking, db_path=self.db_path
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

        logger.info("Starting goal-oriented question collection")
        logger.info(f"Target: {self.goal.total_questions} questions")
        logger.info(f"Type distribution: {self.goal.type_distribution}")
        logger.info(f"Category distribution: {self.goal.category_distribution}")
        logger.info(f"Sources: {list(self.sources.keys())}")

        iterations = 0
        questions_before_iteration = 0

        try:
            # Main collection loop
            while iterations < self.config.max_iterations:
                iterations += 1
                logger.info(
                    f"--- Iteration {iterations}/{self.config.max_iterations} ---"
                )

                # Check if goal met (excluding skip_evidence questions)
                if self.progress.is_goal_met(self.goal, include_skipped=False):
                    logger.success("Goal met!")
                    break

                questions_before = self.progress.total

                # 1. Broad collection from sources
                await self._collect_from_sources()

                # 2. Score new questions immediately
                await self._score_new_questions()

                # 3. Gap filling with quality-aware selection
                await self._fill_gaps()

                # 4. Score gap-filled questions
                await self._score_new_questions()

                # Save intermediate results
                if self.config.save_intermediate_results and self.db:
                    self._save_to_database()

                # Check progress
                if self.progress.total == questions_before:
                    logger.warning(
                        f"No new questions in iteration {iterations}. Sources exhausted."
                    )
                    break

            # Final check (exclude skip_evidence questions)
            goal_met = self.progress.is_goal_met(self.goal, include_skipped=False)

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

            logger.info("Collection complete")
            logger.info(f"Duration: {(completed_at - started_at).total_seconds():.1f}s")
            if self.duplicates_skipped > 0:
                logger.info(f"Duplicates skipped: {self.duplicates_skipped}")

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

    async def _score_new_questions(self) -> None:
        """Score unscored questions and update skip_evidence flags."""
        if not self.quality_stage:
            return

        all_questions = self.progress.get_questions()
        if not all_questions:
            return

        unscored = [q for q in all_questions if q.quality_score is None]
        if not unscored:
            return

        logger.info(f"Scoring {len(unscored)} new questions...")
        result = await self.quality_stage.execute(all_questions)

        if result.status == "completed":
            self.progress.set_questions(result.outputs)
            skipped = sum(1 for q in result.outputs if q.skip_evidence)
            logger.info(
                f"Quality: {len(result.outputs) - skipped} kept, {skipped} skipped"
            )
        else:
            logger.warning("Quality scoring failed")

    async def _collect_from_sources(self) -> None:
        """Collect from all sources based on quotas and needs."""
        # Use GapAnalyzer for consistent gap calculation (exclude skip_evidence)
        analysis = self.gap_analyzer.analyze(
            self.progress, self.goal, include_skipped=False
        )

        requests = []
        for source_name, runner in self.sources.items():
            # Calculate quota: source minimum or fair share of remaining
            collected = self.progress.by_source.get(source_name, 0)
            source_min = self.goal.source_minimums.get(source_name, 0)

            if collected < source_min:
                needed = source_min - collected
            elif analysis.total_needed > 0:
                needed = max(1, analysis.total_needed // len(self.sources))
            else:
                continue

            requests.append(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=needed,
                    type_filter=analysis.type_gaps_list or None,
                    category_filter=analysis.category_gaps
                    if analysis.category_gaps
                    else None,
                    time_horizon_hints=analysis.time_horizon_gaps_list or None,
                    quality_requirements=self.goal.quality,
                    existing_question_ids=self.existing_question_ids,
                )
            )

        # Execute and process results
        results = await self.coordinator.collect_from_sources(requests)

        for result in results:
            self.source_results[result.source_name].append(result)
            if result.success and result.questions:
                unique = self._filter_duplicates(result.questions)
                if unique:
                    self.progress.add_questions(unique)
                elif result.questions:
                    # All questions were duplicates - log for debugging
                    logger.debug(
                        f"{result.source_name}: Filtered out {len(result.questions)} duplicates "
                        f"(consider increasing request count to account for duplicates)"
                    )
            # CollectionResult has errors field (optional)
            if hasattr(result, "errors") and result.errors:
                self.errors.extend(result.errors)

    async def _fill_gaps(self) -> None:
        """Targeted collection to fill distribution gaps."""
        analysis = self.gap_analyzer.analyze(
            self.progress, self.goal, include_skipped=False
        )

        if not analysis.has_gaps:
            return

        gap_questions = await self.gap_filler.fill_gaps(
            analysis=analysis,
            existing_question_ids=self.existing_question_ids,
        )

        if gap_questions:
            unique = self._filter_duplicates(gap_questions)
            if unique:
                self.progress.add_questions(unique)
                logger.info(f"Gap filling: +{len(unique)} questions")

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
            logger.exception(f"Error saving to database: {e}")
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
                logger.info(
                    f"Progress tracker initialized with {self.progress.total} questions"
                )
                logger.debug(
                    f"Sample existing IDs: {list(self.existing_question_ids)[:3]}"
                )
            else:
                logger.info("No existing questions found in database")
        except Exception as e:
            logger.opt(exception=True).warning(
                f"Could not load existing questions: {e}"
            )

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
            logger.info(
                f"Filtered out {len(questions) - len(filtered)} duplicate questions"
            )

        return filtered

    def _report_missing_items(self) -> Dict[str, any]:
        """Generate report of missing types and categories.

        Returns:
            Dict with missing types and categories
        """
        # Use GapAnalyzer for consistent gap analysis (exclude skip_evidence)
        analysis = self.gap_analyzer.analyze(
            self.progress, self.goal, include_skipped=False
        )

        missing = {
            "types": analysis.type_gaps,
            "categories": analysis.category_gaps,
            "time_horizons": analysis.time_horizon_gaps,
        }

        if missing["types"] or missing["categories"] or missing["time_horizons"]:
            logger.info("Missing items report:")

            if missing["types"]:
                logger.info("Missing question types:")
                for qtype, count in missing["types"].items():
                    target = self.goal.type_distribution.get(qtype, 0)
                    collected = target - count
                    logger.info(
                        f"  {qtype:15} {collected:3}/{target:3} ({count} short)"
                    )

            if missing["categories"]:
                logger.info("Missing categories:")
                for cat, count in missing["categories"].items():
                    target = self.goal.category_distribution.get(cat, 0)
                    collected = target - count
                    logger.info(f"  {cat:15} {collected:3}/{target:3} ({count} short)")

            if missing["time_horizons"]:
                logger.info("Missing time horizons:")
                for horizon, count in missing["time_horizons"].items():
                    target = (self.goal.time_horizon_distribution or {}).get(horizon, 0)
                    collected = target - count
                    logger.info(
                        f"  {horizon:15} {collected:3}/{target:3} ({count} short)"
                    )

        return missing
