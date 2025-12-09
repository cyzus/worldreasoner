"""Database management API endpoints.

Provides REST API for managing database file selection.
"""

from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.utils.logging import logger


router = APIRouter()


class DatabaseInfo(BaseModel):
    """Database file information."""
    path: str
    name: str
    size_bytes: int
    exists: bool
    is_current: bool


class DatabaseListResponse(BaseModel):
    """Response for listing database files."""
    databases: List[DatabaseInfo]
    current_database: str


class DatabaseSwitchRequest(BaseModel):
    """Request to switch database file."""
    db_path: str


class DatabaseSwitchResponse(BaseModel):
    """Response for database switch operation."""
    success: bool
    message: str
    db_path: str


# Global state for current database path
class DatabaseState:
    """Singleton to manage current database path."""
    _instance = None
    _current_db_path: str = "worldreasoner.db"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def current_db_path(self) -> str:
        """Get current database path."""
        return self._current_db_path

    @current_db_path.setter
    def current_db_path(self, value: str):
        """Set current database path."""
        self._current_db_path = value
        logger.info(f"Database path updated to: {value}")


# Singleton instance
db_state = DatabaseState()


def get_current_db_path() -> str:
    """Get the current database path.

    This function is used by other route files to get the database path.
    """
    return db_state.current_db_path


@router.get("/current", response_model=DatabaseInfo)
async def get_current_database():
    """Get information about the current database file.

    Returns:
        Current database file information
    """
    try:
        db_path = Path(db_state.current_db_path)

        return DatabaseInfo(
            path=str(db_path),
            name=db_path.name,
            size_bytes=db_path.stat().st_size if db_path.exists() else 0,
            exists=db_path.exists(),
            is_current=True,
        )
    except Exception as e:
        logger.error(f"Failed to get current database info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=DatabaseListResponse)
async def list_databases():
    """List all available database files in the current directory.

    Returns:
        List of database files found
    """
    try:
        current_dir = Path.cwd()
        db_files = list(current_dir.glob("*.db"))

        databases = []
        current_path = db_state.current_db_path

        for db_file in sorted(db_files):
            is_current = str(db_file) == current_path or db_file.name == current_path
            databases.append(
                DatabaseInfo(
                    path=str(db_file),
                    name=db_file.name,
                    size_bytes=db_file.stat().st_size if db_file.exists() else 0,
                    exists=db_file.exists(),
                    is_current=is_current,
                )
            )

        return DatabaseListResponse(
            databases=databases,
            current_database=current_path,
        )
    except Exception as e:
        logger.error(f"Failed to list databases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/switch", response_model=DatabaseSwitchResponse)
async def switch_database(request: DatabaseSwitchRequest):
    """Switch to a different database file.

    Args:
        request: Database switch request with db_path

    Returns:
        Success status and message
    """
    try:
        db_path = Path(request.db_path)

        # Validate the database file exists
        if not db_path.exists():
            return DatabaseSwitchResponse(
                success=False,
                message=f"Database file not found: {db_path}",
                db_path=db_state.current_db_path,
            )

        # Validate it's a .db file
        if db_path.suffix != ".db":
            return DatabaseSwitchResponse(
                success=False,
                message=f"Invalid file type. Expected .db file, got: {db_path.suffix}",
                db_path=db_state.current_db_path,
            )

        # Update the current database path
        db_state.current_db_path = str(db_path)

        logger.info(f"Switched to database: {db_path}")

        return DatabaseSwitchResponse(
            success=True,
            message=f"Successfully switched to database: {db_path.name}",
            db_path=str(db_path),
        )
    except Exception as e:
        logger.error(f"Failed to switch database: {e}")
        raise HTTPException(status_code=500, detail=str(e))
