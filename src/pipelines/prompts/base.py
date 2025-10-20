"""Base classes and utilities for prompt generation."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar, Generic
from dataclasses import dataclass


T = TypeVar('T')


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
    def format_datetime(dt: datetime, format_str: str = '%Y-%m-%d') -> str:
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
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def format_list(items: List[str], separator: str = ", ", empty_value: str = "None") -> str:
        """Format a list of items as a string.
        
        Args:
            items: List of items to format
            separator: Separator between items
            empty_value: Value to return if list is empty
            
        Returns:
            Formatted string
        """
        return separator.join(items) if items else empty_value
    
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
    
    def get_instruction_with_context(
        self,
        current_date: datetime,
        **kwargs
    ) -> str:
        """Generate instruction with datetime context.
        
        Args:
            current_date: Current datetime
            **kwargs: Additional context and configuration
            
        Returns:
            Complete instruction string with date context
        """
        date_str = self.format_datetime(current_date)
        context_header = f"Today's date is {date_str}.\n\n"
        
        # Get the main instruction
        instruction = self.get_instruction(current_date=current_date, **kwargs)
        
        # If instruction doesn't already start with date context, prepend it
        if not instruction.startswith("Today's date is"):
            instruction = context_header + instruction
        
        return instruction
