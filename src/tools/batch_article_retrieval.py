"""Batch article retrieval tool for retrieving multiple articles at once."""

import json
from typing import List, Optional
from src.utils.logging import logger
from src.tools.article_retrieval import ArticleRetrievalTool


class BatchArticleRetrievalTool(ArticleRetrievalTool):
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
        super().__init__(db=db, db_path=db_path)

    def forward(self, article_ids: str) -> str:
        """Retrieve multiple articles by IDs.

        Args:
            article_ids: Comma-separated article IDs

        Returns:
            JSON string with array of article content
        """
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
                # Use parent class forward method to retrieve single article
                result_json = super().forward(article_id)
                result = json.loads(result_json)
                
                if "error" in result:
                    not_found.append(article_id)
                else:
                    articles_data.append(result)

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
            result["suggestion"] = "Use article_retrieval tool for individual articles to get error details"

        return json.dumps(result, indent=2)
