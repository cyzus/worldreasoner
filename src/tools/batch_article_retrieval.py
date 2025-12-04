"""Batch article retrieval tool for retrieving multiple articles at once."""

import json
from typing import List, Optional
from smolagents import Tool
from src.utils.logging import logger


class BatchArticleRetrievalTool(Tool):
    """Tool that retrieves full content for multiple articles in a single call.

    Use this when you need to read multiple articles at once.
    More efficient than calling article_retrieval multiple times.
    """

    name = "batch_article_retrieval"
    description = """Retrieve full content for multiple articles by their IDs.

    Use this tool when you have multiple article IDs and need to read their content.
    Pass a comma-separated list of article IDs.

    Args:
        article_ids (str): Comma-separated article IDs (e.g., "art_tech_001,art_finance_002")

    Returns:
        JSON array with full article content for each ID

    Example:
        batch_article_retrieval(article_ids="art_tech_20251101_001,art_tech_20251101_002")
    """

    inputs = {
        "article_ids": {
            "type": "string",
            "description": "Comma-separated article IDs to retrieve"
        }
    }
    output_type = "string"

    def __init__(self, db=None, db_path: str = None):
        """Initialize the batch article retrieval tool.

        Args:
            db: Optional Database instance
            db_path: Optional path to database file
        """
        super().__init__()

        # Database setup
        if db:
            self.db = db
        elif db_path:
            from src.core.database import Database
            self.db = Database(db_path)
        else:
            from src.core.database import Database
            self.db = Database("worldreasoner.db")

    def forward(self, article_ids: str) -> str:
        """Retrieve multiple articles by IDs.

        Args:
            article_ids: Comma-separated article IDs

        Returns:
            JSON string with array of article content
        """
        from src.domain.models import Article

        # Parse article IDs
        ids = [aid.strip() for aid in article_ids.split(',')]

        if not ids:
            return json.dumps({
                "error": "No article IDs provided",
                "articles": []
            })

        logger.info(f"Retrieving {len(ids)} articles: {ids}")

        articles_data = []
        not_found = []

        for article_id in ids:
            try:
                # Fetch article from database
                try:
                    article = self.db.get_article(article_id)
                except AttributeError:
                    article = self.db.get(Article, article_id)

                if not article:
                    not_found.append(article_id)
                    continue

                # Add full article content
                articles_data.append({
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
                })

            except Exception as e:
                logger.warning(f"Error retrieving article {article_id}: {e}")
                not_found.append(article_id)

        result = {
            "articles": articles_data,
            "found": len(articles_data),
            "not_found": not_found,
            "total_requested": len(ids)
        }

        if not_found:
            # Get available articles for helpful error message
            try:
                all_articles = self.db.get_articles()
                available_ids = [a.id for a in all_articles[:10]]
            except:
                all_articles = self.db.get_many(Article)
                available_ids = [a.id for a in all_articles[:10]]

            result["suggestion"] = f"Available articles: {', '.join(available_ids)}"

        return json.dumps(result, indent=2)
