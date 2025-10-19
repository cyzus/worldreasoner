"""Prompts for article collection stage."""

from datetime import datetime
from typing import Optional
from .base import ContextualPromptGenerator, PromptTemplate


class ArticleCollectionPrompts(ContextualPromptGenerator[None]):
    """Prompts for the article collection stage."""
    
    # Template for the main collection instruction
    COLLECTION_TEMPLATE = PromptTemplate(
        template="""Search for news articles about "{source_name}" from the past {days_back} days.
Find up to {max_articles} relevant articles.{domain_context}

For each article you find:
1. Use web_search to find article URLs
2. Call {tool_name} with ONLY the URL and metadata (title, source, date, author if available)
3. Do NOT pass article content - the tool will fetch it internally to save tokens

Return a summary when done.""",
        required_vars=["source_name", "days_back", "max_articles"],
        optional_vars={"domain_context": "", "tool_name": "article_collector"}
    )
    
    def format_item(self, item: None, idx: int, **context) -> str:
        """Not used for article collection (no items to format)."""
        return ""
    
    def get_instruction(
        self,
        current_date: datetime,
        source_name: str,
        days_back: int,
        max_articles: int,
        domain_context: str = "",
        tool_name: str = "article_collector"
    ) -> str:
        """Generate instruction for article collection.
        
        Args:
            current_date: Current datetime
            source_name: Name of the source to search
            days_back: Number of days to look back
            max_articles: Maximum number of articles to collect
            domain_context: Optional domain context string
            tool_name: Name of the tool to call (default: article_collector)
            
        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)
        
        # Format the instruction body
        instruction_body = self.COLLECTION_TEMPLATE.format(
            source_name=source_name,
            days_back=days_back,
            max_articles=max_articles,
            domain_context=domain_context,
            tool_name=tool_name
        )
        
        return f"Today's date is {date_str}.\n\n{instruction_body}"
    
    @staticmethod
    def get_collection_instruction(
        current_date: datetime,
        source_name: str,
        days_back: int,
        max_articles: int,
        domain_context: str = ""
    ) -> str:
        """Static convenience method for backward compatibility.
        
        Args:
            current_date: Current datetime
            source_name: Name of the source to search
            days_back: Number of days to look back
            max_articles: Maximum number of articles to collect
            domain_context: Optional domain context string
            
        Returns:
            Formatted instruction string
        """
        generator = ArticleCollectionPrompts()
        return generator.get_instruction(
            current_date=current_date,
            source_name=source_name,
            days_back=days_back,
            max_articles=max_articles,
            domain_context=domain_context
        )
