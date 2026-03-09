"""Base class for domain services with shared utilities."""

from typing import Optional

from src.core.database import GenericDatabase


class ServiceBase:
    """Base class for domain services.

    Provides common utilities for service implementations.
    """

    def __init__(self, db: GenericDatabase):
        """Initialize the service.

        Args:
            db: Default database instance
        """
        self.db = db

    def get_db(self, db_path: Optional[str] = None) -> GenericDatabase:
        """Get database instance for the given path.

        Uses custom db_path if provided, otherwise returns the default database.
        This pattern is common across services that support per-request database switching.

        Args:
            db_path: Optional custom database path

        Returns:
            GenericDatabase instance
        """
        if db_path:
            return GenericDatabase(db_path)
        return self.db
