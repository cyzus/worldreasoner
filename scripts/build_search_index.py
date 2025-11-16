"""Build or rebuild search indexes for hybrid search.

This script indexes all articles in the database for both FTS5 and semantic search.
Run this after importing new articles or when changing the embedding model.

Usage:
    # Index all articles (using default embedding model)
    python scripts/build_search_index.py

    # Rebuild from scratch
    python scripts/build_search_index.py --rebuild

    # Use a different embedding model
    python scripts/build_search_index.py --model text-embedding-3-large

    # Use via litellm proxy
    python scripts/build_search_index.py --model litellm_proxy/text-embedding-3-small

    # Custom database path
    python scripts/build_search_index.py --db /path/to/worldreasoner.db
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.domain.models import Article
from src.utils.logging import logger
from src.config.settings import get_config


async def build_index(
    db_path: str = "worldreasoner.db",
    embedding_model: Optional[str] = None,
    rebuild: bool = False,
    batch_size: int = 100
):
    """Build search index for all articles.

    Args:
        db_path: Path to database
        embedding_model: LiteLLM embedding model to use (if None, loads from config.yaml)
        rebuild: Whether to clear existing indexes first
        batch_size: Batch size for embedding generation
    """
    # Load from config if not provided
    if embedding_model is None:
        config = get_config()
        embedding_model = config.llm.embedding_model
        logger.info(f"Using embedding model from config: {embedding_model}")

    logger.info(f"Building search index: db={db_path}, model={embedding_model}")

    # Initialize database and search
    db = GenericDatabase(db_path)
    search = HybridSearch(db_path, embedding_model=embedding_model)

    # Get all articles
    logger.info("Loading articles from database...")
    db.create_table(Article)
    articles = db.get_many(Article)

    if not articles:
        logger.warning("No articles found in database. Nothing to index.")
        return

    logger.info(f"Found {len(articles)} articles")

    # Build indexes
    if rebuild:
        logger.info("Rebuilding indexes from scratch...")
        await search.reindex_all(articles)
    else:
        # Check current index status
        stats = search.get_index_stats()
        logger.info(f"Current index stats: {stats}")

        # Index articles
        await search.index_articles_batch(articles, batch_size=batch_size)

    # Final stats
    final_stats = search.get_index_stats()
    logger.info("=" * 60)
    logger.info("Search Index Build Complete!")
    logger.info("=" * 60)
    logger.info(f"Total articles in DB: {len(articles)}")
    logger.info(f"FTS5 indexed: {final_stats['fts_indexed']}")
    logger.info(f"Embeddings indexed: {final_stats['embeddings_indexed']}")
    logger.info(f"Embedding models: {final_stats['models']}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Build search indexes for hybrid article search using LiteLLM embeddings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index all articles with model from config.yaml
  python scripts/build_search_index.py

  # Rebuild from scratch
  python scripts/build_search_index.py --rebuild

  # Override embedding model (instead of using config.yaml)
  python scripts/build_search_index.py --model text-embedding-3-large

  # Use via litellm proxy
  python scripts/build_search_index.py --model litellm_proxy/text-embedding-3-small

  # Custom database and batch size
  python scripts/build_search_index.py --db data/worldreasoner.db --batch-size 50

Default Configuration:
  The embedding model is read from config.yaml (llm.embedding_model)
  Use --model to override this setting.

Available Embedding Models (via LiteLLM):

OpenAI:
  - text-embedding-3-small (1536 dim, $0.02/1M tokens)
  - text-embedding-3-large (3072 dim, best quality, $0.13/1M tokens)
  - text-embedding-ada-002 (1536 dim, legacy)

Cohere:
  - embed-english-v3.0 (1024 dim)
  - embed-multilingual-v3.0 (1024 dim, 100+ languages)

Other:
  - voyage-2 (Voyage AI)
  - mistral-embed (Mistral AI)
  - gemini/gemini-embedding-001 (Gemini)

See https://docs.litellm.ai/docs/embedding/supported_embedding for full list.
        """
    )
    parser.add_argument(
        "--db",
        default="worldreasoner.db",
        help="Path to database file (default: worldreasoner.db)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LiteLLM embedding model (default: from config.yaml)"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear and rebuild indexes from scratch"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Batch size for embedding generation (default: 100)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(build_index(
            db_path=args.db,
            embedding_model=args.model,
            rebuild=args.rebuild,
            batch_size=args.batch_size
        ))
    except Exception as e:
        logger.error(f"Failed to build index: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
