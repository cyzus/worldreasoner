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

    async def collect_until_goal_met(self) -> OrchestrationResult:
        """Run collection until goal is met or max iterations reached.

        This is the main orchestration loop:
        1. Collect from all sources in priority order
        2. Check if goal is met
        3. If not, identify gaps and do targeted collection
        4. Repeat until goal is met or max iterations

        Returns:
            OrchestrationResult with collected questions and metadata
        """
        started_at = datetime.now(timezone.utc)
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

            logger.info("\n" + "=" * 60)
            logger.info("COLLECTION COMPLETE")
            logger.info("=" * 60)
            self.progress.log_summary(self.goal)
            logger.info(f"Duration: {(completed_at - started_at).total_seconds():.1f}s")
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
            # Collect with filters
            result = await runner.collect(
                count=needed,
                type_filter=None,  # Don't filter here, let source decide
                category_filter=None,
                quality_requirements=self.goal.quality,
            )

            # Store result
            self.source_results[source_name].append(result)

            # Add questions to progress
            if result.success and result.questions:
                self.progress.add_questions(result.questions)
                logger.info(
                    f"✓ '{source_name}': collected {len(result.questions)} questions"
                )
            else:
                if result.error_message:
                    self.errors.append(f"{source_name}: {result.error_message}")
                logger.warning(f"✗ '{source_name}': no questions collected")

        except Exception as e:
            error_msg = f"Error collecting from '{source_name}': {e}"
            logger.error(error_msg)
            self.errors.append(error_msg)

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
                    )

                    if result.success and result.questions:
                        self.progress.add_questions(result.questions)
                        self.source_results[source_name].append(result)
                        count -= len(result.questions)
                        logger.info(f"    ✓ Got {len(result.questions)} '{qtype}' questions")

                except Exception as e:
                    logger.warning(f"    ✗ Error: {e}")

    def _save_to_database(self) -> None:
        """Save collected questions to database."""
        if not self.db:
            return

        questions = self.progress.get_questions()
        if not questions:
            return

        try:
            for question in questions:
                self.db.save(Question, question)
            logger.debug(f"Saved {len(questions)} questions to database")
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            self.errors.append(f"Database save error: {e}")
