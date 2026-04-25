"""Hybrid search combining FTS5 keyword search and semantic embeddings.

This module provides advanced retrieval for articles using:
1. FTS5 (Full-Text Search) for fast keyword matching with BM25 ranking
2. Semantic embeddings via LiteLLM (OpenAI, Cohere, etc.)
3. Hybrid ranking combining both approaches
4. Temporal filtering for forecasting scenarios

Architecture:
    Query → [FTS5 Search] → Keyword Results (scored)
         ↘  [LiteLLM Embedding] → Semantic Results (scored)
              ↓
         [Hybrid Ranker] → Final ranked results
              ↓
         [Temporal Filter] → Temporally valid results
"""

import sqlite3
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from contextlib import contextmanager

from src.domain.models import Article
from src.utils.logging import logger
from ..config.settings import get_config


class HybridSearch:
    """Hybrid search engine combining FTS5 and semantic embeddings."""

    def __init__(
        self,
        db_path: str = "worldreasoner.db",
        embedding_model: Optional[str] = None,
        embedding_config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize hybrid search engine.

        Args:
            db_path: Path to SQLite database
            embedding_model: LiteLLM embedding model name (if None, loads from config.yaml)
                Examples:
                - "text-embedding-3-small" (OpenAI, 1536 dim, cheap)
                - "text-embedding-3-large" (OpenAI, 3072 dim, best quality)
                - "embed-english-v3.0" (Cohere)
                - "litellm_proxy/text-embedding-3-small" (via proxy)
            embedding_config: Optional config dict for LiteLLM client
        """
        self.db_path = Path(db_path)

        # Load embedding model from config if not provided
        if embedding_model is None:
            config = get_config()
            embedding_model = config.llm.embedding_model
            logger.info(f"Using embedding model from config: {embedding_model}")

        self.embedding_model = embedding_model

        # Initialize LiteLLM client lazily for embeddings
        self._llm_client = None
        self._embedding_config = embedding_config if embedding_config is not None else {"embedding_model": embedding_model}

        # Ensure FTS5 table exists
        self._ensure_fts_table()

    @property
    def llm_client(self):
        if self._llm_client is None:
            from .llm import LiteLLMClient
            self._llm_client = LiteLLMClient(self._embedding_config)
        return self._llm_client

    @contextmanager
    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_fts_table(self):
        """Create FTS5 virtual table for articles if not exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create FTS5 virtual table
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    article_id UNINDEXED,
                    title,
                    content,
                    tokenize = 'porter unicode61'
                )
            """)

            # Create embeddings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS article_embeddings (
                    article_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create index on model_name for efficient lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_model
                ON article_embeddings(model_name)
            """)

            conn.commit()

    async def index_article(self, article: Article):
        """Index an article for both FTS5 and embeddings.

        Args:
            article: Article to index
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Index in FTS5
            # FTS5 doesn't support primary keys, so DELETE first to avoid duplicates
            cursor.execute(
                "DELETE FROM articles_fts WHERE article_id = ?", (article.id,)
            )
            cursor.execute(
                """
                INSERT INTO articles_fts (article_id, title, content)
                VALUES (?, ?, ?)
            """,
                (article.id, article.title, article.content),
            )

            # Generate embedding using LiteLLM
            text_to_embed = f"{article.title}\n\n{article.content}"
            embeddings = await self.llm_client.aembedding(
                inputs=[text_to_embed], model=self.embedding_model
            )
            embedding = np.array(embeddings[0], dtype=np.float32)

            # Store as binary blob
            cursor.execute(
                """
                INSERT OR REPLACE INTO article_embeddings (article_id, embedding, model_name)
                VALUES (?, ?, ?)
            """,
                (article.id, embedding.tobytes(), self.embedding_model),
            )

            conn.commit()

    async def index_articles_batch(
        self, articles: List[Article], batch_size: int = 10, fts_only: bool = False
    ):
        """Index multiple articles efficiently using async batching.

        Args:
            articles: List of articles to index
            batch_size: Number of articles to process at once for embeddings
            fts_only: If True, only build the FTS index (skip embedding generation)
        """
        logger.info(f"Checking {len(articles)} articles for indexing...")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            article_ids = [a.id for a in articles]
            placeholders = ",".join(["?"] * len(article_ids))

            if fts_only:
                # Check which articles are already in the FTS table
                cursor.execute(
                    f"SELECT article_id FROM articles_fts WHERE article_id IN ({placeholders})",
                    article_ids,
                )
            else:
                # Check which articles already have embeddings for this model
                cursor.execute(
                    f"""
                    SELECT article_id FROM article_embeddings
                    WHERE model_name = ? AND article_id IN ({placeholders})
                    """,
                    [self.embedding_model] + article_ids,
                )

            already_indexed = {row["article_id"] for row in cursor.fetchall()}

        # Filter to only articles that need indexing
        articles_to_index = [a for a in articles if a.id not in already_indexed]

        if already_indexed:
            logger.info(
                f"Skipping {len(already_indexed)} articles that are already indexed"
            )

        if not articles_to_index:
            logger.info("All articles are already indexed. Nothing to do!")
            return

        logger.info(f"Indexing {len(articles_to_index)} new articles...")

        # Prepare FTS5 data for new articles
        fts_data = [(a.id, a.title, a.content) for a in articles_to_index]

        # Insert FTS5 data upfront (lightweight operation)
        # FTS5 doesn't support primary keys, so DELETE first to avoid duplicates
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Delete existing entries for these article IDs
            article_ids_to_delete = [(a.id,) for a in articles_to_index]
            cursor.executemany(
                "DELETE FROM articles_fts WHERE article_id = ?", article_ids_to_delete
            )
            # Now insert fresh data
            cursor.executemany(
                """
                INSERT INTO articles_fts (article_id, title, content)
                VALUES (?, ?, ?)
            """,
                fts_data,
            )
            conn.commit()

        if fts_only:
            logger.info(f"Successfully indexed {len(articles_to_index)} articles (FTS only)")
            return

        # Generate embeddings in batches and persist immediately
        total_batches = (len(articles_to_index) - 1) // batch_size + 1

        for batch_idx in range(0, len(articles_to_index), batch_size):
            batch_articles = articles_to_index[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            logger.info(
                f"Processing batch {batch_num}/{total_batches} ({len(batch_articles)} articles)..."
            )

            # Generate embeddings for this batch
            batch_texts = [f"{a.title}\n\n{a.content}" for a in batch_articles]

            try:
                batch_embeddings = await self.llm_client.aembedding(
                    inputs=batch_texts, model=self.embedding_model
                )
            except Exception as e:
                logger.error(
                    f"Failed to generate embeddings for batch {batch_num}: {e}"
                )
                raise

            # Convert to numpy and prepare for storage
            embedding_data = [
                (a.id, np.array(emb, dtype=np.float32).tobytes(), self.embedding_model)
                for a, emb in zip(batch_articles, batch_embeddings)
            ]

            # Persist this batch immediately
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO article_embeddings (article_id, embedding, model_name)
                    VALUES (?, ?, ?)
                """,
                    embedding_data,
                )
                conn.commit()

            logger.info(
                f"Batch {batch_num}/{total_batches} saved successfully ({len(batch_articles)} embeddings)"
            )

        logger.info(f"Successfully indexed {len(articles_to_index)} new articles")

    def _fts_search(
        self, query: str, max_results: int = 100, cutoff_date: Optional[datetime] = None
    ) -> List[Tuple[str, float]]:
        """Perform FTS5 keyword search with BM25 ranking.

        Uses OR logic for multi-word queries to be less strict.
        Example: "presidential election polling" → "presidential OR election OR polling"

        Args:
            query: Search query
            max_results: Maximum results to return
            cutoff_date: Optional temporal cutoff

        Returns:
            List of (article_id, bm25_score) tuples
        """
        # Convert query to OR logic for less strict matching
        # Split on whitespace and join with OR
        query_terms = query.strip().split()

        # Escape and quote each term to handle special FTS5 characters
        # FTS5 special chars: . " * ( ) etc.
        def quote_term(term: str) -> str:
            """Quote a search term for FTS5, escaping internal quotes."""
            # Escape any double quotes in the term
            escaped = term.replace('"', '""')
            # Wrap in quotes to treat as literal string
            return f'"{escaped}"'

        if len(query_terms) > 1:
            # Multi-word query: use OR with quoted terms
            fts_query = " OR ".join(quote_term(term) for term in query_terms)
        else:
            # Single word: quote it
            fts_query = quote_term(query_terms[0]) if query_terms else '""'

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if cutoff_date:
                # With temporal filter - use JOIN
                sql = """
                    SELECT
                        articles_fts.article_id,
                        bm25(articles_fts) as score
                    FROM articles_fts
                    JOIN articles ON articles_fts.article_id = articles.id
                    WHERE articles_fts MATCH ?
                    AND articles.published_date < ?
                    ORDER BY score
                    LIMIT ?
                """
                params = [fts_query, cutoff_date.isoformat(), max_results]
            else:
                # Without temporal filter - simpler query
                sql = """
                    SELECT
                        article_id,
                        bm25(articles_fts) as score
                    FROM articles_fts
                    WHERE articles_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                """
                params = [fts_query, max_results]

            cursor.execute(sql, params)
            results = [(row["article_id"], row["score"]) for row in cursor.fetchall()]

        return results

    async def _semantic_search(
        self, query: str, max_results: int = 100, cutoff_date: Optional[datetime] = None
    ) -> List[Tuple[str, float]]:
        """Perform semantic search using embeddings.

        Args:
            query: Search query
            max_results: Maximum results to return
            cutoff_date: Optional temporal cutoff

        Returns:
            List of (article_id, similarity_score) tuples
        """
        # Generate query embedding using LiteLLM
        embeddings = await self.llm_client.aembedding(
            inputs=[query], model=self.embedding_model
        )
        query_embedding = np.array(embeddings[0], dtype=np.float32)

        # Get all article embeddings with temporal filter
        with self._get_connection() as conn:
            cursor = conn.cursor()

            sql = """
                SELECT e.article_id, e.embedding
                FROM article_embeddings e
                JOIN articles a ON e.article_id = a.id
                WHERE e.model_name = ?
            """
            params = [self.embedding_model]

            if cutoff_date:
                sql += " AND a.published_date < ?"
                params.append(cutoff_date.isoformat())

            cursor.execute(sql, params)
            rows = cursor.fetchall()

        if not rows:
            return []

        # Compute cosine similarities
        article_ids = []
        similarities = []

        for row in rows:
            article_id = row["article_id"]
            embedding_bytes = row["embedding"]
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32)

            # Cosine similarity (guard against zero-norm vectors)
            query_norm = np.linalg.norm(query_embedding)
            embedding_norm = np.linalg.norm(embedding)
            if query_norm == 0 or embedding_norm == 0:
                similarity = 0.0
            else:
                similarity = np.dot(query_embedding, embedding) / (
                    query_norm * embedding_norm
                )

            article_ids.append(article_id)
            similarities.append(float(similarity))

        # Sort by similarity and take top results
        sorted_indices = np.argsort(similarities)[::-1][:max_results]
        results = [(article_ids[i], similarities[i]) for i in sorted_indices]

        return results

    async def hybrid_search(
        self,
        query: str,
        max_results: int = 10,
        cutoff_date: Optional[datetime] = None,
        alpha: float = 0.5,
        fts_multiplier: int = 3,
    ) -> List[Tuple[str, float]]:
        """Perform hybrid search combining FTS5 and semantic search.

        Args:
            query: Search query
            max_results: Maximum final results
            cutoff_date: Optional temporal cutoff
            alpha: Weight for semantic search (1-alpha for FTS). 0.5 = equal weight
            fts_multiplier: Retrieve fts_multiplier * max_results from each method

        Returns:
            List of (article_id, combined_score) tuples, sorted by score
        """
        # Retrieve more results from each method for better fusion
        candidate_size = max_results * fts_multiplier

        logger.debug(
            f"Hybrid search: query='{query}', max_results={max_results}, alpha={alpha}"
        )

        # Get results from both methods
        fts_results = self._fts_search(query, candidate_size, cutoff_date)
        semantic_results = await self._semantic_search(
            query, candidate_size, cutoff_date
        )

        logger.debug(
            f"FTS results: {len(fts_results)}, Semantic results: {len(semantic_results)}"
        )

        # Normalize scores to [0, 1] range
        def normalize_scores(
            results: List[Tuple[str, float]], invert: bool = False
        ) -> Dict[str, float]:
            if not results:
                return {}

            scores = [score for _, score in results]
            min_score = min(scores)
            max_score = max(scores)

            # Avoid division by zero
            if max_score == min_score:
                return {aid: 1.0 for aid, _ in results}

            normalized = {
                aid: (score - min_score) / (max_score - min_score)
                for aid, score in results
            }

            # Invert for scores where lower raw value = better match
            # (e.g., BM25 returns negative scores, more negative = better)
            if invert:
                normalized = {aid: 1.0 - score for aid, score in normalized.items()}

            return normalized

        # BM25 scores are negative (more negative = better match), so invert
        fts_normalized = normalize_scores(fts_results, invert=True)
        semantic_normalized = normalize_scores(semantic_results)

        # Combine scores using weighted sum
        all_article_ids = set(fts_normalized.keys()) | set(semantic_normalized.keys())

        combined_scores = {}
        for article_id in all_article_ids:
            fts_score = fts_normalized.get(article_id, 0.0)
            semantic_score = semantic_normalized.get(article_id, 0.0)

            # Weighted combination
            combined_score = (1 - alpha) * fts_score + alpha * semantic_score
            combined_scores[article_id] = combined_score

        # Sort by combined score and take top results
        sorted_results = sorted(
            combined_scores.items(), key=lambda x: x[1], reverse=True
        )[:max_results]

        logger.debug(f"Combined results: {len(sorted_results)}")

        return sorted_results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        cutoff_date: Optional[datetime] = None,
        method: str = "hybrid",
        **kwargs,
    ) -> List[str]:
        """Unified search interface.

        Args:
            query: Search query
            max_results: Maximum results to return
            cutoff_date: Optional temporal cutoff
            method: Search method - "hybrid", "fts", or "semantic"
            **kwargs: Additional parameters for specific methods

        Returns:
            List of article IDs, ranked by relevance
        """
        if method == "fts":
            results = self._fts_search(query, max_results, cutoff_date)
        elif method == "semantic":
            results = await self._semantic_search(query, max_results, cutoff_date)
        elif method == "hybrid":
            results = await self.hybrid_search(
                query, max_results, cutoff_date, **kwargs
            )
        else:
            raise ValueError(f"Unknown search method: {method}")

        return [article_id for article_id, _ in results]

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about indexed articles.

        Returns:
            Dictionary with index statistics
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # FTS5 count
            cursor.execute("SELECT COUNT(*) as count FROM articles_fts")
            fts_count = cursor.fetchone()["count"]

            # Embeddings count for CURRENT model
            cursor.execute(
                """
                SELECT COUNT(*) as count 
                FROM article_embeddings 
                WHERE model_name = ?
            """,
                (self.embedding_model,),
            )
            embeddings_count = cursor.fetchone()["count"]

            # Embeddings by model
            cursor.execute("""
                SELECT model_name, COUNT(*) as count
                FROM article_embeddings
                GROUP BY model_name
            """)
            models = {row["model_name"]: row["count"] for row in cursor.fetchall()}

        return {
            "fts_indexed": fts_count,
            "embeddings_indexed": embeddings_count,
            "models": models,
            "current_model": self.embedding_model,
        }

    async def reindex_all(self, articles: List[Article]):
        """Clear and rebuild all indexes.

        Args:
            articles: All articles to index
        """
        logger.info("Clearing existing indexes...")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles_fts")
            cursor.execute("DELETE FROM article_embeddings")
            conn.commit()

        logger.info("Rebuilding indexes...")
        await self.index_articles_batch(articles)

    def cleanup_orphaned_embeddings(self) -> int:
        """Remove embeddings for articles that no longer exist in the database.

        Returns:
            Number of orphaned embeddings removed
        """
        from .database import GenericDatabase
        from src.domain.models import Article

        logger.info("Checking for orphaned embeddings...")

        # Get all article IDs from the main articles table
        db = GenericDatabase(str(self.db_path))
        db.create_table(Article)
        valid_article_ids = {a.id for a in db.get_many(Article)}

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get all article IDs from embeddings
            cursor.execute("SELECT DISTINCT article_id FROM article_embeddings")
            embedded_ids = {row["article_id"] for row in cursor.fetchall()}

            # Find orphaned IDs
            orphaned_ids = embedded_ids - valid_article_ids

            if not orphaned_ids:
                logger.info("No orphaned embeddings found")
                return 0

            # Delete orphaned embeddings
            placeholders = ",".join(["?"] * len(orphaned_ids))
            cursor.execute(
                f"DELETE FROM article_embeddings WHERE article_id IN ({placeholders})",
                list(orphaned_ids),
            )

            # Also clean up FTS
            cursor.execute(
                f"DELETE FROM articles_fts WHERE article_id IN ({placeholders})",
                list(orphaned_ids),
            )

            conn.commit()

        logger.info(f"Removed {len(orphaned_ids)} orphaned embeddings")
        return len(orphaned_ids)
