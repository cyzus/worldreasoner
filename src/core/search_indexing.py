"""Utility functions for search indexing after pipeline runs."""

from typing import Optional

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.domain.models import Article
from src.utils.logging import logger


async def auto_index_articles(
    db_path: str = "worldreasoner.db",
    embedding_model: Optional[str] = None,
    skip_existing: bool = True,
    fts_only: bool = False,
) -> dict:
    """Automatically index articles for hybrid search after pipeline runs.

    Args:
        db_path: Path to database
        embedding_model: Optional embedding model override
        skip_existing: If True, only index articles not already in FTS/embeddings

    Returns:
        Dictionary with indexing statistics
    """
    logger.info("Auto-indexing articles for search...")

    # Initialize database and search
    db = GenericDatabase(db_path)
    search = HybridSearch(db_path, embedding_model=embedding_model)

    # Get all articles from database
    db.create_table(Article)
    all_articles = db.get_many(Article)

    if not all_articles:
        logger.warning("No articles found in database. Nothing to index.")
        return {
            "total_articles": 0,
            "already_indexed": 0,
            "newly_indexed": 0,
            "status": "no_articles",
        }

    # Get current index stats
    stats = search.get_index_stats()
    already_indexed = stats["fts_indexed"] if fts_only else stats["embeddings_indexed"]

    logger.info(f"Total articles in database: {len(all_articles)}")
    logger.info(f"Already indexed: {already_indexed}")

    if skip_existing:
        # Get list of already indexed article IDs
        with search._get_connection() as conn:
            cursor = conn.cursor()
            if fts_only:
                cursor.execute("SELECT article_id FROM articles_fts")
            else:
                cursor.execute(
                    "SELECT article_id FROM article_embeddings WHERE model_name = ?",
                    (search.embedding_model,),
                )
            indexed_ids = {row["article_id"] for row in cursor.fetchall()}

        # Filter to only new articles
        articles_to_index = [a for a in all_articles if a.id not in indexed_ids]

        if not articles_to_index:
            logger.info("✓ All articles already indexed. Nothing to do.")
            return {
                "total_articles": len(all_articles),
                "already_indexed": already_indexed,
                "newly_indexed": 0,
                "status": "up_to_date",
            }

        logger.info(f"New articles to index: {len(articles_to_index)}")
    else:
        # Index all articles (rebuild)
        articles_to_index = all_articles
        logger.info("Rebuilding index for all articles...")

    # Index the articles
    try:
        await search.index_articles_batch(articles_to_index, fts_only=fts_only)

        # Get final stats
        final_stats = search.get_index_stats()

        logger.info("Search indexing complete!")
        logger.info(
            f"FTS5 indexed: {final_stats['fts_indexed']}, Embeddings indexed: {final_stats['embeddings_indexed']}"
        )
        logger.info(f"Embedding model: {search.embedding_model}")

        return {
            "total_articles": len(all_articles),
            "already_indexed": already_indexed,
            "newly_indexed": len(articles_to_index),
            "final_indexed": final_stats["embeddings_indexed"],
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Failed to index articles: {e}")
        return {
            "total_articles": len(all_articles),
            "already_indexed": already_indexed,
            "newly_indexed": 0,
            "status": "failed",
            "error": str(e),
        }
