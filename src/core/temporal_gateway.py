"""Temporal Gateway - Control information access based on cutoff dates.

This module ensures temporal validity in forecasting by restricting access to
information published or occurred before a specified cutoff date.
"""

import contextvars
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass

from src.utils.logging import logger
from src.services.temporal_filter_service import TemporalFilterService

if TYPE_CHECKING:
    from src.domain.models import Article, Event, Question, Forecast


@dataclass
class ValidationResult:
    """Result of temporal validation."""

    valid: bool
    errors: List[str]
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    def add_error(self, error: str) -> None:
        """Add validation error."""
        self.errors.append(error)
        self.valid = False

    def add_warning(self, warning: str) -> None:
        """Add validation warning."""
        self.warnings.append(warning)


class TemporalGateway:
    """Control information access based on cutoff dates.

    The TemporalGateway ensures that forecasts only use information available
    before a specified cutoff date. This is critical for valid forecasting
    benchmarks - without it, LLMs could access future information or outcomes.

    Example:
        >>> gateway = TemporalGateway(cutoff_date=datetime(2024, 11, 4, tzinfo=timezone.utc))
        >>> accessible_articles = gateway.filter_articles(all_articles)
        >>> # Only articles published before Nov 4, 2024 are included
    """

    def __init__(self, cutoff_date: datetime):
        """Initialize gateway with cutoff date.

        Args:
            cutoff_date: Latest date for accessible information (timezone-aware)

        Raises:
            ValueError: If cutoff_date is not timezone-aware
        """
        if cutoff_date.tzinfo is None:
            raise ValueError(
                "cutoff_date must be timezone-aware (use datetime.now(timezone.utc))"
            )

        self.cutoff_date = cutoff_date
        logger.debug(
            f"TemporalGateway initialized with cutoff: {cutoff_date.isoformat()}"
        )

    def filter_articles(self, articles: List["Article"]) -> List["Article"]:
        """Filter articles to only those published before cutoff.

        Delegates to TemporalFilterService for filtering logic.

        Args:
            articles: List of articles to filter

        Returns:
            List of articles with published_date < cutoff_date (strictly before)
        """
        if not articles:
            return []

        # Delegate to TemporalFilterService
        filtered = TemporalFilterService.filter_by_cutoff(
            articles, self.cutoff_date, date_field="published_date"
        )

        # Log filtered count for debugging
        filtered_count = len(articles) - len(filtered)
        if filtered_count > 0:
            logger.debug(
                f"Filtered {filtered_count} articles published after {self.cutoff_date.isoformat()}"
            )

        return filtered

    def filter_events(self, events: List["Event"]) -> List["Event"]:
        """Filter events to only those that occurred before cutoff.

        Delegates to TemporalFilterService for filtering logic.

        Args:
            events: List of events to filter

        Returns:
            List of events with occurred_date < cutoff_date (strictly before)

        Note:
            Events with occurred_date=None are excluded (conservative approach)
        """
        if not events:
            return []

        # Count events without dates (for logging)
        none_date_count = sum(1 for e in events if e.occurred_date is None)

        # Delegate to TemporalFilterService
        filtered = TemporalFilterService.filter_by_cutoff(
            events, self.cutoff_date, date_field="occurred_date"
        )

        # Log filtered counts
        filtered_count = len(events) - len(filtered) - none_date_count
        if filtered_count > 0 or none_date_count > 0:
            logger.debug(
                f"Filtered {filtered_count} future events and {none_date_count} "
                f"events with None occurred_date"
            )

        return filtered

    def is_article_accessible(self, article: "Article") -> bool:
        """Check if a single article is accessible.

        Uses TemporalFilterService for consistency.

        Args:
            article: Article to check

        Returns:
            True if article.published_date < cutoff_date (strictly before)
        """
        if article.published_date is None:
            logger.warning(f"Article {article.id} has None published_date - rejecting")
            return False

        # Use TemporalFilterService for single-item check
        result = TemporalFilterService.filter_by_cutoff(
            [article], self.cutoff_date, date_field="published_date"
        )

        return len(result) > 0

    def is_event_accessible(self, event: "Event") -> bool:
        """Check if a single event is accessible.

        Uses TemporalFilterService for consistency.

        Args:
            event: Event to check

        Returns:
            True if event.occurred_date < cutoff_date (strictly before)
            False if occurred_date is None (conservative approach)
        """
        if event.occurred_date is None:
            # Conservative: reject events without occurred_date
            return False

        # Use TemporalFilterService for single-item check
        result = TemporalFilterService.filter_by_cutoff(
            [event], self.cutoff_date, date_field="occurred_date"
        )

        return len(result) > 0

    def validate_forecast(
        self, forecast: "Forecast", question: "Question", db=None
    ) -> ValidationResult:
        """Validate that a forecast respects temporal constraints.

        Checks:
        1. Forecast simulated_date <= question.cutoff_date
        2. All accessed articles published before cutoff
        3. All identified events occurred before cutoff

        Args:
            forecast: Forecast to validate
            question: Question being forecasted
            db: Optional database to load articles/events (GenericDatabase)

        Returns:
            ValidationResult with valid flag and error messages
        """
        from src.domain.models import Article, Event

        result = ValidationResult(valid=True, errors=[], warnings=[])

        # Check cutoff_date exists
        if question.cutoff_date is None:
            result.add_warning(
                "Question has no cutoff_date - using creation date as fallback"
            )
            cutoff = question.created_at
        else:
            cutoff = question.cutoff_date

        # Check simulated_date
        if forecast.simulated_date is not None:
            if forecast.simulated_date > cutoff:
                result.add_error(
                    f"Forecast simulated_date ({forecast.simulated_date.isoformat()}) "
                    f"is after cutoff ({cutoff.isoformat()})"
                )

        # Check accessed articles if database provided
        if db is not None and forecast.articles_accessed:
            for article_id in forecast.articles_accessed:
                article = db.get(Article, article_id)

                if article is None:
                    result.add_warning(f"Article {article_id} not found in database")
                    continue

                if not self.is_article_accessible(article):
                    result.add_error(
                        f"Accessed article {article_id} published after cutoff "
                        f"({article.published_date.isoformat()} > {cutoff.isoformat()})"
                    )

        # Check identified events if database provided
        if db is not None and forecast.identified_events:
            for event_id in forecast.identified_events:
                event = db.get(Event, event_id)

                if event is None:
                    result.add_warning(f"Event {event_id} not found in database")
                    continue

                if event.occurred_date is not None and not self.is_event_accessible(
                    event
                ):
                    result.add_error(
                        f"Identified event {event_id} occurred after cutoff "
                        f"({event.occurred_date.isoformat()} > {cutoff.isoformat()})"
                    )

        if result.valid:
            logger.info(f"Forecast {forecast.id} passed temporal validation")
        else:
            logger.warning(
                f"Forecast {forecast.id} FAILED temporal validation: {len(result.errors)} errors"
            )

        return result

    def get_accessible_article_ids(self, all_article_ids: List[str], db) -> List[str]:
        """Get list of article IDs that are accessible.

        Args:
            all_article_ids: List of article IDs to check
            db: Database to load articles (GenericDatabase)

        Returns:
            List of article IDs that pass temporal check
        """
        from src.domain.models import Article

        accessible = []

        for article_id in all_article_ids:
            article = db.get(Article, article_id)
            if article and self.is_article_accessible(article):
                accessible.append(article_id)

        return accessible

    def get_accessible_event_ids(self, all_event_ids: List[str], db) -> List[str]:
        """Get list of event IDs that are accessible.

        Args:
            all_event_ids: List of event IDs to check
            db: Database to load events (GenericDatabase)

        Returns:
            List of event IDs that pass temporal check
        """
        from src.domain.models import Event

        accessible = []

        for event_id in all_event_ids:
            event = db.get(Event, event_id)
            if event and self.is_event_accessible(event):
                accessible.append(event_id)

        return accessible


# Module-level ContextVar for async/thread-safe temporal state
_temporal_cutoff_var: contextvars.ContextVar[Optional[datetime]] = (
    contextvars.ContextVar("temporal_cutoff", default=None)
)


class TemporalContext:
    """Async/thread-safe context for temporal constraints.

    Uses contextvars.ContextVar for safe concurrent access in async
    frameworks (FastAPI, asyncio) and threaded environments.

    Usage as context manager:
        >>> with TemporalContext(cutoff_date=question.cutoff_date):
        ...     # All operations in this block respect the cutoff
        ...     articles = db.get_articles()
    """

    def __init__(self, cutoff_date: datetime):
        """Initialize temporal context.

        Args:
            cutoff_date: Cutoff date for this context
        """
        if cutoff_date.tzinfo is None:
            raise ValueError("cutoff_date must be timezone-aware")

        self.cutoff_date = cutoff_date
        self._token: Optional[contextvars.Token] = None

    def __enter__(self):
        """Enter context - set cutoff date."""
        self._token = _temporal_cutoff_var.set(self.cutoff_date)
        logger.debug(
            f"Entered TemporalContext with cutoff: {self.cutoff_date.isoformat()}"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - restore previous cutoff."""
        if self._token is not None:
            _temporal_cutoff_var.reset(self._token)
            self._token = None
        logger.debug("Exited TemporalContext")
        return False

    @classmethod
    def get_current_cutoff(cls) -> Optional[datetime]:
        """Get the currently active cutoff date.

        Returns:
            Current cutoff date if in temporal context, None otherwise
        """
        return _temporal_cutoff_var.get()

    @classmethod
    def is_active(cls) -> bool:
        """Check if a temporal context is currently active.

        Returns:
            True if inside a TemporalContext block
        """
        return _temporal_cutoff_var.get() is not None
