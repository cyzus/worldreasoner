"""Targeted gap filling for collection."""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass

from src.pipelines.question.sources.base import QuestionSourceRunner, CollectionResult
from .gap_analyzer import GapAnalysis
from .source_coordinator import SourceCoordinator, SourceRequest
from .progress import CollectionProgress
from src.config.collection_goal import CollectionGoal, QualityRequirements
from src.domain.models import Question
from src.utils.logging import logger


class GapFiller:
    """Fills gaps in collection through targeted source queries.

    Uses gap analysis to make focused collection requests to sources
    that can provide the missing types and categories.
    """

    def __init__(
        self,
        sources: Dict[str, QuestionSourceRunner],
        coordinator: SourceCoordinator,
        goal: CollectionGoal,
    ):
        """Initialize gap filler.

        Args:
            sources: Available question sources
            coordinator: Source coordinator for execution
            goal: Collection goal with quotas
        """
        self.sources = sources
        self.coordinator = coordinator
        self.goal = goal
        self.exhausted_sources: Set[str] = set()

    async def fill_gaps(
        self,
        analysis: GapAnalysis,
        progress: CollectionProgress,
        existing_question_ids: set,
    ) -> List[Question]:
        """Fill identified gaps through targeted collection.

        Args:
            analysis: Gap analysis identifying what's missing
            progress: Current collection progress
            existing_question_ids: IDs to skip for deduplication

        Returns:
            List of questions collected to fill gaps
        """
        if not analysis.has_gaps:
            logger.info("No gaps to fill")
            return []

        collected_questions = []

        # Fill type gaps
        for qtype, needed_count in analysis.type_gaps.items():
            if needed_count <= 0:
                continue
            questions = await self._fill_type_gap(
                qtype=qtype,
                needed_count=needed_count,
                all_type_hints=analysis.type_gaps_list,
                category_hints=analysis.category_gaps,
                progress=progress,
                existing_question_ids=existing_question_ids,
            )
            collected_questions.extend(questions)

        # Fill category gaps
        for category, needed_count in analysis.category_gaps.items():
            if needed_count <= 0:
                continue
            questions = await self._fill_category_gap(
                category=category,
                needed_count=needed_count,
                type_hints=analysis.type_gaps_list,
                progress=progress,
                existing_question_ids=existing_question_ids,
            )
            collected_questions.extend(questions)

        # If no specific gaps were identified but we still need questions for the total
        if analysis.total_needed > 0 and not analysis.type_gaps and not analysis.category_gaps:
            logger.info(
                f"Filling total gap: need {analysis.total_needed} more questions to reach goal"
            )
            questions = await self._fill_total_gap(
                needed_count=analysis.total_needed,
                progress=progress,
                existing_question_ids=existing_question_ids,
            )
            collected_questions.extend(questions)

        return collected_questions

    async def _fill_type_gap(
        self,
        qtype: str,
        needed_count: int,
        all_type_hints: List[str],
        category_hints: Dict[str, int],
        progress: CollectionProgress,
        existing_question_ids: set,
    ) -> List[Question]:
        """Fill gap for specific question type."""
        logger.info(f"Filling gap: need {needed_count} '{qtype}' questions")

        collected = []
        remaining = needed_count

        for source_name, runner in self.sources.items():
            if remaining <= 0:
                break

            # Skip exhausted sources
            if source_name in self.exhausted_sources:
                logger.debug(f"  Skipping '{source_name}' (exhausted)")
                continue

            # Check if source can provide this type
            can_provide = await runner.can_provide(question_type=qtype)
            if not can_provide:
                logger.debug(f"  Skipping '{source_name}' (cannot provide '{qtype}')")
                continue

            # NOTE: We intentionally skip quota checks here
            # Distribution gap filling is allowed to exceed source quotas
            # to improve the overall distribution quality

            # Collect
            logger.info(
                f"  Trying '{source_name}' for '{qtype}' "
                f"(all type hints: {all_type_hints})..."
            )

            result = await self.coordinator._collect_from_source(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=remaining,
                    type_filter=all_type_hints,  # Hint at ALL gaps
                    category_filter=category_hints,
                    quality_requirements=self.goal.quality,
                    existing_question_ids=existing_question_ids,
                )
            )

            if result.success and result.questions:
                collected.extend(result.questions)
                remaining -= len(result.questions)
                logger.info(f"    ✓ Got {len(result.questions)} questions")
            else:
                # Mark as exhausted
                logger.debug(f"    ✗ '{source_name}': no questions, marking exhausted")
                self.exhausted_sources.add(source_name)

        return collected

    async def _fill_category_gap(
        self,
        category: str,
        needed_count: int,
        type_hints: List[str],
        progress: CollectionProgress,
        existing_question_ids: set,
    ) -> List[Question]:
        """Fill gap for specific category."""
        logger.info(f"Filling gap: need {needed_count} '{category}' questions")

        collected = []
        remaining = needed_count

        for source_name, runner in self.sources.items():
            if remaining <= 0:
                break

            # Skip exhausted sources
            if source_name in self.exhausted_sources:
                logger.debug(f"  Skipping '{source_name}' (exhausted)")
                continue

            # Check if source can provide this category
            can_provide = await runner.can_provide(category=category)
            if not can_provide:
                logger.debug(f"  Skipping '{source_name}' (cannot provide '{category}')")
                continue

            # NOTE: We intentionally skip quota checks here
            # Distribution gap filling is allowed to exceed source quotas
            # to improve the overall distribution quality

            # Collect
            logger.info(
                f"  Trying '{source_name}' for '{category}' "
                f"(all type hints: {type_hints})..."
            )

            result = await self.coordinator._collect_from_source(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=remaining,
                    type_filter=type_hints,
                    category_filter={category: remaining},
                    quality_requirements=self.goal.quality,
                    existing_question_ids=existing_question_ids,
                )
            )

            if result.success and result.questions:
                collected.extend(result.questions)
                remaining -= len(result.questions)
                logger.info(f"    ✓ Got {len(result.questions)} questions")
            else:
                # Mark as exhausted
                logger.debug(f"    ✗ '{source_name}': no questions, marking exhausted")
                self.exhausted_sources.add(source_name)

        return collected

    async def _fill_total_gap(
        self,
        needed_count: int,
        progress: CollectionProgress,
        existing_question_ids: set,
    ) -> List[Question]:
        """Fill gap in total question count without specific type/category requirements.
        
        Makes broad collection requests to reach the total goal.
        """
        logger.info(f"Filling total gap: need {needed_count} questions (any type/category)")

        collected = []
        remaining = needed_count

        for source_name, runner in self.sources.items():
            if remaining <= 0:
                break

            # Skip exhausted sources
            if source_name in self.exhausted_sources:
                logger.debug(f"  Skipping '{source_name}' (exhausted)")
                continue

            # Collect without specific type/category filters
            logger.info(f"  Trying '{source_name}' for {remaining} questions (any type/category)...")

            result = await self.coordinator._collect_from_source(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=remaining,
                    type_filter=None,  # Accept any type
                    category_filter=None,  # Accept any category
                    quality_requirements=self.goal.quality,
                    existing_question_ids=existing_question_ids,
                )
            )

            if result.success and result.questions:
                collected.extend(result.questions)
                remaining -= len(result.questions)
                logger.info(f"    ✓ Got {len(result.questions)} questions")
            else:
                # Mark as exhausted
                logger.debug(f"    ✗ '{source_name}': no questions, marking exhausted")
                self.exhausted_sources.add(source_name)

        return collected

    def _has_quota_available(
        self,
        source_name: str,
        progress: CollectionProgress
    ) -> bool:
        """Check if source has quota remaining."""
        already_collected = progress.by_source.get(source_name, 0)
        source_minimum = self.goal.source_minimums.get(source_name, 1)
        return already_collected < source_minimum

    def reset_exhausted(self):
        """Reset exhausted sources (for next iteration)."""
        self.exhausted_sources.clear()
