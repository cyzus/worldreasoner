"""Gap analysis for collection progress."""

from typing import Dict, List, Optional
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
        goal: CollectionGoal
    ) -> GapAnalysis:
        """Analyze gaps between progress and goal.

        Args:
            progress: Current collection progress
            goal: Target collection goal

        Returns:
            Gap analysis with missing types and categories
        """
        # Calculate minimum total needed to reach goal
        total_needed = max(0, goal.total_questions - progress.total)

        # Get distribution gaps (types and categories)
        gaps = progress.get_gaps(goal)

        # Only report distribution gaps if we've met the minimum total
        # Distribution gaps are only meaningful once we have enough questions
        type_gaps = {}
        category_gaps = {}
        
        if total_needed == 0:
            # We've met the minimum total - now check distribution gaps
            for qtype, count in gaps["types"].items():
                if count > 0:
                    type_gaps[qtype] = count

            for category, count in gaps["categories"].items():
                if count > 0:
                    category_gaps[category] = count
        # else: Still need more questions to meet minimum - no distribution gaps yet

        analysis = GapAnalysis(
            type_gaps=type_gaps,
            category_gaps=category_gaps,
            total_needed=total_needed
        )

        # Report gaps if we need more questions OR have distribution gaps
        if total_needed > 0:
            logger.info(f"Gap analysis: need {total_needed} more questions to reach total goal")
            if analysis.has_gaps:
                logger.info(f"  Distribution gaps - Types: {analysis.type_gaps}, Categories: {analysis.category_gaps}")
        elif analysis.has_gaps:
            logger.info("Total goal met, but distribution gaps remain:")
            logger.info(f"  Types: {analysis.type_gaps}")
            logger.info(f"  Categories: {analysis.category_gaps}")
        else:
            logger.info("No gaps detected - goal fully met")

        return analysis
