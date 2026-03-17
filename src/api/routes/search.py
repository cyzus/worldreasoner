"""Search index management API endpoints.

Provides REST API for building and managing search indexes.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.domain.models import Article
from src.core.search_indexing import auto_index_articles
from src.config.settings import get_config
from src.utils.logging import logger
from .database import get_current_db_path


router = APIRouter()


class SearchIndexStatus(BaseModel):
    """Search index status information."""

    total_articles: int
    fts_indexed: int
    embeddings_indexed: int
    models: dict[str, int]  # Model name -> count mapping
    needs_indexing: bool
    embedding_model: str


class SearchIndexBuildRequest(BaseModel):
    """Request to build search indexes."""

    rebuild: bool = False
    embedding_model: Optional[str] = None
    batch_size: int = 2
    fts_only: bool = False


class SearchIndexBuildResponse(BaseModel):
    """Response for search index build operation."""

    success: bool
    message: str
    total_articles: int
    newly_indexed: int
    final_indexed: int
    status: str


class CleanupResponse(BaseModel):
    """Response for cleanup operation."""

    success: bool
    message: str
    orphaned_removed: int


@router.get("/status", response_model=SearchIndexStatus)
async def get_search_index_status():
    """Get the current status of search indexes.

    Returns:
        Search index status information including counts and model info
    """
    try:
        db_path = get_current_db_path()

        # Get config for embedding model
        config = get_config()
        embedding_model = config.llm.embedding_model

        # Initialize database and search
        db = GenericDatabase(db_path)
        search = HybridSearch(db_path, embedding_model=embedding_model)

        # Get stats
        db.create_table(Article)
        total_articles = len(db.get_many(Article))
        stats = search.get_index_stats()

        needs_indexing = total_articles > stats["fts_indexed"]

        return SearchIndexStatus(
            total_articles=total_articles,
            fts_indexed=stats["fts_indexed"],
            embeddings_indexed=stats["embeddings_indexed"],
            models=stats["models"],
            needs_indexing=needs_indexing,
            embedding_model=embedding_model,
        )
    except Exception as e:
        logger.error(f"Failed to get search index status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build-index", response_model=SearchIndexBuildResponse)
async def build_search_index(request: SearchIndexBuildRequest):
    """Build or rebuild search indexes.

    Args:
        request: Build request with rebuild flag and optional model override

    Returns:
        Build status and statistics
    """
    try:
        db_path = get_current_db_path()

        # Get embedding model from request or config
        if request.embedding_model:
            embedding_model = request.embedding_model
        else:
            config = get_config()
            embedding_model = config.llm.embedding_model

        logger.info(
            f"Building search index: db={db_path}, model={embedding_model}, rebuild={request.rebuild}"
        )

        # Check if there are articles to index
        db = GenericDatabase(db_path)
        db.create_table(Article)
        total_articles = len(db.get_many(Article))

        if total_articles == 0:
            return SearchIndexBuildResponse(
                success=True,
                message="No articles found in database",
                total_articles=0,
                newly_indexed=0,
                final_indexed=0,
                status="no_articles",
            )

        # Determine skip_existing based on rebuild flag
        skip_existing = not request.rebuild

        # Run the indexing
        result = await auto_index_articles(
            db_path=db_path,
            embedding_model=embedding_model,
            skip_existing=skip_existing,
            fts_only=request.fts_only,
        )

        # Build response based on result
        if result["status"] == "success":
            return SearchIndexBuildResponse(
                success=True,
                message=f"Successfully indexed {result['newly_indexed']} articles",
                total_articles=result["total_articles"],
                newly_indexed=result["newly_indexed"],
                final_indexed=result["final_indexed"],
                status=result["status"],
            )
        elif result["status"] == "up_to_date":
            return SearchIndexBuildResponse(
                success=True,
                message="All articles already indexed",
                total_articles=result["total_articles"],
                newly_indexed=0,
                final_indexed=result["already_indexed"],
                status=result["status"],
            )
        else:
            # Failed
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Search indexing failed: {error_msg}")
            return SearchIndexBuildResponse(
                success=False,
                message=f"Indexing failed: {error_msg}",
                total_articles=result["total_articles"],
                newly_indexed=0,
                final_indexed=result["already_indexed"],
                status=result["status"],
            )

    except Exception as e:
        logger.error(f"Failed to build search index: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_orphaned_embeddings():
    """Clean up orphaned embeddings (embeddings for deleted articles).

    Returns:
        Cleanup status and count of removed embeddings
    """
    try:
        db_path = get_current_db_path()
        config = get_config()
        embedding_model = config.llm.embedding_model

        search = HybridSearch(db_path, embedding_model=embedding_model)
        orphaned_count = search.cleanup_orphaned_embeddings()

        return CleanupResponse(
            success=True,
            message=f"Removed {orphaned_count} orphaned embeddings",
            orphaned_removed=orphaned_count,
        )
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned embeddings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
