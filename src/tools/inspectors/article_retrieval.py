"""Tool for retrieving articles from the database."""

from src.tools.base.database_mixin import DatabaseAwareTool
from src.tools.base.base import ToolResponseMixin
from src.tools.base.output_models import ArticleRetrievalOutput
from src.domain.models import Article
from src.tools.base.schema_helper import pydantic_to_output_schema


class ArticleRetrievalTool(DatabaseAwareTool, ToolResponseMixin):
    """Tool that retrieves full article content by article ID.

    Use this when you need the complete article text for an article
    you've identified (e.g., from event details or article lists).
    """

    name = "article_retrieval"
    description = """Retrieve full article content by article ID.

    Use this tool when you have an article ID and need to read its full content.
    Article IDs can be found in event details (event.article_ids) or other sources.
    """

    inputs = {
        "article_id": {
            "type": "string",
            "description": "The ID of the article to retrieve",
        }
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(ArticleRetrievalOutput)

    def __init__(self, db=None, db_path: str = None):
        """Initialize the article retrieval tool.

        Args:
            db: Optional GenericDatabase instance
            db_path: Optional path to database file (creates new GenericDatabase if provided)

        Note:
            If neither db nor db_path is provided, will use default database path
        """
        super().__init__(db=db, db_path=db_path, ensure_tables=[Article])

    def forward(self, article_id: str) -> ArticleRetrievalOutput:
        """Retrieve article by ID.

        Args:
            article_id: Article ID to retrieve

        Returns:
            ArticleRetrievalOutput Pydantic model with full article content
        """
        from src.domain.models import Article

        # Fetch article from database
        article = self.db.get(Article, article_id)

        if not article:
            import json
            error_json = self.not_found_response("Article", article_id, Article)
            try:
                error_dict = json.loads(error_json)
                error_msg = error_dict.get("error", "Not found")
                avail = ", ".join(error_dict.get("available_items", []))
                content_msg = f"Error: {error_msg}. Available items: {avail}"
            except Exception:
                content_msg = f"Error: {error_json}"
            return ArticleRetrievalOutput(
                id="error",
                title="Error",
                url="",
                content=content_msg,
                word_count=0
            )

        # Return Pydantic output model directly (smolagents passes through as-is)
        return ArticleRetrievalOutput(
            id=article.id,
            title=article.title,
            url=article.url,
            content=article.content,  # Full content!
            source=article.source,
            published_date=article.published_date.isoformat()
            if article.published_date
            else None,
            word_count=article.word_count,
        )
