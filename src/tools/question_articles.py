"""Tool to retrieve articles collected for the current question context."""

import json
from typing import Optional

from src.tools.database_mixin import DatabaseAwareTool
from src.domain.models import Article
from src.utils.logging import logger


class QuestionArticlesTool(DatabaseAwareTool):
    """Retrieves all articles collected for the current question.

    This tool requires no input arguments - it uses the question_id
    provided at initialization to find relevant articles.

    Use this tool at the START of causal analysis to get article IDs
    for linking to events and causal hypotheses.
    """

    name = "get_question_articles"
    description = """Get all articles collected for this question.

    NO INPUT REQUIRED - automatically uses the current question context.

    Returns a list of articles with their IDs, titles, and content previews.
    Use the returned article IDs when:
    - Creating events with event_identifier (source_article_ids)
    - Creating causal links with causal_reasoner (evidence_article_ids)

    Returns:
        JSON with list of articles: [{id, title, source, published_date, content_preview}, ...]
    """

    inputs = {}
    output_type = "string"

    def __init__(self, db_path: str = None, question_id: Optional[str] = None):
        """Initialize the tool.

        Args:
            db_path: Path to the database
            question_id: Question ID to get articles for (injected at init)
        """
        super().__init__(db_path=db_path, ensure_tables=[Article])
        self.question_id = question_id

    def forward(self) -> str:
        """Get all articles collected for this question.

        Returns:
            JSON string with article list
        """
        if not self.question_id:
            return json.dumps({
                "error": "No question_id context provided",
                "articles": []
            })

        if not self.db:
            return json.dumps({
                "error": "No database connection",
                "articles": []
            })

        # Find articles collected for this question
        all_articles = self.db.get_many(Article)

        # Filter by provenance field or metadata
        question_articles = []
        for article in all_articles:
            # Check explicit provenance field first
            if article.collected_for_question_id == self.question_id:
                question_articles.append(article)
            # Fallback: check metadata for pre-migration data
            elif (article.collected_for_question_id is None and
                  article.metadata.get('related_question_ids') and
                  self.question_id in article.metadata['related_question_ids']):
                question_articles.append(article)

        logger.debug(f"Found {len(question_articles)} articles for question {self.question_id}")

        # Format response with essential info
        articles_data = []
        for article in question_articles:
            articles_data.append({
                "id": article.id,
                "title": article.title,
                "source": article.source,
                "published_date": article.published_date.isoformat() if article.published_date else None,
                "content_preview": article.content[:300] + "..." if len(article.content) > 300 else article.content,
                "word_count": article.word_count,
            })

        return json.dumps({
            "question_id": self.question_id,
            "total_articles": len(articles_data),
            "articles": articles_data,
            "article_ids": [a["id"] for a in articles_data],  # Convenient list for tool calls
        }, indent=2)
