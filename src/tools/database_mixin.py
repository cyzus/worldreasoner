"""Database-aware tool mixin for tools that need database access."""

from typing import Optional, Type, List
from smolagents import Tool
from src.core.database import GenericDatabase


class DatabaseAwareTool(Tool):
    """Base class for tools that need database access.

    Provides standardized database initialization with:
    - Direct db instance injection (preferred for testing)
    - Database path with lazy initialization
    - Default fallback to "worldreasoner.db"
    - Optional table creation for required models
    - Helper methods for common database operations

    Example:
        >>> from src.domain.models import Article
        >>>
        >>> class MyTool(DatabaseAwareTool):
        ...     name = "my_tool"
        ...     description = "My tool description"
        ...     inputs = {}
        ...     output_type = "string"
        ...
        ...     def __init__(self, db=None, db_path=None):
        ...         super().__init__(
        ...             db=db,
        ...             db_path=db_path,
        ...             ensure_tables=[Article]
        ...         )
        ...
        ...     def forward(self, article_id: str) -> str:
        ...         article = self.db.get(Article, article_id)
        ...         if not article:
        ...             return self.not_found_response("Article", article_id, Article)
        ...         return self.json_response({"article": article})
    """

    # Default tool attributes (subclasses should override)
    name = "database_aware_tool"
    description = "Base tool with database access"
    inputs = {}
    output_type = "string"
    skip_forward_signature_validation = True  # Base class doesn't define forward()

    def __init__(
        self,
        db: Optional[GenericDatabase] = None,
        db_path: Optional[str] = None,
        ensure_tables: Optional[List[Type]] = None,
    ):
        """Initialize database connection.

        Args:
            db: Direct database instance (preferred for testing)
            db_path: Path to database file
            ensure_tables: List of model classes to create tables for

        Examples:
            >>> # With direct db instance (testing)
            >>> tool = MyTool(db=mock_db)
            >>>
            >>> # With db_path
            >>> tool = MyTool(db_path="test.db")
            >>>
            >>> # With default (worldreasoner.db)
            >>> tool = MyTool()
        """
        super().__init__()

        self.db: Optional[GenericDatabase] = None

        # Initialize database connection
        if db:
            self.db = db
        elif db_path:
            self.db = GenericDatabase(db_path)
        else:
            # Use default database path
            self.db = GenericDatabase("worldreasoner.db")

        # Ensure schema is initialized for required models
        if ensure_tables and self.db:
            for model_class in ensure_tables:
                self.db.create_table(model_class)

    def not_found_response(
        self, item_type: str, item_id: str, model_class: Type, limit: int = 10
    ) -> str:
        """Generate standardized 'not found' error with available IDs.

        Provides helpful error message listing available items when
        a requested item doesn't exist.

        Args:
            item_type: Human-readable type name (e.g., "Article", "Event")
            item_id: The ID that wasn't found
            model_class: Model class to query for available IDs
            limit: Max number of available IDs to return (default: 10)

        Returns:
            JSON error response with available IDs

        Examples:
            >>> article = self.db.get(Article, article_id)
            >>> if not article:
            ...     return self.not_found_response("Article", article_id, Article)
        """
        import json

        # Get available items
        all_items = self.db.get_many(model_class)
        available_ids = [i.id for i in all_items[:limit]]

        error_response = {
            "error": f"{item_type} '{item_id}' not found in database",
            "available_items": available_ids,
        }

        return json.dumps(error_response, indent=2)
