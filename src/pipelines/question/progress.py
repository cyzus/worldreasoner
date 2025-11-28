"""Progress tracking for goal-oriented question collection.

Tracks collection progress against defined goals in real-time.
"""

from typing import Dict, List, Any
from collections import defaultdict
from pydantic import BaseModel, Field

from src.domain.models import Question
from src.config.collection_goal import CollectionGoal
from src.utils.logging import logger


class CollectionProgress(BaseModel):
    """Tracks progress toward collection goal.

    Monitors questions collected by type, category, source, and quality metrics.
    """

    model_config = {"arbitrary_types_allowed": True}

    by_type: Dict[str, int] = Field(default_factory=lambda: defaultdict(int))
    by_category: Dict[str, int] = Field(default_factory=lambda: defaultdict(int))
    by_source: Dict[str, int] = Field(default_factory=lambda: defaultdict(int))
    total: int = 0

    # Quality metrics
    avg_difficulty: float = 0.0
    questions_with_criteria: int = 0

    # Internal tracking (excluded from serialization)
    questions_list: List[Question] = Field(default_factory=list, exclude=True)

    def add_question(self, question: Question) -> None:
        """Update progress with new question.

        Args:
            question: Question to add to progress tracking
        """
        self.total += 1
        self.questions_list.append(question)

        # Update type distribution
        self.by_type[question.question_type] += 1

        # Update category distribution
        category = question.metadata.get("category") if question.metadata else None
        if category is None:
            category = "other"
        self.by_category[category] += 1

        # Update source distribution
        source = question.metadata.get("source", "unknown")
        self.by_source[source] += 1

        # Update quality metrics
        if question.resolution_criteria:
            self.questions_with_criteria += 1

        # Recalculate average difficulty
        difficulties = [q.difficulty for q in self.questions_list if q.difficulty]
        if difficulties:
            self.avg_difficulty = sum(difficulties) / len(difficulties)

        logger.debug(
            f"Progress: {self.total} total | "
            f"Types: {dict(self.by_type)} | "
            f"Categories: {dict(self.by_category)}"
        )

    def add_questions(self, questions: List[Question]) -> None:
        """Bulk add multiple questions.

        Args:
            questions: List of questions to add
        """
        for question in questions:
            self.add_question(question)

    def is_goal_met(self, goal: CollectionGoal) -> bool:
        """Check if we've satisfied the collection goal.

        Args:
            goal: Target collection goal

        Returns:
            True if goal is met (with tolerance), False otherwise
        """
        # Check total
        if self.total < goal.total_questions:
            logger.debug(
                f"Total not met: {self.total}/{goal.total_questions}"
            )
            return False

        # Check type distribution (with tolerance)
        for qtype, target in goal.type_distribution.items():
            actual = self.by_type.get(qtype, 0)
            min_required = int(target * goal.distribution_tolerance)

            if actual < min_required:
                logger.debug(
                    f"Type '{qtype}' not met: {actual}/{target} "
                    f"(min: {min_required})"
                )
                return False

        # Check category distribution (with tolerance)
        for category, target in goal.category_distribution.items():
            actual = self.by_category.get(category, 0)
            min_required = int(target * goal.distribution_tolerance)

            if actual < min_required:
                logger.debug(
                    f"Category '{category}' not met: {actual}/{target} "
                    f"(min: {min_required})"
                )
                return False

        logger.info("Goal met!")
        return True

    def get_type_gaps(self, goal: CollectionGoal) -> Dict[str, int]:
        """Identify gaps in question type distribution.

        Args:
            goal: Target collection goal

        Returns:
            Dict mapping question types to number needed
        """
        gaps = {}
        for qtype, target in goal.type_distribution.items():
            actual = self.by_type.get(qtype, 0)
            gap = max(0, target - actual)
            if gap > 0:
                gaps[qtype] = gap

        return gaps

    def get_category_gaps(self, goal: CollectionGoal) -> Dict[str, int]:
        """Identify gaps in category distribution.

        Args:
            goal: Target collection goal

        Returns:
            Dict mapping categories to number needed
        """
        gaps = {}
        for category, target in goal.category_distribution.items():
            actual = self.by_category.get(category, 0)
            gap = max(0, target - actual)
            if gap > 0:
                gaps[category] = gap

        return gaps

    def get_gaps(self, goal: CollectionGoal) -> Dict[str, Dict[str, int]]:
        """Identify all gaps in collection.

        Args:
            goal: Target collection goal

        Returns:
            Dict with 'types' and 'categories' gaps
        """
        return {
            "types": self.get_type_gaps(goal),
            "categories": self.get_category_gaps(goal)
        }

    def get_completion_percentage(self, goal: CollectionGoal) -> float:
        """Calculate overall completion percentage.

        Args:
            goal: Target collection goal

        Returns:
            Completion percentage (0-100)
        """
        if goal.total_questions == 0:
            return 100.0

        return min(100.0, (self.total / goal.total_questions) * 100)

    def get_summary(self, goal: CollectionGoal) -> Dict[str, Any]:
        """Get comprehensive progress summary.

        Args:
            goal: Target collection goal

        Returns:
            Dict with progress statistics
        """
        return {
            "total": self.total,
            "target": goal.total_questions,
            "completion_pct": self.get_completion_percentage(goal),
            "goal_met": self.is_goal_met(goal),
            "by_type": dict(self.by_type),
            "type_targets": goal.type_distribution,
            "type_gaps": self.get_type_gaps(goal),
            "by_category": dict(self.by_category),
            "category_targets": goal.category_distribution,
            "category_gaps": self.get_category_gaps(goal),
            "by_source": dict(self.by_source),
            "avg_difficulty": round(self.avg_difficulty, 2),
            "questions_with_criteria": self.questions_with_criteria,
        }

    def log_summary(self, goal: CollectionGoal) -> None:
        """Log progress summary.

        Args:
            goal: Target collection goal
        """
        summary = self.get_summary(goal)

        logger.info("=" * 60)
        logger.info("COLLECTION PROGRESS SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total: {summary['total']}/{summary['target']} "
                   f"({summary['completion_pct']:.1f}%)")
        logger.info(f"Goal met: {summary['goal_met']}")
        logger.info("")

        logger.info("By Type:")
        for qtype, count in summary['by_type'].items():
            target = summary['type_targets'].get(qtype, 0)
            logger.info(f"  {qtype:15} {count:3}/{target:3}")

        logger.info("")
        logger.info("By Category:")
        for category, count in summary['by_category'].items():
            target = summary['category_targets'].get(category, 0)
            logger.info(f"  {category:15} {count:3}/{target:3}")

        logger.info("")
        logger.info("By Source:")
        for source, count in summary['by_source'].items():
            logger.info(f"  {source:15} {count:3}")

        logger.info("")
        logger.info(f"Avg Difficulty: {summary['avg_difficulty']:.2f}")
        logger.info(f"With Criteria: {summary['questions_with_criteria']}/{summary['total']}")
        logger.info("=" * 60)

    def get_questions(self) -> List[Question]:
        """Get all collected questions.

        Returns:
            List of all questions added to progress tracker
        """
        return self.questions_list.copy()
