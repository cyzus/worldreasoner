"""Database utility helpers."""

from typing import Union
from src.core.database import GenericDatabase


def ensure_database(db: Union[str, GenericDatabase]) -> GenericDatabase:
    """Convert string path to GenericDatabase instance if needed.

    Eliminates repeated pattern:
    `db = GenericDatabase(db) if isinstance(db, str) else db`

    Args:
        db: Either a database path string or GenericDatabase instance

    Returns:
        GenericDatabase instance

    Examples:
        >>> db = ensure_database("worldreasoner.db")
        >>> db = ensure_database(existing_db_instance)  # No-op
    """
    if isinstance(db, str):
        return GenericDatabase(db)
    return db
