"""Database configuration for WorldReasoner.

NOTE: This project uses SQLite, not PostgreSQL.
The configuration is simplified for local file-based storage.
"""

from pathlib import Path
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """SQLite database configuration.

    This project uses SQLite for simplicity and portability.
    Configuration focuses on file path and performance settings.
    """

    # SQLite file settings
    db_path: str = Field(
        default="worldreasoner.db", description="Path to SQLite database file"
    )

    # Performance settings
    batch_size: int = Field(
        default=100, description="Batch insert size for bulk operations"
    )

    # Connection settings
    timeout: float = Field(
        default=5.0, description="Database connection timeout in seconds"
    )

    check_same_thread: bool = Field(
        default=False, description="SQLite threading check (False for multi-threaded)"
    )

    def get_db_path(self) -> Path:
        """Get database file path as Path object.

        Returns:
            Path object for database file
        """
        return Path(self.db_path)

    def get_connection_string(self) -> str:
        """Get SQLite connection string.

        Returns:
            SQLite connection string for SQLAlchemy if needed
        """
        return f"sqlite:///{self.db_path}"
