"""Article collection tool using web search for scraping."""

import hashlib
from typing import Optional
from urllib.parse import urlparse

from src.config import get_config
from src.domain.models import Article, Domain
from src.utils.logging import logger
from src.utils.enums import enum_to_list, parse_domain
from src.domain.models.id_generator import generate_article_id
from src.utils.date_utils import parse_iso_datetime
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.collectors.web_fetch import WebFetchTool
from src.tools.base.base import CollectorAwareTool
from src.tools.base.output_models import ArticleOutput


class ArticleCollectorTool(CollectorAwareTool[Article]):
    """Fetches and stores article data from URLs into Article objects.

    This tool helps the agent:
    1. Internally fetch full article content from a URL (using WebFetchTool)
    2. Convert content into structured Article format
    3. Generate unique article IDs
    4. Handle deduplication via content hashing
    5. Calculate metadata (word count, reading time, etc.)

    IMPORTANT: This tool ONLY needs the URL and metadata.
    The agent should use web_search to find article URLs, then pass ONLY the URL
    to this tool. This tool will internally fetch the full content, avoiding
    expensive token usage from passing large article text through the LLM.
    """

    name = "article_collector"
    description = f"""Fetches and stores article data from a URL to database.
    
    Use this tool AFTER you've found article URLs using web_search.
    IMPORTANT: make sure the published_date is correct.
    This tool will internally fetch the full article content to save tokens.
    """

    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "url": {
            "type": "string",
            "description": "Source URL to fetch the article from",
        },
        "title": {
            "type": "string",
            "description": "Article headline/title from search results",
        },
        "source": {"type": "string", "description": "Publication name"},
        "domain": {
            "type": "string",
            "description": f"Domain category - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain),
            "nullable": True,
        },
        "published_date": {
            "type": "string",
            "description": "Publication date (ISO format with time zone)",
        },
        "author": {"type": "string", "description": "Author name", "nullable": True},
        "timeout": {
            "type": "integer",
            "description": "Web fetch timeout in seconds (default: 15)",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(ArticleOutput)

    def __init__(
        self,
        db=None,
        db_path: str = None,
        collector=None,
        question_id: Optional[str] = None,
    ):
        """Initialize the article collector.

        Args:
            db: Optional Database instance for cross-run deduplication
            db_path: Optional path to database file (creates new Database with schema if provided)
            collector: Optional ResultCollector[Article] for storing results.
                      If provided, articles are added to the collector instead of internal storage.
            question_id: Question ID for provenance tracking (sets collected_for_question_id)
        """
        super().__init__(collector)
        self.config = None
        self.seen_hashes = set()  # For in-memory deduplication within this run
        self.web_visitor = WebFetchTool()  # Internal tool for fetching content
        self.question_id = question_id  # Provenance context

        logger.info(
            f"ArticleCollectorTool initialized with collector: {collector is not None}, question_id: {question_id}"
        )

        # Database for cross-run deduplication (optional)
        self.db = None
        if db:
            self.db = db
        elif db_path:
            # Lazy import to avoid circular dependency
            from src.core.database import GenericDatabase

            self.db = GenericDatabase(db_path)
            # Ensure schema is initialized
            self.db.create_table(Article)

    def setup(self):
        """Load configuration (called on first use)."""
        if self.config is None:
            self.config = get_config()

    def forward(
        self,
        url: str,
        title: str,
        source: str,
        published_date: str,
        domain: str = "general",
        author: Optional[str] = None,
        timeout: int = 15,
    ) -> ArticleOutput:
        """Fetch article content from URL and store as structured Article.

        Args:
            url: Source URL to fetch article from
            title: Article headline from search results
            source: Publication name
            domain: Article domain category (string, will be converted to enum)
            published_date: Publication date (ISO format with time zone)
            author: Optional author name
            timeout: Web fetch timeout in seconds

        Returns:
            ArticleOutput: Pydantic model with article metadata and status
        """
        # STAGE 1: Fast URL-based deduplication (before fetching content)
        # This is the most efficient check - prevents unnecessary web scraping
        if self.db:
            # Normalize URL for better matching (remove trailing slash, fragments)
            normalized_url = self._normalize_url(url)

            # Use GenericDatabase's get_many with filter
            existing_articles = self.db.get_many(
                Article, filters={"url": normalized_url}
            )
            if existing_articles:
                existing = existing_articles[0]

                # Update collected_for_question_id if this article is being claimed
                # for a question but wasn't previously tagged (e.g. pre-existing news articles)
                if self.question_id and existing.collected_for_question_id != self.question_id:
                    existing.collected_for_question_id = self.question_id
                    self.db.save(Article, existing)
                    logger.debug(
                        f"Updated collected_for_question_id on existing article {existing.id}"
                    )

                # Add to collector even if duplicate (for current pipeline run)
                # Note: Check 'is not None' because ResultCollector.__bool__ returns False when empty
                if self.collector is not None:
                    self.collector.add(existing)
                    logger.debug(
                        f"Added existing article {existing.id} to collector (duplicate URL, total: {self.collector.count()})"
                    )
                else:
                    self._fallback_items.append(existing)
                    logger.debug(
                        f"Added existing article {existing.id} to internal list (duplicate URL, total: {len(self._fallback_items)})"
                    )

                return ArticleOutput(
                    id=existing.id,
                    title=existing.title,
                    url=existing.url,
                    source=existing.source,
                    status="already_exists",
                    word_count=existing.word_count,
                    published_date=existing.published_date.isoformat()
                    if existing.published_date
                    else None,
                )

        # STAGE 2: Fetch content (only if URL not found)
        # This avoids passing large content through the LLM
        try:
            web_output = self.web_visitor.forward(url, timeout=timeout)

            # WebFetchTool returns WebFetchOutput object now
            if not web_output.success or not web_output.content:
                # Return error as ArticleOutput
                error_msg = web_output.error or "Empty content fetched"
                return ArticleOutput(
                    id="error",
                    title=title,
                    url=url,
                    status=f"error: {error_msg}",
                )

            content = web_output.content
            if len(content.strip()) < 100:
                return ArticleOutput(
                    id="error",
                    title=title,
                    url=url,
                    status=f"error: Content too short ({len(content)} chars)",
                )
        except Exception as e:
            return ArticleOutput(
                id="error",
                title=title,
                url=url,
                status=f"error: {str(e)}",
            )

        # Parse published date or use current time
        pub_date = parse_iso_datetime(published_date)

        # Validate article date against question time window
        # Store validation result to include in return message
        time_window_validation = None
        if self.question_id and self.db:
            from src.domain.models import Question
            from src.utils.date_utils import validate_date_against_question_window

            question = self.db.get(Question, self.question_id)
            if question:
                time_window_validation = validate_date_against_question_window(
                    date=pub_date,
                    question_start_time=question.estimated_start_time,
                    question_resolution_date=question.resolution_date,
                    entity_type="Article",
                )

        # STAGE 3: Content hash deduplication (catches syndicated/republished articles)
        # Check if we've already seen this content (in-memory for current run)
        content_hash = self._compute_content_hash(content)
        if content_hash in self.seen_hashes:
            logger.debug(
                f"Skipping duplicate content hash: {content_hash} for URL: {url}"
            )
            return ArticleOutput(
                id="duplicate",
                title=title,
                url=url,
                status="duplicate: Same content already exists",
            )

        # Also check database for content hash (cross-run syndication detection)
        if self.db:
            # Query by content_hash if your Article model has this field
            # For now, we'll skip this to avoid performance issues
            # In production, you might want to add a content_hash field and index
            pass

        self.seen_hashes.add(content_hash)

        # Validate and convert domain
        domain_enum = parse_domain(domain, default=Domain.GENERAL)
        if domain_enum is None:
            domain_enum = Domain.GENERAL

        # Generate unique ID
        article_id = generate_article_id(domain_enum, pub_date, len(self.seen_hashes))

        # Extract domain from URL if not provided
        parsed_url = urlparse(url)
        source_domain = parsed_url.netloc

        # Store normalized URL for consistency
        normalized_url = self._normalize_url(url)

        # Build metadata with provenance info
        metadata = {}
        if self.question_id:
            metadata["evidence_type"] = "hindsight"
            metadata["related_question_ids"] = [self.question_id]

        # Create Article object
        article = Article(
            id=article_id,
            title=title,
            content=content,
            url=normalized_url,  # Use normalized URL for consistency
            source=source,
            author=author or "Unknown",
            published_date=pub_date,
            domain=domain_enum,
            tags=[domain_enum.value, source_domain],
            event_ids=[],  # Initialize with empty list (will be populated later in pipeline)
            is_synthetic=False,
            language="en",
            collected_for_question_id=self.question_id,  # Provenance tracking
            metadata=metadata,
        )

        # Calculate metadata
        article.word_count = len(article.content.split())
        article.reading_time_minutes = max(1, article.word_count // 200)

        # Store article using unified collector interface
        self.store_result(article, context=f"Article {article.id}")

        # Persist to database if available
        if self.db:
            self.db.save(Article, article)
            logger.debug(f"Article {article.id} persisted to database")

        # Return ArticleOutput Pydantic model with summary metadata
        # Note: We don't include full content to save tokens
        status_msg = "stored"
        if time_window_validation:
            status_msg = "stored_with_warnings"

        return ArticleOutput(
            id=article.id,
            title=article.title,
            url=article.url,
            source=article.source,
            status=status_msg,
            word_count=article.word_count,
            published_date=article.published_date.isoformat(),
        )

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent duplicate detection.

        Removes:
        - Trailing slashes
        - URL fragments (#section)
        - Common tracking parameters
        - Converts http to https

        Args:
            url: Raw URL

        Returns:
            Normalized URL
        """
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

        parsed = urlparse(url)

        # Convert http to https
        scheme = "https" if parsed.scheme == "http" else parsed.scheme

        # Remove trailing slash from path
        path = parsed.path.rstrip("/")

        # Remove common tracking parameters
        if parsed.query:
            params = parse_qs(parsed.query)
            # Remove common tracking params
            tracking_params = {
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_content",
                "utm_term",
                "fbclid",
                "gclid",
                "ref",
                "source",
            }
            cleaned_params = {
                k: v for k, v in params.items() if k not in tracking_params
            }
            query = urlencode(cleaned_params, doseq=True) if cleaned_params else ""
        else:
            query = ""

        # Reconstruct URL without fragment
        normalized = urlunparse((scheme, parsed.netloc, path, parsed.params, query, ""))

        return normalized

    def _compute_content_hash(self, content: str) -> str:
        """Compute SHA-256 hash of normalized content for deduplication.

        Args:
            content: Article content to hash

        Returns:
            Hexadecimal hash string
        """
        normalized = " ".join(content.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def reset_deduplication(self):
        """Reset the deduplication cache."""
        self.seen_hashes.clear()
