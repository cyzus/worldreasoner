"""Goal-oriented question collection orchestrator.

Coordinates multiple question sources to meet collection goals with
distribution requirements.
"""

import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.config.collection_goal import CollectionGoal
from src.pipelines.sources.base import QuestionSourceRunner, CollectionResult
from .progress import CollectionProgress
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
                logger.info(f"\n--- Iteration {iterations}/{self.config.max_iterations} ---")

                # Check if goal already met
                if self.progress.is_goal_met(self.goal):
                    logger.success("Goal met!")
                    break

                # Collect from sources
                await self._collect_from_sources()

                # Save intermediate results
                if self.config.save_intermediate_results and self.db:
                    self._save_to_database()

                # Log progress
                self.progress.log_summary(self.goal)

                # If we're close but not quite there, try targeted collection
                if self.progress.total >= self.goal.total_questions * 0.8:
                    logger.info("\nAttempting targeted gap filling...")
                    await self._fill_gaps()

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

            logger.info("\n" + "=" * 60)
            logger.info("COLLECTION COMPLETE")
            logger.info("=" * 60)
            self.progress.log_summary(self.goal)
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

        if self.config.parallel_sources:
            # Run sources in parallel
            tasks = []
            for source_name, runner in self.sources.items():
                task = self._collect_from_source(source_name, runner)
                tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Run sources sequentially
            for source_name, runner in self.sources.items():
                await self._collect_from_source(source_name, runner)

    async def _collect_from_source(
        self,
        source_name: str,
        runner: QuestionSourceRunner,
    ) -> None:
        """Collect from a single source.

        Args:
            source_name: Name of the source
            runner: Runner instance for this source
        """
        # Check source quota
        already_collected = self.progress.by_source.get(source_name, 0)
        source_quota = self.goal.source_quotas.get(source_name, 100)

        if already_collected >= source_quota:
            logger.debug(f"Source '{source_name}' quota met ({already_collected}/{source_quota})")
            return

        # Calculate how many we need from this source
        needed = self._calculate_needed_from_source(source_name, source_quota)

        if needed <= 0:
            logger.debug(f"No more questions needed from '{source_name}'")
            return

        logger.info(f"\nCollecting from '{source_name}': {needed} questions...")

        try:
            # Calculate which types we need most
            needed_types = self._get_needed_types()

            # Collect with type hints and existing IDs for early deduplication
            result = await runner.collect(
                count=needed,
                type_filter=needed_types if needed_types else None,  # Hint which types we need
                category_filter=None,
                quality_requirements=self.goal.quality,
                existing_question_ids=self.existing_question_ids,  # Skip duplicates early
            )

            # Store result
            self.source_results[source_name].append(result)

            # Add questions to progress (after deduplication)
            if result.success and result.questions:
                # Filter out duplicates
                unique_questions = self._filter_duplicates(result.questions)

                if unique_questions:
                    self.progress.add_questions(unique_questions)
                    logger.info(
                        f"✓ '{source_name}': collected {len(unique_questions)} questions"
                    )
                else:
                    logger.warning(f"✗ '{source_name}': all questions were duplicates")
            else:
                if result.error_message:
                    self.errors.append(f"{source_name}: {result.error_message}")
                logger.warning(f"✗ '{source_name}': no questions collected")

        except Exception as e:
            error_msg = f"Error collecting from '{source_name}': {e}"
            logger.error(error_msg)
            self.errors.append(error_msg)

    def _get_needed_types(self) -> Optional[List[str]]:
        """Get list of question types we need most.

        Returns:
            List of needed types, or None if all types equally needed
        """
        type_gaps = self.progress.get_type_gaps(self.goal)

        if not type_gaps:
            return None

        # Sort by gap size (descending) and return types with positive gaps
        needed = [qtype for qtype, gap in type_gaps.items() if gap > 0]

        return needed if needed else None

    def _calculate_needed_from_source(
        self,
        source_name: str,
        source_quota: int,
    ) -> int:
        """Calculate how many questions we need from this source.

        Args:
            source_name: Name of the source
            source_quota: Maximum for this source

        Returns:
            Number of questions to request
        """
        # Already collected from this source
        already_from_source = self.progress.by_source.get(source_name, 0)

        # Remaining quota for source
        source_remaining = source_quota - already_from_source

        # Overall remaining
        overall_remaining = self.goal.total_questions - self.progress.total

        # Type gaps
        type_gaps = self.progress.get_type_gaps(self.goal)
        type_gap_total = sum(type_gaps.values())

        # Return minimum of all constraints
        return max(0, min(source_remaining, overall_remaining, type_gap_total or source_quota))

    async def _fill_gaps(self) -> None:
        """Targeted collection to fill specific gaps in distribution."""

        gaps = self.progress.get_gaps(self.goal)

        if not gaps["types"] and not gaps["categories"]:
            logger.info("No gaps to fill")
            return

        logger.info(f"Gaps identified:")
        logger.info(f"  Types: {gaps['types']}")
        logger.info(f"  Categories: {gaps['categories']}")

        # Try to fill type gaps
        for qtype, count in gaps["types"].items():
            if count <= 0:
                continue

            logger.info(f"\nFilling gap: need {count} '{qtype}' questions")

            # Find sources that can provide this type
            for source_name, runner in self.sources.items():
                if count <= 0:
                    break

                # Check if source can provide this type
                can_provide = await runner.can_provide(question_type=qtype)
                if not can_provide:
                    continue

                # Check quota
                already_collected = self.progress.by_source.get(source_name, 0)
                source_quota = self.goal.source_quotas.get(source_name, 100)
                if already_collected >= source_quota:
                    continue

                # Collect with type filter
                logger.info(f"  Trying '{source_name}' for '{qtype}'...")
                try:
                    result = await runner.collect(
                        count=count,
                        type_filter=[qtype],
                        quality_requirements=self.goal.quality,
                        existing_question_ids=self.existing_question_ids,
                    )

                    if result.success and result.questions:
                        # Filter duplicates
                        unique_questions = self._filter_duplicates(result.questions)

                        if unique_questions:
                            self.progress.add_questions(unique_questions)
                            self.source_results[source_name].append(result)
                            count -= len(unique_questions)
                            logger.info(f"    ✓ Got {len(unique_questions)} '{qtype}' questions")

                except Exception as e:
                    logger.warning(f"    ✗ Error: {e}")

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
        """Load existing question IDs from database for deduplication."""
        if not self.db:
            logger.info("No database configured, skipping deduplication")
            return

        try:
            # Use get_many() to retrieve all questions
            existing = self.db.get_many(Question, ids=None, filters=None)
            self.existing_question_ids = {q.id for q in existing}
            if self.existing_question_ids:
                logger.info(f"Loaded {len(self.existing_question_ids)} existing questions for deduplication")
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
        gaps = self.progress.get_gaps(self.goal)

        missing = {
            "types": {k: v for k, v in gaps["types"].items() if v > 0},
            "categories": {k: v for k, v in gaps["categories"].items() if v > 0},
        }

        if missing["types"] or missing["categories"]:
            logger.info("\n" + "=" * 60)
            logger.info("MISSING ITEMS REPORT")
            logger.info("=" * 60)

            if missing["types"]:
                logger.info("Missing question types:")
                for qtype, count in missing["types"].items():
                    target = self.goal.type_distribution.get(qtype, 0)
                    collected = target - count
                    logger.info(f"  {qtype:15} {collected:3}/{target:3} ({count} short)")

            if missing["categories"]:
                logger.info("\nMissing categories:")
                for cat, count in missing["categories"].items():
                    target = self.goal.category_distribution.get(cat, 0)
                    collected = target - count
                    logger.info(f"  {cat:15} {collected:3}/{target:3} ({count} short)")

            logger.info("=" * 60)

        return missing
