"""Database management API endpoints.

Provides REST API for managing database file selection.
"""

import os
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.utils.logging import logger
from src.core.database import GenericDatabase
from src.config import get_config


router = APIRouter()


class MCPServerManager:
    """Manages the lifecycle of the MCP forecasting server.

    This class handles starting, stopping, and monitoring the MCP server process.
    When the database switches, it automatically restarts the server with the new database.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8301):
        """Initialize the MCP server manager.

        Args:
            host: Host to bind the MCP server to
            port: Port to bind the MCP server to
        """
        self.host = host
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self._current_db: Optional[str] = None

    @property
    def is_running(self) -> bool:
        """Check if the MCP server is currently running."""
        return self.process is not None and self.process.poll() is None

    def start_server(self, db_path: str, auto_restart: bool = True):
        """Start the MCP server with the specified database.

        Args:
            db_path: Path to the database file
            auto_restart: If True, stop existing server before starting new one

        Raises:
            RuntimeError: If server fails to start or health check fails
        """
        # Resolve to absolute path for comparison
        db_abs_path = str(Path(db_path).resolve())

        # Check if server is already healthy with the requested database
        if self.check_health(expected_db=db_abs_path):
            logger.info(f"MCP server already healthy with database: {db_abs_path}")
            logger.info("Skipping restart")
            return

        # Stop existing server if running
        if self.is_running and auto_restart:
            old_pid = self.process.pid
            logger.info(
                f"Stopping existing MCP server (PID: {old_pid}, current_db: {self._current_db})"
            )
            self.stop_server()
            logger.info(f"Old MCP server (PID: {old_pid}) stopped")

            # Give the OS time to release the port
            import time

            time.sleep(1)
            logger.info("Waited 1s for port release")

        # EXTRA SAFETY: Kill any rogue MCP server processes on our port
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    # Check if it's a Python process running mcp_forecasting_server
                    if "python" in proc.info["name"].lower() and any(
                        "mcp_forecasting_server" in str(arg) for arg in cmdline
                    ):
                        logger.warning(
                            f"Found orphaned MCP server process (PID: {proc.info['pid']}), terminating..."
                        )
                        proc.terminate()
                        proc.wait(timeout=3)
                        logger.info(f"Terminated orphaned process {proc.info['pid']}")
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.TimeoutExpired,
                ):
                    pass
        except ImportError:
            logger.debug("psutil not available, skipping orphaned process cleanup")

        # Resolve to absolute path
        db_abs_path = str(Path(db_path).resolve())

        logger.info(f"Starting NEW MCP server with database: {db_abs_path}")

        # Get the Python executable that's running this backend
        python_exe = sys.executable

        # Start the MCP server process
        try:
            self.process = subprocess.Popen(
                [
                    python_exe,
                    "-m",
                    "src.api.mcp_forecasting_server",
                    "--host",
                    self.host,
                    "--port",
                    str(self.port),
                    "--db",
                    db_abs_path,
                    "--log-level",
                    "info",
                ],
                env={**os.environ, "WORLDREASONER_DB": db_abs_path},
                # Don't capture output - let it go to console for debugging
                # stdout=subprocess.PIPE,
                # stderr=subprocess.PIPE,
                # Ensure server runs in background
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32"
                else 0,
            )

            self._current_db = db_abs_path
            logger.info(f"MCP server process started (PID: {self.process.pid})")

            # Wait for server to be ready (give it more time to initialize)
            self._wait_for_health(max_attempts=30, delay=0.5)

            logger.info(
                f"MCP server is healthy and ready at http://{self.host}:{self.port}"
            )

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")

            # Try to get error output from the process
            if self.process:
                try:
                    # Check if process is still running
                    if self.process.poll() is not None:
                        # Process has terminated, get output
                        stdout, stderr = self.process.communicate(timeout=1)
                        if stderr:
                            logger.error(f"MCP server stderr:\n{stderr}")
                        if stdout:
                            logger.info(f"MCP server stdout:\n{stdout}")
                except Exception as comm_error:
                    logger.warning(f"Could not get process output: {comm_error}")

                self.process.kill()
                self.process = None

            raise RuntimeError(f"Failed to start MCP server: {e}")

    def stop_server(self, timeout: int = 5):
        """Stop the MCP server gracefully.

        Args:
            timeout: Maximum time to wait for graceful shutdown (seconds)
        """
        if not self.is_running:
            logger.debug("No MCP server is running")
            return

        try:
            logger.info(f"Terminating MCP server (PID: {self.process.pid})")
            self.process.terminate()

            # Wait for graceful shutdown
            try:
                self.process.wait(timeout=timeout)
                logger.info("MCP server terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"MCP server did not terminate within {timeout}s, forcing kill"
                )
                self.process.kill()
                self.process.wait()
                logger.info("MCP server killed")

        except Exception as e:
            logger.error(f"Error stopping MCP server: {e}")
        finally:
            self.process = None
            self._current_db = None

    def _wait_for_health(self, max_attempts: int = 20, delay: float = 0.5):
        """Wait for the MCP server to become healthy.

        Args:
            max_attempts: Maximum number of health check attempts
            delay: Delay between attempts (seconds)

        Raises:
            RuntimeError: If health check fails after max attempts
        """
        # Give the server a moment to start binding to the port
        time.sleep(1)

        for attempt in range(1, max_attempts + 1):
            # Check if process is still alive
            if self.process.poll() is not None:
                # Process has terminated
                logger.error(
                    f"MCP server process terminated unexpectedly (exit code: {self.process.returncode})"
                )
                try:
                    stdout, stderr = self.process.communicate(timeout=1)
                    if stderr:
                        logger.error(f"MCP server stderr:\n{stderr}")
                    if stdout:
                        logger.info(f"MCP server stdout:\n{stdout}")
                except Exception as e:
                    logger.warning(f"Could not get process output: {e}")
                raise RuntimeError(
                    f"MCP server process terminated with exit code {self.process.returncode}"
                )

            # Use the check_health method to verify server is healthy
            if self.check_health(expected_db=self._current_db):
                logger.info(
                    f"Health check successful - database verified: {self._current_db}"
                )
                return

            logger.debug(f"Health check attempt {attempt}/{max_attempts} failed")
            time.sleep(delay)

        # Health check failed - try to get process output for debugging
        logger.error(f"Health check failed after {max_attempts} attempts")
        if self.process and self.process.poll() is None:
            logger.warning(
                "MCP server process is still running but not responding to health checks"
            )
            logger.warning(
                f"Check if port {self.port} is accessible or if there's a firewall blocking it"
            )

        raise RuntimeError(
            f"MCP server failed to become healthy after {max_attempts} attempts. "
            f"Check server logs for details."
        )

    def check_health(self, expected_db: Optional[str] = None) -> bool:
        """Check if the MCP server is healthy and responding.

        Args:
            expected_db: Optional database path to verify server is using

        Returns:
            True if server is healthy (and using expected_db if provided), False otherwise
        """
        if not self.is_running:
            return False

        health_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        health_url = f"http://{health_host}:{self.port}/health"

        try:
            import requests
            response = requests.get(health_url, timeout=2)
            if response.status_code == 200:
                data = response.json()

                # If expected_db is provided, verify the server is using it
                if expected_db:
                    reported_db = data.get("database", "")
                    expected_abs = str(Path(expected_db).resolve())
                    reported_abs = (
                        str(Path(reported_db).resolve()) if reported_db else ""
                    )

                    if reported_abs != expected_abs:
                        logger.debug(
                            f"Health check: DB mismatch. Expected: {expected_abs}, Got: {reported_abs}"
                        )
                        return False

                return True
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    def get_status(self) -> dict:
        """Get the current status of the MCP server.

        Returns:
            Dictionary with server status information
        """
        if not self.is_running:
            return {"running": False, "database": None, "pid": None, "url": None}

        return {
            "running": True,
            "database": self._current_db,
            "pid": self.process.pid,
            "url": f"http://{self.host}:{self.port}",
        }

    def get_logs(self, lines: int = 50) -> dict:
        """Get recent stdout/stderr from the MCP server process.

        Args:
            lines: Number of recent lines to return (not implemented, returns all)

        Returns:
            Dictionary with stdout and stderr content
        """
        if not self.process:
            return {"stdout": "", "stderr": "", "error": "No process running"}

        # Note: Since we're using PIPE, we can't easily get logs after process starts
        # This is a limitation - we'd need to use file-based logging instead
        return {
            "stdout": "Logs not available (process using PIPE)",
            "stderr": "Logs not available (process using PIPE)",
            "note": "Check MCP server logs in console or enable file logging",
        }


# Global MCP server manager instance — reads from YAML config
_cfg = get_config()
mcp_manager = MCPServerManager(host=_cfg.server.mcp_host, port=_cfg.server.mcp_port)


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


class DatabaseCreateRequest(BaseModel):
    """Request to create a new database file."""

    name: str
    switch: bool = True


class DatabaseSwitchResponse(BaseModel):
    """Response for database switch operation."""

    success: bool
    message: str
    db_path: str


# Global state for current database path
class DatabaseState:
    """Singleton to manage current database path."""

    _instance = None
    _current_db_path: str = str(Path("worldreasoner.db").resolve())

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
        """Set current database path to absolute path."""
        # Always resolve to absolute path to avoid working directory issues
        resolved_path = str(Path(value).resolve())
        self._current_db_path = resolved_path
        logger.info(f"Database path updated to: {resolved_path}")


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
                # Normalize both paths to absolute for comparison
                resolved_db_file = str(db_file.resolve())
                is_current = resolved_db_file == current_path
                databases.append(
                DatabaseInfo(
                        path=resolved_db_file,
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


@router.get("/mcp-status")
async def get_mcp_status():
    """Get the status of the MCP forecasting server.

    Returns:
        MCP server status information
    """
    try:
        status = mcp_manager.get_status()
        return status
    except Exception as e:
        logger.error(f"Failed to get MCP server status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create", response_model=DatabaseSwitchResponse)
async def create_database(request: DatabaseCreateRequest):
    """Create a new (empty, fully-initialized) database file.

    The file is created in the current working directory, the same place
    ``/list`` scans for ``.db`` files. All tables are initialized so the new
    database is immediately usable. Optionally switches to it.

    Args:
        request: Database create request with name and switch flag

    Returns:
        Success status, message, and the path of the (possibly switched) database
    """
    try:
        # Sanitize the requested name: keep only the file name, no directories
        raw_name = (request.name or "").strip()
        if not raw_name:
            return DatabaseSwitchResponse(
                success=False,
                message="Database name is required",
                db_path=db_state.current_db_path,
            )

        # Reject path separators / traversal to keep files in the cwd
        if any(sep in raw_name for sep in ("/", "\\", "..")):
            return DatabaseSwitchResponse(
                success=False,
                message="Database name must not contain path separators",
                db_path=db_state.current_db_path,
            )

        # Ensure a .db extension
        if not raw_name.endswith(".db"):
            raw_name = f"{raw_name}.db"

        # Validate the remaining name is a sensible file name
        stem = raw_name[:-3]
        if not stem or not all(
            c.isalnum() or c in ("_", "-", " ") for c in stem
        ):
            return DatabaseSwitchResponse(
                success=False,
                message=(
                    "Invalid database name. Use letters, numbers, spaces, "
                    "hyphens, and underscores only."
                ),
                db_path=db_state.current_db_path,
            )

        db_path = (Path.cwd() / raw_name).resolve()

        if db_path.exists():
            return DatabaseSwitchResponse(
                success=False,
                message=f"Database already exists: {db_path.name}",
                db_path=db_state.current_db_path,
            )

        # Create the file and initialize the full schema
        db = GenericDatabase(str(db_path))
        tables_count = db.initialize_all_tables()
        logger.info(f"Created database {db_path} with {tables_count} tables")

        # Optionally switch to the newly created database
        if request.switch:
            db_state.current_db_path = str(db_path)
            logger.info(f"Switched to newly created database: {db_path}")
            message = f"Created and switched to database: {db_path.name}"
            current_path = str(db_path)
        else:
            message = f"Created database: {db_path.name}"
            current_path = db_state.current_db_path

        return DatabaseSwitchResponse(
            success=True,
            message=message,
            db_path=current_path,
        )
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/switch", response_model=DatabaseSwitchResponse)
async def switch_database(request: DatabaseSwitchRequest):
    """Switch to a different database file.

    This endpoint updates the backend's current database. The MCP server
    supports per-request database switching via X-Database-Path headers,
    so no server restart is needed (instant switching).

    Args:
        request: Database switch request with db_path

    Returns:
        Success status and message
    """
    try:
        db_path = Path(request.db_path).resolve()

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

        # Initialize all tables in the switched database
        # This ensures the schema is up-to-date and prevents errors when querying tables
        try:
            db = GenericDatabase(str(db_path))
            tables_count = db.initialize_all_tables()
            logger.info(f"Initialized {tables_count} tables in switched database")
        except Exception as init_err:
            logger.error(f"Warning: Failed to initialize tables in new database: {init_err}")
            # Don't fail the switch if table initialization fails - user can still try

        # NO LONGER RESTARTING MCP SERVER!
        # The MCP server now supports per-request database switching via X-Database-Path header
        # This makes database switching instant and much more stable
        logger.info(
            "Database switch complete (MCP server supports per-request DB via headers)"
        )
        message = f"Successfully switched to database: {db_path.name} (instant - no restart needed)"

        return DatabaseSwitchResponse(
            success=True,
            message=message,
            db_path=str(db_path),
        )
    except Exception as e:
        logger.error(f"Failed to switch database: {e}")
        raise HTTPException(status_code=500, detail=str(e))
