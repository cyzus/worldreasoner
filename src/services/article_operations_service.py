"""Service for article search and retrieval operations with temporal filtering.

This service handles all article-related operations for the MCP forecasting server,
including search, fetch, and temporal access validation.
"""

from typing import List, Optional
from datetime import datetime

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.core.temporal_gateway import TemporalGateway
from src.domain.models import Article
from src.utils.enums import parse_domain
from src.utils.logging import logger


class ArticleOperationsService:
    """Service for article search and retrieval with temporal filtering.

    Handles:
    - Article search with temporal filtering
    - Article fetch with temporal validation
    - Temporal access validation
    """

    def __init__(self, db: GenericDatabase, hybrid_search: HybridSearch):
        """Initialize the service.

        Args:
            db: Database instance for article retrieval
            hybrid_search: HybridSearch instance for article search
        """
        self.db = db
        self.hybrid_search = hybrid_search

    async def search_articles(
        self,
        query: str,
        simulated_date: datetime,
        domain: Optional[str] = None,
        max_results: int = 10,
        search_method: str = "fts",
        question_id: Optional[str] = None,
    ) -> List[Article]:
        """Search for articles with temporal filtering.

        Finds the most relevant articles published BEFORE the simulated date.

        Args:
            query: Search query
            simulated_date: Cutoff date (only articles before this are returned)
            domain: Optional domain filter
            max_results: Maximum number of results (default: 10)
            search_method: Search method - "fts", "semantic", or "hybrid" (default: "fts")
            question_id: Optional question ID to scope fallback to question's articles

        Returns:
            List of articles before simulated_date, ranked by relevance
        """
        logger.info(
            f"Searching articles: query='{query}', simulated_date={simulated_date.isoformat()}, method={search_method}"
        )

        # Overfetch to account for SQL timezone comparison inaccuracies:
        # Dates stored with non-UTC offsets can pass the SQL string comparison
        # but get filtered by the Python gateway. Fetching extra candidates
        # ensures we still return max_results valid articles after Python filtering.
        fetch_limit = max_results * 5

        article_ids = await self.hybrid_search.search(
            query=query,
            max_results=fetch_limit,
            cutoff_date=simulated_date,
            method=search_method,
            alpha=0.5,  # Equal weight to keyword and semantic search
        )

        logger.info(f"Found {len(article_ids)} candidates from search index")

        # Get temporal database for fetching full articles
        temporal_db = GenericDatabase(self.db.db_path, cutoff_date=simulated_date)

        domain_filter = parse_domain(domain) if domain else None

        # Fetch and Python-filter full article objects, then trim to max_results
        matches = self._collect_matches(article_ids, temporal_db, domain_filter, max_results)

        # Fallback: if search index is empty or returned no results, query DB directly
        # by question ID so the agent can still find articles collected for this question.
        if not matches and question_id:
            logger.info(
                f"Search index returned no results; falling back to direct DB query "
                f"for question_id={question_id}"
            )
            matches = self._fallback_by_question(
                temporal_db, question_id, domain_filter, max_results
            )

        return matches

    def _collect_matches(
        self,
        article_ids: List[str],
        temporal_db: GenericDatabase,
        domain_filter,
        max_results: int,
    ) -> List[Article]:
        """Fetch articles from DB, applying Python temporal + domain filters."""
        matches = []
        for article_id in article_ids:
            if len(matches) >= max_results:
                break
            article = temporal_db.get(Article, article_id)
            if article:
                if domain_filter is not None and article.domain != domain_filter:
                    continue
                matches.append(article)
        return matches

    def _fallback_by_question(
        self,
        temporal_db: GenericDatabase,
        question_id: str,
        domain_filter,
        max_results: int,
    ) -> List[Article]:
        """Return temporally valid articles collected for a specific question."""
        articles = temporal_db.get_many(
            Article, filters={"collected_for_question_id": question_id}
        )
        matches = []
        for article in articles:
            if len(matches) >= max_results:
                break
            if domain_filter is not None and article.domain != domain_filter:
                continue
            matches.append(article)
        logger.info(f"Fallback returned {len(matches)} articles")
        return matches

    def fetch_article(
        self, article_id: str, simulated_date: datetime
    ) -> Optional[Article]:
        """Fetch full article content with temporal validation.

        Only returns the article if it was published before the simulated date.
        This simulates accessing information available at the simulated "today" date.

        Args:
            article_id: Article ID to fetch
            simulated_date: Cutoff date for temporal validation

        Returns:
            Article object if accessible, None if not found in database

        Raises:
            ValueError: If article was published after simulated_date
        """
        logger.info(
            f"Fetching article {article_id} with simulated_date {simulated_date.isoformat()}"
        )

        # Get article from temporal database
        temporal_db = GenericDatabase(self.db.db_path, cutoff_date=simulated_date)
        article = temporal_db.get(Article, article_id)

        if not article:
            return None

        # Validate temporal access
        if not self.validate_temporal_access(article, simulated_date):
            raise ValueError(
                f"Article {article_id} was published after the simulated date. "
                f"Published: {article.published_date.isoformat()}, "
                f"Simulated: {simulated_date.isoformat()}. "
                f"You can only access articles from before the simulated 'today' date."
            )

        return article

    def validate_temporal_access(
        self, article: Article, simulated_date: datetime
    ) -> bool:
        """Validate that an article is accessible at the simulated date.

        An article is accessible if it was published before the simulated date.

        Args:
            article: Article to validate
            simulated_date: Simulated "today" date

        Returns:
            True if article is accessible, False otherwise
        """
        gateway = TemporalGateway(simulated_date)
        return gateway.is_article_accessible(article)
