"""Tool for retrieving full event details and linked article content."""

from typing import List, Optional
from smolagents import Tool
from src.data.models import Event, Article


class EventDetailsTool(Tool):
    """Tool that provides full event details including linked article content.
    
    The agent can use this tool to get more context about events before
    generating questions, allowing for deeper, more insightful questions.
    """
    
    name = "event_details"
    description = """Get full details about a specific event including linked article content.
    
    Use this tool when you need more information about an event to generate
    high-quality, insightful forecast questions. This gives you access to:
    - Full event description (not truncated)
    - Complete article content from source articles
    - All event metadata and entities
    
    Args:
        event_id: The ID of the event to get details for
    
    Returns:
        Dictionary with full event details and article content
    """
    
    inputs = {
        "event_id": {
            "type": "string",
            "description": "The ID of the event (e.g., 'evt_tech_20251019_001')"
        }
    }
    output_type = "string"
    
    def __init__(self, events: List[Event], articles: List[Article]):
        """Initialize tool with events and articles.
        
        Args:
            events: List of all events available
            articles: List of all articles available
        """
        super().__init__()
        self.events_by_id = {event.id: event for event in events}
        self.articles_by_id = {article.id: article for article in articles}
    
    def forward(self, event_id: str) -> str:
        """Get full details for an event.
        
        Args:
            event_id: Event ID to look up
            
        Returns:
            JSON string with event details and article content
        """
        import json
        
        # Find the event
        event = self.events_by_id.get(event_id)
        if not event:
            return json.dumps({
                "error": f"Event '{event_id}' not found",
                "available_events": list(self.events_by_id.keys())
            })
        
        # Get linked articles
        linked_articles = []
        for article_id in event.article_ids:
            article = self.articles_by_id.get(article_id)
            if article:
                linked_articles.append({
                    "id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source": article.source,
                    "published_date": str(article.published_date),
                    "content": article.content,  # Full content!
                    "word_count": article.word_count
                })
        
        # Build comprehensive response
        response = {
            "event": {
                "id": event.id,
                "title": event.title,
                "description": event.description,  # Full description
                "occurred_date": str(event.occurred_date) if event.occurred_date else None,
                "predicted_date": str(event.predicted_date) if event.predicted_date else None,
                "event_type": event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
                "domain": event.domain,
                "status": event.status.value if hasattr(event.status, 'value') else event.status,
                "entities": event.entities,
                "metadata": event.metadata,
                "tags": event.tags if hasattr(event, 'tags') else []
            },
            "linked_articles": linked_articles,
            "summary": f"Event '{event.title}' with {len(linked_articles)} linked article(s)"
        }
        
        return json.dumps(response, indent=2)
