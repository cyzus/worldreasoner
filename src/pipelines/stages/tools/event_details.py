"""Tool for retrieving full event details and linked article content."""

from typing import List, Optional, TYPE_CHECKING
from smolagents import Tool
from src.domain.models import Event, Article

if TYPE_CHECKING:
    from src.core.database import Database


class EventDetailsTool(Tool):
    """Tool that provides full event details including linked article content.
    
    The agent can use this tool to get more context about events before
    generating questions, allowing for deeper, more insightful questions.
    
    Can work with either in-memory data or database backend.
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
    
    def __init__(
        self, 
        events: Optional[List[Event]] = None, 
        articles: Optional[List[Article]] = None,
        db: Optional["Database"] = None,
        db_path: Optional[str] = None
    ):
        """Initialize tool with either in-memory data or database.
        
        Args:
            events: Optional list of events (for in-memory mode)
            articles: Optional list of articles (for in-memory mode)
            db: Optional Database instance (for database mode)
            db_path: Optional path to database file (creates new Database if provided)
            
        Note:
            Priority: db > db_path > in-memory (events + articles)
        """
        super().__init__()
        
        # Database mode
        if db:
            self.db = db
            self.use_db = True
        elif db_path:
            # Lazy import to avoid circular dependency
            from src.core.database import Database
            self.db = Database(db_path)
            self.use_db = True
        # In-memory mode
        elif events is not None and articles is not None:
            self.events_by_id = {event.id: event for event in events}
            self.articles_by_id = {article.id: article for article in articles}
            self.db = None
            self.use_db = False
        else:
            raise ValueError(
                "Must provide either (events + articles) for in-memory mode, "
                "or (db) or (db_path) for database mode"
            )
    
    def forward(self, event_id: str) -> str:
        """Get full details for an event.
        
        Args:
            event_id: Event ID to look up
            
        Returns:
            JSON string with event details and article content
        """
        import json
        
        if self.use_db:
            return self._forward_db(event_id)
        else:
            return self._forward_memory(event_id)
    
    def _forward_db(self, event_id: str) -> str:
        """Get event details from database.
        
        Args:
            event_id: Event ID to look up
            
        Returns:
            JSON string with event details
        """
        import json
        
        # Fetch event from database
        event = self.db.get_event(event_id)
        if not event:
            # Get available events for helpful error message
            all_events = self.db.get_events()
            return json.dumps({
                "error": f"Event '{event_id}' not found in database",
                "available_events": [e.id for e in all_events[:10]]  # First 10
            })
        
        # Fetch linked articles from database
        linked_articles = []
        if event.article_ids:
            articles = self.db.get_articles(event.article_ids)
            for article in articles:
                linked_articles.append({
                    "id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source": article.source,
                    "published_date": str(article.published_date),
                    "content": article.content,  # Full content!
                    "word_count": article.word_count
                })
        
        # Build response
        response = self._build_response(event, linked_articles)
        return json.dumps(response, indent=2)
    
    def _forward_memory(self, event_id: str) -> str:
        """Get event details from in-memory data.
        
        Args:
            event_id: Event ID to look up
            
        Returns:
            JSON string with event details
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
        
        # Build response
        response = self._build_response(event, linked_articles)
        return json.dumps(response, indent=2)
    
    def _build_response(self, event: Event, linked_articles: List[dict]) -> dict:
        """Build standardized response structure.
        
        Args:
            event: Event object
            linked_articles: List of article dicts
            
        Returns:
            Response dictionary
        """
        return {
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

