"""Base classes and utilities for prompt generation."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, TypeVar, Generic, Tuple
from dataclasses import dataclass


T = TypeVar("T")


@dataclass
class PromptTemplate:
    """A reusable prompt template with variable substitution."""

    template: str
    required_vars: List[str]
    optional_vars: Dict[str, str] = None  # var_name -> default_value

    def format(self, **kwargs) -> str:
        """Format the template with provided variables.

        Args:
            **kwargs: Variables to substitute in the template

        Returns:
            Formatted prompt string

        Raises:
            ValueError: If required variables are missing
        """
        # Check required variables
        missing = [var for var in self.required_vars if var not in kwargs]
        if missing:
            raise ValueError(f"Missing required variables: {missing}")

        # Add optional variables with defaults
        if self.optional_vars:
            for var, default in self.optional_vars.items():
                if var not in kwargs:
                    kwargs[var] = default

        return self.template.format(**kwargs)


class BasePromptGenerator(ABC, Generic[T]):
    """Base class for prompt generators.

    Provides common functionality for formatting and generating prompts.
    """

    @staticmethod
    def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d") -> str:
        """Format a datetime consistently.

        Args:
            dt: Datetime to format
            format_str: Format string (default: YYYY-MM-DD)

        Returns:
            Formatted date string
        """
        return dt.strftime(format_str)

    @staticmethod
    def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to a maximum length.

        Args:
            text: Text to truncate
            max_length: Maximum length
            suffix: Suffix to add if truncated

        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text
        return text[: max_length - len(suffix)] + suffix

    @staticmethod
    def format_list(
        items: List[str], separator: str = ", ", empty_value: str = "None"
    ) -> str:
        """Format a list of items as a string.

        Args:
            items: List of items to format
            separator: Separator between items
            empty_value: Value to return if list is empty

        Returns:
            Formatted string
        """
        return separator.join(items) if items else empty_value

    @staticmethod
    def format_content_preview(
        content: str, max_length: int = 300, suffix: str = "..."
    ) -> str:
        """Format content preview with consistent truncation.

        Args:
            content: Content to preview
            max_length: Maximum length (default: 300)
            suffix: Suffix to add if truncated

        Returns:
            Truncated content preview
        """
        return BasePromptGenerator.truncate_text(content, max_length, suffix)

    @staticmethod
    def build_priority_guidance(
        type_hints: Optional[List[str]] = None,
        category_hints: Optional[List[str]] = None,
        time_horizon_hints: Optional[List[str]] = None,
        prefix: str = "\n\n⚠️ COLLECTION PRIORITIES:\n",
    ) -> str:
        """Build priority guidance section from hints.

        Args:
            type_hints: Priority types needed (e.g., ["boolean", "mcq"])
            category_hints: Priority categories needed (e.g., ["finance", "tech"])
            time_horizon_hints: Priority time horizons needed (e.g., ["medium"])
            prefix: Prefix for the guidance section

        Returns:
            Formatted priority guidance string, or empty string if no hints
        """
        if not type_hints and not category_hints and not time_horizon_hints:
            return ""

        guidance_parts = []
        if type_hints:
            guidance_parts.append(
                f"PRIORITY TYPES NEEDED: {BasePromptGenerator.format_list(type_hints)}"
            )
        if category_hints:
            guidance_parts.append(
                f"PRIORITY CATEGORIES NEEDED: {BasePromptGenerator.format_list(category_hints)}"
            )
        if time_horizon_hints:
            # Provide specific day ranges for each horizon
            from src.config.collection_goal import TimeHorizon

            horizon_descriptions = []
            for h in time_horizon_hints:
                try:
                    th = TimeHorizon(h)
                    min_d, max_d = TimeHorizon.get_day_range(th)
                    horizon_descriptions.append(f"{h} ({min_d}-{max_d} days)")
                except ValueError:
                    horizon_descriptions.append(h)
            guidance_parts.append(
                f"PRIORITY TIME HORIZONS NEEDED: {', '.join(horizon_descriptions)}"
            )
            guidance_parts.append(
                "Generate questions where the time between when the question becomes forecastable "
                "(estimated_start_time) and its resolution_date falls within the specified horizon range."
            )

        focus_items = []
        if type_hints:
            focus_items.append("types")
        if category_hints:
            focus_items.append("categories")
        if time_horizon_hints:
            focus_items.append("time horizons")
        return (
            prefix
            + "\n".join(guidance_parts)
            + f"\nFocus on generating questions matching these {'/'.join(focus_items)} first!"
        )

    @staticmethod
    def build_domain_options(
        category_hints: Optional[List[str]] = None, fallback_enum=None
    ) -> str:
        """Build domain options string from hints or enum.

        Args:
            category_hints: Priority categories to use
            fallback_enum: Enum class to use if no hints (e.g., Domain)

        Returns:
            Formatted domain options string like "One of (finance, tech, sports)"
        """
        if category_hints:
            return f"One of ({', '.join(category_hints)})"
        elif fallback_enum:
            from src.utils.enums import enum_to_list

            return f"One of ({', '.join(enum_to_list(fallback_enum))})"
        else:
            return "One of the available domains"

    @abstractmethod
    def format_item(self, item: T, idx: int, **context) -> str:
        """Format a single item for inclusion in a prompt.

        Args:
            item: Item to format
            idx: Index of the item (1-based)
            **context: Additional context (e.g., current_date)

        Returns:
            Formatted item string
        """
        pass

    def format_items(self, items: List[T], **context) -> str:
        """Format multiple items for inclusion in a prompt.

        Args:
            items: List of items to format
            **context: Additional context

        Returns:
            Formatted items string
        """
        formatted = []
        for idx, item in enumerate(items, 1):
            formatted.append(self.format_item(item, idx, **context))
        return "\n".join(formatted)

    @abstractmethod
    def get_instruction(self, **kwargs) -> str:
        """Generate the full instruction prompt.

        Args:
            **kwargs: Context and configuration for the prompt

        Returns:
            Complete instruction string
        """
        pass


class ContextualPromptGenerator(BasePromptGenerator[T]):
    """Prompt generator that includes datetime context by default."""

    def build_instruction(
        self,
        current_date: datetime,
        instruction_body: str,
        include_date_header: bool = True,
    ) -> str:
        """Build complete instruction with optional date context header.

        This is the standard way to construct instructions with date context.
        Prevents duplication if instruction already has date header.

        Args:
            current_date: Current datetime
            instruction_body: Main instruction content
            include_date_header: Whether to prepend date header (default: True)

        Returns:
            Complete instruction string
        """
        if not include_date_header:
            return instruction_body

        date_str = self.format_datetime(current_date)

        # Don't duplicate if instruction already has date header
        if instruction_body.strip().startswith("Today's date is"):
            return instruction_body

        return f"Today's date is {date_str}.\n\n{instruction_body}"

    @staticmethod
    def calculate_date_window(
        current_date: datetime,
        require_past_events: bool,
        events: Optional[List] = None,
        future_days: int = 365,
    ) -> Tuple[datetime, datetime]:
        """Calculate resolution date window for questions.

        Args:
            current_date: Current datetime
            require_past_events: True for ground truth mode, False for predictions
            events: Optional list of events to determine min date from
            future_days: Days in future for prediction mode (default: 365)

        Returns:
            Tuple of (min_date, max_date) for resolution window
        """
        from datetime import timedelta

        if require_past_events:
            # Ground truth mode: Use past events only
            if events:
                event_dates = [
                    e.occurred_date or e.predicted_date
                    for e in events
                    if (e.occurred_date or e.predicted_date)
                    and (e.occurred_date or e.predicted_date) < current_date
                ]
                min_date = (
                    min(event_dates)
                    if event_dates
                    else current_date - timedelta(days=365)
                )
            else:
                min_date = current_date - timedelta(days=365)
            max_date = current_date
        else:
            # Future prediction mode
            min_date = current_date
            max_date = current_date + timedelta(days=future_days)

        return min_date, max_date
