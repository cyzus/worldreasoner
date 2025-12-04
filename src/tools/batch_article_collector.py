"""Batch article collection tool to store multiple articles in one call."""

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from smolagents import Tool
from src.domain.models import Article, Domain
from src.utils.enums import parse_domain, enum_to_list
from src.utils.id_generator import generate_article_id
from src.utils.date_utils import parse_iso_datetime
from src.utils.logging import logger
from src.tools.web_fetch import WebFetchTool
from src.tools.base import CollectorAwareTool


class BatchArticleCollectorTool(CollectorAwareTool[Article]):
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

    def __init__(self, db=None, db_path: str = None, collector=None, default_domain: Optional[str] = None):
        super().__init__(collector)
        self.web_visitor = WebFetchTool()
        self.default_domain = default_domain
        # Precompute domain list for descriptions
        self._domain_list = ", ".join(enum_to_list(Domain))

        # Optional database for deduplication/persistence via Database wrapper
        if db:
            self.db = db
        elif db_path:
            from src.core.database import Database
            self.db = Database(db_path)
        else:
            self.db = None

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

            # Fetch content per URL
            try:
                content = self.web_visitor.forward(url)
                if not content or len(content.strip()) < 100:
                    errors.append({"index": idx, "url": url, "error": "Failed to fetch or content too short"})
                    continue
            except Exception as e:
                errors.append({"index": idx, "url": url, "error": f"Fetch error: {e}"})
                continue

            pub_date = parse_iso_datetime(published_date)
            domain_enum = parse_domain(domain)

            # Generate ID (DB-backed systems may de-duplicate at save time)
            article_id = generate_article_id(domain_enum, pub_date, idx)

            article = Article(
                id=article_id,
                title=title,
                url=url,
                source=source,
                domain=domain_enum,
                published_date=pub_date or datetime.now(timezone.utc),
                author=author,
                content=content,
                word_count=len(content.split()),
                reading_time_minutes=max(1, len(content.split()) // 200),
                tags=[],
                event_ids=[],
                metadata={}
            )

            # Persist via unified collector interface (and optional DB)
            self.store_result(article, context=f"Article {article.id}")
            if self.db:
                try:
                    self.db.save_article(article)
                except Exception as e:
                    logger.debug(f"DB save failed for {article.id}: {e}")

            stored.append({"id": article.id, "title": article.title, "url": article.url})

        return json.dumps({
            "stored": len(stored),
            "errors": errors,
            "articles": stored
        })
