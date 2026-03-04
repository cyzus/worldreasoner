"""Shared CLI option factories for DRY Typer declarations.

All command files import from here instead of declaring inline options.
"""

from typing import Optional

import typer

from src.core.database import GenericDatabase
from src.cli.core.question_manager import QuestionManager


def db_option(default: str = "worldreasoner.db") -> str:
    """Reusable --db option."""
    return typer.Option(default, "--db", help="Database path")


def source_option() -> Optional[str]:
    """Reusable --source/-s option."""
    return typer.Option(None, "--source", "-s", help="Filter by question source")


def domain_option() -> Optional[str]:
    """Reusable --domain/-d option for filtering."""
    return typer.Option(None, "--domain", "-d", help="Filter by domain")


def limit_option(default: int = 50) -> int:
    """Reusable --limit/-n option."""
    return typer.Option(default, "--limit", "-n", help="Maximum results to show")


def sample_option() -> Optional[int]:
    """Reusable --sample option."""
    return typer.Option(None, "--sample", help="Random sample size")


def seed_option() -> Optional[int]:
    """Reusable --seed option."""
    return typer.Option(None, "--seed", help="Random seed for reproducible sampling")


def yes_option() -> bool:
    """Reusable --yes/-y option."""
    return typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")


def json_option() -> bool:
    """Reusable --json option."""
    return typer.Option(False, "--json", help="Output as JSON")


def get_db_and_manager(db_path: str):
    """Helper to create database and manager instances."""
    db = GenericDatabase(db_path)
    manager = QuestionManager(db)
    return db, manager
