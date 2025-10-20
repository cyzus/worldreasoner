"""Tool for retrieving articles from the database."""

import json
from typing import Optional, List
from smolagents import Tool


class ArticleRetrievalTool(Tool):
    """Tool that allows agents to query and retrieve articles from the database.
    
    This tool provides flexible article retrieval by:
    - Domain filtering
    - Date range filtering
    - Source filtering
    - Keyword search in titles/content
    """
    
    name = "article_retrieval"
    description = """Query and retrieve articles from the database.
    
    Use this tool to find articles that match specific criteria.
    Useful for event identification when you need to analyze articles
    from specific domains, time periods, or containing certain topics.
    
    Args:
        domain (str, optional): Filter by domain (tech|finance|politics|health|climate|general)
        source (str, optional): Filter by source publication name
        max_results (int, optional): Maximum number of articles to return (default: 10)
        keywords (str, optional): Search for keywords in title or content (comma-separated)
    
    Returns:
        JSON string with list of articles (with content preview to save tokens)
    """
    
    inputs = {
        "domain": {
            "type": "string",
            "description": "Domain to filter by (tech|finance|politics|health|climate|general)",
            "nullable": True
        },
        "source": {
            "type": "string",
            "description": "Source publication name to filter by",
            "nullable": True
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of articles to return (default: 10)",
            "nullable": True
        },
        "keywords": {
            "type": "string",
            "description": "Comma-separated keywords to search for in title/content",
            "nullable": True
        }
    }
    output_type = "string"
    
    def __init__(self, db=None, db_path: str = None):
        """Initialize the article retrieval tool.
        
        Args:
            db: Optional Database instance
            db_path: Optional path to database file (creates new Database with schema if provided)
        """
        super().__init__()
        
        # Database setup
        self.db = None
        if db:
            self.db = db
        elif db_path:
            # Use Database wrapper which auto-creates schema
            from src.core.database import Database
            self.db = Database(db_path)
        else:
            raise ValueError("Must provide either db or db_path")
    
    def forward(
        self,
        domain: Optional[str] = None,
        source: Optional[str] = None,
        max_results: Optional[int] = 10,
        keywords: Optional[str] = None
    ) -> str:
        """Query articles from database.
        
        Args:
            domain: Optional domain filter
            source: Optional source filter
            max_results: Maximum results to return
            keywords: Optional comma-separated keywords
            
        Returns:
            JSON string with article list
        """
        from src.domain.models import Article
        
        # Build filters
        filters = {}
        if domain:
            filters['domain'] = domain
        if source:
            filters['source'] = source
        
        # Query database
        try:
            if filters:
                articles = self.db.get_many(Article, filters=filters)
            else:
                articles = self.db.get_many(Article)
        except Exception as e:
            return json.dumps({
                "error": f"Database query failed: {str(e)}",
                "filters": filters
            })
        
        # Apply keyword filtering if provided
        if keywords and articles:
            keyword_list = [k.strip().lower() for k in keywords.split(',')]
            filtered_articles = []
            for article in articles:
                # Search in title and content
                text = (article.title + " " + article.content).lower()
                if any(keyword in text for keyword in keyword_list):
                    filtered_articles.append(article)
            articles = filtered_articles
        
        # Limit results
        if max_results and len(articles) > max_results:
            articles = articles[:max_results]
        
        # Build response with content previews (not full content)
        article_list = []
        for article in articles:
            article_list.append({
                "id": article.id,
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "domain": article.domain,
                "published_date": article.published_date.isoformat(),
                "author": article.author,
                "word_count": article.word_count,
                "tags": article.tags,
                # Only include preview to save tokens
                "content_preview": article.content[:300] + "..." if len(article.content) > 300 else article.content,
                "event_ids": article.event_ids
            })
        
        response = {
            "total_found": len(articles),
            "filters_applied": {
                "domain": domain,
                "source": source,
                "keywords": keywords
            },
            "articles": article_list
        }
        
        return json.dumps(response, indent=2)
