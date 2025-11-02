"""Prompts for event identification stage."""

from datetime import datetime
from typing import List
from src.domain.models import Article
from .base import ContextualPromptGenerator, PromptTemplate


class EventIdentificationPrompts(ContextualPromptGenerator[Article]):
    """Prompts for the event identification stage."""
    
    # Template for formatting individual articles
    ARTICLE_TEMPLATE = PromptTemplate(
        template="""
Article {idx} (ID: {article_id}):
- Title: {title}
- Source: {source}
- Published: {published_date}
- Domain: {domain}
- Content Preview: {content_preview}
""",
        required_vars=["idx", "article_id", "title", "source", "published_date", "domain", "content_preview"]
    )
    
    # Template for the main identification instruction
    IDENTIFICATION_TEMPLATE = PromptTemplate(
        template="""Analyze the following {num_articles} articles and identify significant events mentioned.

{articles_text}

For each event you identify:
1. Retrieve associated article details if helpful.
2. Extract event attributes
3. Call {tool_name} tool to store the events
4. Include the article ID in source_article_ids

Only include events with confidence >= {confidence_threshold}.
Return a summary when done.""",
        required_vars=["num_articles", "articles_text", "confidence_threshold"],
        optional_vars={"tool_name": "event_identifier"}
    )
    
    def format_item(
        self,
        item: Article,
        idx: int,
        content_preview_length: int = 300,
        **context
    ) -> str:
        """Format a single article for the prompt.
        
        Args:
            item: Article to format
            idx: Index of the article (1-based)
            content_preview_length: Length of content preview (default: 300)
            **context: Additional context (not used)
            
        Returns:
            Formatted article summary
        """
        content_preview = self.truncate_text(
            item.content,
            max_length=content_preview_length,
            suffix="..."
        )
        
        return self.ARTICLE_TEMPLATE.format(
            idx=idx,
            article_id=item.id,
            title=item.title,
            source=item.source,
            published_date=item.published_date,
            domain=item.domain,
            content_preview=content_preview
        )
    
    def get_instruction(
        self,
        current_date: datetime,
        articles: List[Article],
        confidence_threshold: float,
        content_preview_length: int = 300,
        tool_name: str = "event_identifier"
    ) -> str:
        """Generate instruction for event identification.
        
        Args:
            current_date: Current datetime
            articles: List of articles to analyze
            confidence_threshold: Minimum confidence threshold
            content_preview_length: Length of content preview (default: 300)
            tool_name: Name of the tool to call (default: event_identifier)
            
        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)
        
        # Format all articles
        articles_text = self.format_items(
            articles,
            content_preview_length=content_preview_length
        )
        
        # Format the instruction body
        instruction_body = self.IDENTIFICATION_TEMPLATE.format(
            num_articles=len(articles),
            articles_text=articles_text,
            confidence_threshold=confidence_threshold,
            tool_name=tool_name
        )
        
        return f"Today's date is {date_str}.\n\n{instruction_body}"
    
