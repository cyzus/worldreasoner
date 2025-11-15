"""Test script for hybrid search functionality.

This script tests the hybrid search module with sample queries.

Usage:
    python scripts/test_hybrid_search.py
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.domain.models import Article
from src.utils.logging import logger


async def test_search(
    db_path: str = "worldreasoner.db",
    test_queries: list = None
):
    """Test hybrid search with various queries.

    Args:
        db_path: Path to database
        test_queries: List of test queries
    """
    if test_queries is None:
        test_queries = [
            "presidential election polling",
            "economic recession indicators",
            "artificial intelligence safety",
            "climate change policy",
            "Ukraine conflict developments"
        ]

    logger.info("=" * 60)
    logger.info("Hybrid Search Test")
    logger.info("=" * 60)

    # Initialize
    db = GenericDatabase(db_path)
    search = HybridSearch(db_path)

    # Get index stats
    stats = search.get_index_stats()
    logger.info(f"Index Status:")
    logger.info(f"  FTS5 indexed: {stats['fts_indexed']}")
    logger.info(f"  Embeddings indexed: {stats['embeddings_indexed']}")
    logger.info(f"  Models: {stats['models']}")

    if stats['fts_indexed'] == 0:
        logger.error("No articles indexed! Run: python scripts/build_search_index.py")
        return

    # Test each query with different methods
    for query in test_queries:
        logger.info("=" * 60)
        logger.info(f"Query: '{query}'")
        logger.info("-" * 60)

        # Test hybrid search
        logger.info("Hybrid Search (FTS5 + Embeddings):")
        hybrid_results = await search.search(
            query=query,
            max_results=5,
            method="hybrid"
        )
        display_results(db, hybrid_results)

        # Test FTS only
        logger.info("\nKeyword Search (FTS5 only):")
        fts_results = await search.search(
            query=query,
            max_results=5,
            method="fts"
        )
        display_results(db, fts_results)

        # Test semantic only
        logger.info("\nSemantic Search (Embeddings only):")
        semantic_results = await search.search(
            query=query,
            max_results=5,
            method="semantic"
        )
        display_results(db, semantic_results)

    logger.info("=" * 60)
    logger.info("Test Complete!")
    logger.info("=" * 60)


def display_results(db: GenericDatabase, article_ids: list):
    """Display search results.

    Args:
        db: Database instance
        article_ids: List of article IDs
    """
    if not article_ids:
        logger.info("  No results found")
        return

    for i, article_id in enumerate(article_ids, 1):
        article = db.get(Article, article_id)
        if article:
            logger.info(f"  {i}. [{article.domain}] {article.title[:80]}...")
            logger.info(f"     Published: {article.published_date.date()}")
        else:
            logger.info(f"  {i}. Article {article_id} not found")


async def test_temporal_filtering():
    """Test temporal filtering with hybrid search."""
    logger.info("=" * 60)
    logger.info("Testing Temporal Filtering")
    logger.info("=" * 60)

    db_path = "worldreasoner.db"
    search = HybridSearch(db_path)
    db = GenericDatabase(db_path)

    query = "election polling"

    # Get all articles
    all_articles = db.get_many(Article)
    if not all_articles:
        logger.warning("No articles in database")
        return

    # Find a reasonable cutoff date (middle of dataset)
    # Ensure all dates are timezone-aware for comparison
    from datetime import timezone as tz
    dates = []
    for a in all_articles:
        if a.published_date:
            # Make timezone-aware if naive
            if a.published_date.tzinfo is None:
                date = a.published_date.replace(tzinfo=tz.utc)
            else:
                date = a.published_date
            dates.append(date)

    dates = sorted(dates)
    if dates:
        cutoff_date = dates[len(dates) // 2]

        logger.info(f"Query: '{query}'")
        logger.info(f"Cutoff date: {cutoff_date.date()}")

        # Search without cutoff
        logger.info("\nWithout temporal filter:")
        all_results = await search.search(query=query, max_results=10, method="hybrid")
        logger.info(f"  Found {len(all_results)} results")
        display_results(db, all_results[:5])

        # Search with cutoff
        logger.info(f"\nWith temporal filter (before {cutoff_date.date()}):")
        filtered_results = await search.search(
            query=query,
            max_results=10,
            cutoff_date=cutoff_date,
            method="hybrid"
        )
        logger.info(f"  Found {len(filtered_results)} results")
        display_results(db, filtered_results[:5])


async def main():
    """Run all tests."""
    # Run basic search tests
    await test_search()

    # Run temporal filtering test
    await test_temporal_filtering()


if __name__ == "__main__":
    asyncio.run(main())
