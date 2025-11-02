"""Tool for retrieving articles from the database."""

import json
from typing import Optional, List
from smolagents import Tool


class ArticleRetrievalTool(Tool):
    """Tool that retrieves full article content by article ID.

    Use this when you need the complete article text for an article
    you've identified (e.g., from event details or article lists).
    """

    name = "article_retrieval"
    description = """Retrieve full article content by article ID.

    Use this tool when you have an article ID and need to read its full content.
    Article IDs can be found in event details (event.article_ids) or other sources.

    Args:
        article_id (str): The ID of the article to retrieve (e.g., "art_tech_20251101_001_abc123")

    Returns:
        JSON string with full article content
    """

    inputs = {
        "article_id": {
            "type": "string",
            "description": "The ID of the article to retrieve"
        }
    }
    output_type = "string"
    
    def __init__(self, db=None, db_path: str = None):
        """Initialize the article retrieval tool.

        Args:
            db: Optional Database instance
            db_path: Optional path to database file (creates new Database if provided)

        Note:
            If neither db nor db_path is provided, will use default database path
        """
        super().__init__()

        # Database setup (always use database)
        if db:
            self.db = db
        elif db_path:
            from src.core.database import Database
            self.db = Database(db_path)
        else:
            # Use default database path
            from src.core.database import Database
            self.db = Database("worldreasoner.db")
    
    def forward(self, article_id: str) -> str:
        """Retrieve article by ID.

        Args:
            article_id: Article ID to retrieve

        Returns:
            JSON string with full article content
        """
        from src.domain.models import Article

        # Fetch article from database
        try:
            article = self.db.get_article(article_id)
        except AttributeError:
            # Fallback if db doesn't have get_article method
            article = self.db.get(Article, article_id)

        if not article:
            # Get available articles for helpful error message
            try:
                all_articles = self.db.get_articles()
                available_ids = [a.id for a in all_articles[:10]]
            except:
                all_articles = self.db.get_many(Article)
                available_ids = [a.id for a in all_articles[:10]]

            return json.dumps({
                "error": f"Article '{article_id}' not found in database",
                "available_articles": available_ids
            })

        # Return full article content
        response = {
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "source": article.source,
            "domain": article.domain.value if hasattr(article.domain, 'value') else article.domain,
            "published_date": article.published_date.isoformat(),
            "author": article.author,
            "word_count": article.word_count,
            "tags": article.tags,
            "content": article.content,  # Full content!
            "event_ids": article.event_ids
        }

        return json.dumps(response, indent=2)
