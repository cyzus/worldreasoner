"""Gap analysis for collection progress."""

from typing import Dict, List
from dataclasses import dataclass

from .progress import CollectionProgress
from src.config.collection_goal import CollectionGoal
from src.utils.logging import logger


@dataclass
class GapAnalysis:
    """Analysis of gaps in collection progress."""

    type_gaps: Dict[str, int]  # qtype -> count needed
    category_gaps: Dict[str, int]  # category -> count needed
    total_needed: int

    @property
    def has_gaps(self) -> bool:
        """Check if any gaps exist."""
        return bool(self.total_needed > 0 or self.type_gaps or self.category_gaps)

    @property
    def type_gaps_list(self) -> List[str]:
        """Get list of types with gaps."""
        return [t for t, count in self.type_gaps.items() if count > 0]

    @property
    def category_gaps_list(self) -> List[str]:
        """Get list of categories with gaps."""
        return [c for c, count in self.category_gaps.items() if count > 0]


class GapAnalyzer:
    """Analyzes collection progress to identify distribution gaps."""

    def analyze(
        self,
        progress: CollectionProgress,
        goal: CollectionGoal,
        include_skipped: bool = False,
    ) -> GapAnalysis:
        """Analyze gaps between progress and goal.

        Args:
            progress: Current collection progress
            goal: Target collection goal
            include_skipped: If False, exclude questions with skip_evidence=True

        Returns:
            Gap analysis with missing types and categories
        """
        # Filter questions if needed (consistent with is_goal_met)
        if include_skipped:
            questions = progress.questions_list
        else:
            questions = [q for q in progress.questions_list if not q.skip_evidence]

        # Calculate minimum total needed to reach goal (using filtered count)
        total_needed = max(0, goal.total_questions - len(questions))

        # Recalculate distributions from filtered questions
        by_type = {}
        by_category = {}
        for q in questions:
            by_type[q.question_type] = by_type.get(q.question_type, 0) + 1
            by_category[q.domain] = by_category.get(q.domain, 0) + 1

        # Calculate gaps based on filtered distributions
        type_gaps_dict = {}
        for qtype, target in goal.type_distribution.items():
            actual = by_type.get(qtype, 0)
            gap = max(0, target - actual)
            if gap > 0:
                type_gaps_dict[qtype] = gap

        category_gaps_dict = {}
        for category, target in goal.category_distribution.items():
            actual = by_category.get(category, 0)
            gap = max(0, target - actual)
            if gap > 0:
                category_gaps_dict[category] = gap

        analysis = GapAnalysis(
            type_gaps=type_gaps_dict,
            category_gaps=category_gaps_dict,
            total_needed=total_needed,
        )

        # Report gaps if we need more questions OR have distribution gaps
        if total_needed > 0:
            logger.info(
                f"Gap analysis: need {total_needed} more questions to reach total goal"
            )
            if analysis.has_gaps:
                logger.info(
                    f"  Distribution gaps - Types: {analysis.type_gaps}, Categories: {analysis.category_gaps}"
                )
        elif analysis.has_gaps:
            logger.info("Total goal met, but distribution gaps remain:")
            logger.info(f"  Types: {analysis.type_gaps}")
            logger.info(f"  Categories: {analysis.category_gaps}")
        else:
            logger.info("No gaps detected - goal fully met")

        return analysis
