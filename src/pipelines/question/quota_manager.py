"""Quota management for collection sources."""

from typing import Optional

from .progress import CollectionProgress
from src.config.collection_goal import CollectionGoal
from src.utils.logging import logger


class QuotaManager:
    """Manages source quotas and calculates collection amounts."""

    def __init__(self, goal: CollectionGoal):
        """Initialize quota manager.

        Args:
            goal: Collection goal with quotas
        """
        self.goal = goal

    def calculate_needed_from_source(
        self,
        source_name: str,
        progress: CollectionProgress,
    ) -> int:
        """Calculate how many questions to request from a source.

        Args:
            source_name: Name of the source
            progress: Current collection progress

        Returns:
            Number of questions to request (0 if quota met)
        """
        # Already collected from this source
        already_from_source = progress.by_source.get(source_name, 0)

        # Source quota
        source_quota = self.goal.source_quotas.get(source_name, 100)

        # Remaining quota for source
        source_remaining = source_quota - already_from_source

        # Overall remaining
        overall_remaining = self.goal.total_questions - progress.total

        # Type gaps
        type_gaps = progress.get_type_gaps(self.goal)
        type_gap_total = sum(type_gaps.values()) if type_gaps else source_quota

        # Return minimum of all constraints
        needed = max(0, min(source_remaining, overall_remaining, type_gap_total))

        if needed > 0:
            logger.debug(
                f"Quota calc for '{source_name}': "
                f"source_remaining={source_remaining}, "
                f"overall_remaining={overall_remaining}, "
                f"type_gap_total={type_gap_total} "
                f"→ needed={needed}"
            )

        return needed

    def has_quota_available(
        self,
        source_name: str,
        progress: CollectionProgress
    ) -> bool:
        """Check if source has quota remaining.

        Args:
            source_name: Name of the source
            progress: Current collection progress

        Returns:
            True if quota available
        """
        return self.calculate_needed_from_source(source_name, progress) > 0
