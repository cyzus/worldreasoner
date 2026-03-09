"""Targeted gap filling for collection."""

from typing import Dict, List, Set, Optional

from .runner_base import QuestionSourceRunner
from .gap_analyzer import GapAnalysis
from .coordinator import SourceCoordinator, SourceRequest
from src.config.collection_goal import CollectionGoal
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
        existing_question_ids: set,
    ) -> List[Question]:
        """Fill identified gaps through targeted collection.

        Args:
            analysis: Gap analysis identifying what's missing
            existing_question_ids: IDs to skip for deduplication

        Returns:
            List of questions collected to fill gaps
        """
        if not analysis.has_gaps:
            logger.info("No gaps to fill")
            return []

        # Pre-compute which types/categories are actually supported to avoid futile requests
        supported_types = {
            qtype
            for qtype in analysis.type_gaps.keys()
            if any(
                [
                    await runner.can_provide(question_type=qtype)
                    for runner in self.sources.values()
                ]
            )
        }
        unsupported_types = set(analysis.type_gaps.keys()) - supported_types
        if unsupported_types:
            logger.warning(
                f"Skipping unsupported type gaps: {sorted(unsupported_types)} (no source can provide these types)"
            )

        collected_questions = []

        # Fill type gaps
        for qtype, needed_count in analysis.type_gaps.items():
            if needed_count <= 0 or qtype in unsupported_types:
                continue
            logger.info(f"Filling type gap: {needed_count} '{qtype}' questions")
            questions = await self._collect_with_filters(
                remaining=needed_count,
                type_filter=analysis.type_gaps_list,
                category_filter=None,
                existing_question_ids=existing_question_ids,
                description=f"of type '{qtype}'",
                time_horizon_hints=analysis.time_horizon_gaps_list or None,
            )
            collected_questions.extend(questions)

        # Fill category gaps
        for category, needed_count in analysis.category_gaps.items():
            if needed_count <= 0:
                continue
            can_serve_category = any(
                [
                    await runner.can_provide(category=category)
                    for runner in self.sources.values()
                ]
            )
            if not can_serve_category:
                logger.warning(
                    f"Skipping unsupported category gap '{category}' (no source can provide it)"
                )
                continue
            logger.info(f"Filling category gap: {needed_count} '{category}' questions")
            questions = await self._collect_with_filters(
                remaining=needed_count,
                type_filter=None,
                category_filter={category: needed_count},
                existing_question_ids=existing_question_ids,
                description=f"in category '{category}'",
                time_horizon_hints=analysis.time_horizon_gaps_list or None,
            )
            collected_questions.extend(questions)

        # Fill time horizon gaps
        for horizon, needed_count in analysis.time_horizon_gaps.items():
            if needed_count <= 0:
                continue
            from src.config.collection_goal import TimeHorizon

            try:
                th = TimeHorizon(horizon)
                min_d, max_d = TimeHorizon.get_day_range(th)
                logger.info(
                    f"Filling time horizon gap: {needed_count} '{horizon}' questions "
                    f"({min_d}-{max_d} days resolution window)"
                )
            except ValueError:
                logger.warning(f"Unknown time horizon '{horizon}', skipping")
                continue
            questions = await self._collect_with_filters(
                remaining=needed_count,
                type_filter=analysis.type_gaps_list or None,
                category_filter=None,
                existing_question_ids=existing_question_ids,
                description=f"with '{horizon}' time horizon ({min_d}-{max_d} days)",
                time_horizon_hints=[horizon],
            )
            collected_questions.extend(questions)

        # Fill total count if no specific distribution gaps remain
        if (
            analysis.total_needed > 0
            and not analysis.type_gaps
            and not analysis.category_gaps
            and not analysis.time_horizon_gaps
        ):
            logger.info(
                f"Filling total gap: {analysis.total_needed} questions (any type/category)"
            )
            questions = await self._collect_with_filters(
                remaining=analysis.total_needed,
                type_filter=None,
                category_filter=None,
                existing_question_ids=existing_question_ids,
                description="(any type/category)",
            )
            collected_questions.extend(questions)

        return collected_questions

    async def _collect_with_filters(
        self,
        remaining: int,
        type_filter: Optional[List[str]],
        category_filter: Optional[Dict[str, int]],
        existing_question_ids: set,
        description: str = "",
        time_horizon_hints: Optional[List[str]] = None,
    ) -> List[Question]:
        """Generic collection method with filters."""
        collected = []

        for source_name, runner in self.sources.items():
            if remaining <= 0:
                break

            if source_name in self.exhausted_sources:
                continue

            # Check capabilities
            if type_filter and not any(
                [await runner.can_provide(question_type=t) for t in type_filter]
            ):
                continue
            if category_filter and not any(
                [await runner.can_provide(category=c) for c in category_filter.keys()]
            ):
                continue

            # Over-request to account for potential duplicates (2-3x more)
            # This is especially important when fetching by category, as markets
            # may be cross-tagged and appear in multiple categories
            request_count = remaining * 3 if category_filter else remaining * 2

            logger.info(
                f"  {source_name}: requesting {request_count} {description} (to get {remaining} unique)"
            )

            result = await self.coordinator._collect_from_source(
                SourceRequest(
                    source_name=source_name,
                    runner=runner,
                    count=request_count,
                    type_filter=type_filter,
                    category_filter=category_filter,
                    quality_requirements=self.goal.quality,
                    existing_question_ids=existing_question_ids,
                    time_horizon_hints=time_horizon_hints,
                )
            )

            if result.success:
                if result.questions:
                    collected.extend(result.questions)
                    remaining -= len(result.questions)
                # Don't mark as exhausted if no questions - may work with different filters
            else:
                # Only mark exhausted on actual failure
                self.exhausted_sources.add(source_name)

        return collected

    def reset_exhausted(self):
        """Reset exhausted sources (for next iteration)."""
        self.exhausted_sources.clear()
