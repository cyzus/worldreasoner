"""Tool for retrieving articles from the database."""

import json
from typing import Optional, List
from src.tools.database_mixin import DatabaseAwareTool
from src.domain.models import Article


class ArticleRetrievalTool(DatabaseAwareTool):
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
            db: Optional GenericDatabase instance
            db_path: Optional path to database file (creates new GenericDatabase if provided)

        Note:
            If neither db nor db_path is provided, will use default database path
        """
        super().__init__(db=db, db_path=db_path, ensure_tables=[Article])
    
    def forward(self, article_id: str) -> str:
        """Retrieve article by ID.

        Args:
            article_id: Article ID to retrieve

        Returns:
            JSON string with full article content
        """
        from src.domain.models import Article

        # Fetch article from database
        article = self.db.get(Article, article_id)

        if not article:
            return self.not_found_response("Article", article_id, Article)

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
