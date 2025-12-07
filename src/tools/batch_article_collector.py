"""Batch article collection tool to store multiple articles in one call."""

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from src.domain.models import Article, Domain
from src.utils.enums import parse_domain, enum_to_list
from src.utils.logging import logger
from src.tools.article_collector import ArticleCollectorTool


class BatchArticleCollectorTool(ArticleCollectorTool):
    """Fetches and stores multiple articles from URLs into Article objects.

    Use this after web_search yields multiple URLs. Pass a JSON array of
    minimal metadata per URL; this tool fetches full content internally to
    minimize token usage.

    Input schema (each item in array):
    - url (str): Source URL
    - title (str): Headline/title from search results
    - source (str): Publication name
    - domain (str, optional): Domain category; defaults to "general"
    - published_date (str, optional): ISO 8601 WITH timezone (e.g. 2025-12-31T23:59:59Z)
    - author (str, optional): Author name
    """

    name = "batch_article_collector"
    description = """Fetch and store multiple articles by URLs in one call.

    Args:
        articles_json (str): JSON array of objects with fields:
            url, title, source, domain(optional; one of: {domains}), published_date(optional, ISO 8601 WITH timezone), author(optional)

    Returns:
        JSON summary with counts and IDs of stored articles
    """

    inputs = {
        "articles_json": {
            "type": "string",
            "description": "JSON array of article metadata (url,title,source,domain(optional; one of: {domains}),published_date(optional, ISO 8601 WITH timezone),author(optional))"
        }
    }
    output_type = "string"

    def __init__(
        self,
        db=None,
        db_path: str = None,
        collector=None,
        default_domain: Optional[str] = None,
        question_id: Optional[str] = None,
    ):
        """Initialize the batch article collector.

        Args:
            db: Optional database instance
            db_path: Optional database path
            collector: Optional result collector
            default_domain: Default domain for articles
            question_id: Question ID for provenance tracking (sets collected_for_question_id)
        """
        super().__init__(db=db, db_path=db_path, collector=collector, question_id=question_id)
        self.default_domain = default_domain
        # Precompute domain list for descriptions
        self._domain_list = ", ".join(enum_to_list(Domain))

    def forward(self, articles_json: str) -> str:
        """Process multiple articles from a JSON array."""
        # Fill dynamic domain enum into descriptions once (runtime strings for agent clarity)
        # Note: smolagents tools typically read 'inputs' and 'description' at init time.
        # We replace placeholders if present.
        if "{domains}" in self.description:
            self.description = self.description.format(domains=self._domain_list)
        # Update inputs description similarly
        if "articles_json" in self.inputs and "{domains}" in self.inputs["articles_json"]["description"]:
            self.inputs["articles_json"]["description"] = self.inputs["articles_json"]["description"].format(domains=self._domain_list)

        try:
            items: List[Dict[str, Any]] = json.loads(articles_json)
        except Exception as e:
            return json.dumps({"error": f"Invalid JSON: {e}", "status": "failed"})

        if not isinstance(items, list):
            return json.dumps({"error": "articles_json must be a JSON array", "status": "failed"})

        stored = []
        errors = []

        for idx, data in enumerate(items):
            url = data.get("url")
            title = data.get("title")
            source = data.get("source")
            domain = data.get("domain", self.default_domain or "general")
            published_date = data.get("published_date")
            author = data.get("author")

            if not url or not title or not source:
                errors.append({"index": idx, "error": "Missing required fields: url/title/source"})
                continue

            # Use parent class forward method to process single article
            try:
                result_json = super().forward(
                    url=url,
                    title=title,
                    source=source,
                    domain=domain,
                    published_date=published_date,
                    author=author
                )
                result = json.loads(result_json)
                
                if "error" in result:
                    errors.append({"index": idx, "url": url, "error": result["error"]})
                else:
                    stored.append({"id": result["id"], "title": result["title"], "url": result["url"]})
            except Exception as e:
                errors.append({"index": idx, "url": url, "error": f"Processing error: {e}"})

        return json.dumps({
            "stored": len(stored),
            "errors": errors,
            "articles": stored
        })
