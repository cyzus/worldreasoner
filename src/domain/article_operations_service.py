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
        search_method: str = "fts"
    ) -> List[Article]:
        """Search for articles with temporal filtering.

        Finds the most relevant articles published BEFORE the simulated date.

        Args:
            query: Search query
            simulated_date: Cutoff date (only articles before this are returned)
            domain: Optional domain filter
            max_results: Maximum number of results (default: 10)
            search_method: Search method - "fts", "semantic", or "hybrid" (default: "fts")

        Returns:
            List of articles before simulated_date, ranked by relevance
        """
        logger.info(f"Hybrid search: query='{query}', simulated_date={simulated_date.isoformat()}")

        # Perform search with temporal filtering
        # Returns article IDs ranked by hybrid score (FTS5 + embeddings)
        article_ids = await self.hybrid_search.search(
            query=query,
            max_results=max_results,
            cutoff_date=simulated_date,
            method=search_method,
            alpha=0.5  # Equal weight to keyword and semantic search
        )

        logger.info(f"Found {len(article_ids)} results")

        # Get temporal database for fetching full articles
        temporal_db = GenericDatabase(self.db.db_path, cutoff_date=simulated_date)

        # Fetch full article objects
        matches = []
        for article_id in article_ids:
            article = temporal_db.get(Article, article_id)
            if article:
                # Apply domain filter if specified
                if domain and len(article_ids) > max_results * 10:
                    domain_filter = parse_domain(domain)
                    if domain_filter is not None and article.domain != domain_filter:
                        continue
                matches.append(article)

        # Limit results after domain filtering
        matches = matches[:max_results]

        return matches

    def fetch_article(
        self,
        article_id: str,
        simulated_date: datetime
    ) -> Optional[Article]:
        """Fetch full article content with temporal validation.

        Only returns the article if it was published before the simulated date.
        This simulates accessing information available at the simulated "today" date.

        Args:
            article_id: Article ID to fetch
            simulated_date: Cutoff date for temporal validation

        Returns:
            Article object if accessible, None if not found or published after simulated_date

        Raises:
            ValueError: If article was published after simulated_date
        """
        logger.info(f"Fetching article {article_id} with simulated_date {simulated_date.isoformat()}")

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
        self,
        article: Article,
        simulated_date: datetime
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
