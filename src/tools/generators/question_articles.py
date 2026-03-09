from typing import Optional
from datetime import datetime, timezone

from src.core.alias_registry import AliasRegistry
from src.tools.base.database_mixin import DatabaseAwareTool
from src.tools.base.output_models import QuestionArticlesOutput
from src.domain.models import Article
from src.utils.logging import logger
from src.tools.base.schema_helper import pydantic_to_output_schema


class QuestionArticlesTool(DatabaseAwareTool):
    """Retrieves all articles collected for the current question.

    This tool requires no input arguments - it uses the question_id
    provided at initialization to find relevant articles.

    Use this tool at the START of causal analysis to get article IDs
    for linking to events and causal hypotheses.
    """

    name = "get_question_articles"
    description = """Retrieves all articles associated with the current question.

    No input required. Returns a JSON object containing:
    - articles: List of articles with id, title, source, published_date, content_preview, word_count.
    - total_articles: Count of articles found.
    """

    inputs = {
        "limit": {
            "type": "integer",
            "description": "Number of articles to return (default: 20)",
            "default": 20,
            "nullable": True,
        },
        "offset": {
            "type": "integer",
            "description": "Number of articles to skip (default: 0)",
            "default": 0,
            "nullable": True,
        },
        "sort": {
            "type": "string",
            "description": "Sort order: 'date_desc' (newest first) or 'date_asc' (oldest first). Default: 'date_desc'",
            "default": "date_desc",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(QuestionArticlesOutput)

    def __init__(
        self,
        db_path: str = None,
        question_id: Optional[str] = None,
        alias_registry: Optional[AliasRegistry] = None,
    ):
        """Initialize the tool.

        Args:
            db_path: Path to the database
            question_id: Question ID to get articles for (injected at init)
            alias_registry: Optional alias registry for generating article aliases
        """
        super().__init__(db_path=db_path, ensure_tables=[Article])
        self.question_id = question_id
        self.alias_registry = alias_registry

    def forward(
        self, limit: int = 20, offset: int = 0, sort: str = "date_desc"
    ) -> QuestionArticlesOutput:
        """Get articles collected for this question with pagination.

        Args:
            limit: Max articles to return
            offset: Number of articles to skip
            sort: Sort order ('date_desc' or 'date_asc')

        Returns:
            QuestionArticlesOutput: Pydantic model with paginated article list
        """
        if not self.question_id:
            return QuestionArticlesOutput(
                articles=[], total=0, limit=limit, offset=offset
            )

        if not self.db:
            return QuestionArticlesOutput(
                articles=[], total=0, limit=limit, offset=offset
            )

        # Find articles collected for this question
        all_articles = self.db.get_many(Article)

        # Filter by provenance field or metadata
        question_articles = []
        for article in all_articles:
            # Check explicit provenance field first
            if article.collected_for_question_id == self.question_id:
                question_articles.append(article)
            # Fallback: check metadata for pre-migration data
            elif (
                article.collected_for_question_id is None
                and article.metadata.get("related_question_ids")
                and self.question_id in article.metadata["related_question_ids"]
            ):
                question_articles.append(article)

        logger.debug(
            f"Found {len(question_articles)} total articles for question {self.question_id}"
        )

        # Sort articles
        reverse_sort = sort != "date_asc"  # Default to desc (newest first)
        question_articles.sort(
            key=lambda a: a.published_date or datetime.min.replace(tzinfo=timezone.utc),
            reverse=reverse_sort,
        )

        # Apply pagination
        total_count = len(question_articles)
        start_idx = max(0, offset)
        end_idx = min(start_idx + limit, total_count)
        paginated_articles = question_articles[start_idx:end_idx]

        # Format response with essential info
        articles_data = []
        for article in paginated_articles:
            # Generate article alias if registry is provided
            alias = None
            if self.alias_registry:
                alias = self.alias_registry.generate_article_alias(
                    article.title, article.id
                )

            articles_data.append(
                {
                    "id": article.id,
                    "alias": alias,
                    "title": article.title,
                    "source": article.source,
                    "published_date": article.published_date.isoformat()
                    if article.published_date
                    else None,
                    "content_preview": article.content[:300] + "..."
                    if len(article.content) > 300
                    else article.content,
                    "word_count": article.word_count,
                }
            )

        return QuestionArticlesOutput(
            articles=articles_data,
            total=total_count,
            limit=limit,
            offset=offset,
        )
