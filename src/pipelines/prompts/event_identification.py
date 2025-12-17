"""Prompts for event identification stage."""

from datetime import datetime
from typing import List, Optional
from src.domain.models import Article, Domain
from src.utils.enums import enum_to_list
from .base import ContextualPromptGenerator, PromptTemplate

ARTICLE_TEMPLATE = \
"""
Article {idx} (ID: {article_id}):
- Title: {title}
- Source: {source}
- Published: {published_date}
- Domain: {domain}
- Content Preview: {content_preview}
"""

IDENTIFICATION_PROMPT = \
"""
Analyze the following {num_articles} articles and identify events that would make good forecast questions.

{articles_text}

FOCUS ON events about:
- Elections, major companies (Apple/Tesla/Google), crypto/stock milestones, product launches, sports
SKIP:
- Niche legal disputes, minor corporate changes, insider-knowledge topics

For each event you identify:
1. Retrieve associated article details if helpful.
2. Extract event attributes (title, description, domain, occurred_date, event_type, source_article_ids)

After analyzing all articles, call {tool_name} tool ONCE with a JSON array containing ALL events.
Each event should have:
- title: Short event title
- description: Detailed description
- domain: {domain_options}
- occurred_date: ISO date format (YYYY-MM-DD)
- event_type: One of (decision, outcome, indicator, milestone, external_shock)
- source_article_ids: Comma-separated article IDs

Only include events with confidence >= {confidence_threshold}.

Call final_answer only after you finish the task.
"""


class EventIdentificationPrompts(ContextualPromptGenerator[Article]):
    """Prompts for the event identification stage."""
    
    # Template for formatting individual articles
    ARTICLE_TEMPLATE = PromptTemplate(
        template=ARTICLE_TEMPLATE,
        required_vars=["idx", "article_id", "title", "source", "published_date", "domain", "content_preview"]
    )
    
    # Template for the main identification instruction
    IDENTIFICATION_TEMPLATE = PromptTemplate(
        template=IDENTIFICATION_PROMPT,
        required_vars=["num_articles", "articles_text", "confidence_threshold", "domain_options"],
        optional_vars={"tool_name": "batch_event_identifier"}
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
        tool_name: str = "batch_event_identifier",
        category_hints: Optional[List[str]] = None
    ) -> str:
        """Generate instruction for event identification.

        Args:
            current_date: Current datetime
            articles: List of articles to analyze
            confidence_threshold: Minimum confidence threshold
            content_preview_length: Length of content preview (default: 300)
            tool_name: Name of the tool to call (default: batch_event_identifier)
            category_hints: Priority categories/domains needed (e.g., ["finance", "tech"])

        Returns:
            Formatted instruction string
        """
        date_str = self.format_datetime(current_date)
        
        # Format all articles
        articles_text = self.format_items(
            articles,
            content_preview_length=content_preview_length
        )
        
        # Build domain options from category hints (fully adaptive)
        if category_hints:
            domain_options = f"One of ({', '.join(category_hints)})"
        else:
            # Fallback: use actual Domain enum values to ensure consistency
            domain_options = f"One of ({', '.join(enum_to_list(Domain))})"
        
        # Build priority guidance from hints
        priority_guidance = ""
        if category_hints:
            priority_guidance = f"\n\n⚠️ PRIORITY DOMAINS NEEDED: {self.format_list(category_hints)}\nFocus on identifying events in these domains first!"
        
        # Format the instruction body
        instruction_body = self.IDENTIFICATION_TEMPLATE.format(
            num_articles=len(articles),
            articles_text=articles_text,
            confidence_threshold=confidence_threshold,
            domain_options=domain_options,
            tool_name=tool_name
        )
        
        # Add priority guidance if provided
        if priority_guidance:
            instruction_body = instruction_body + priority_guidance
        
        return f"Today's date is {date_str}.\n\n{instruction_body}"
    
