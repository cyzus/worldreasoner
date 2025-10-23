"""Shared test fixtures and configuration for all tests.

This module provides reusable fixtures for database management,
ensuring proper cleanup and isolation between tests.
"""
import pytest
from pathlib import Path
from src.core.database import Database, GenericDatabase


@pytest.fixture
def test_db_path(tmp_path):
    """Provide a temporary database path that auto-cleans after test.

    The database file is created in pytest's temporary directory
    and automatically cleaned up when the test finishes.

    Usage:
        def test_something(test_db_path):
            stage = ArticleCollectionStage(config, db_path=test_db_path)
            # Database will be cleaned up automatically

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        str: Path to temporary database file
    """
    return str(tmp_path / "test.db")


@pytest.fixture
def test_db(tmp_path):
    """Provide a temporary Database instance that auto-cleans.

    Creates a fully initialized Database instance in a temporary directory.
    All tables (articles, events, questions) are created automatically.

    Usage:
        def test_something(test_db):
            test_db.save_article(article)
            test_db.save_event(event)
            # Database will be cleaned up automatically

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Database: Initialized database instance
    """
    db_path = tmp_path / "test.db"
    return Database(str(db_path))


@pytest.fixture
def generic_test_db(tmp_path):
    """Provide a temporary GenericDatabase instance.

    For tests that need lower-level database access without
    the high-level Database wrapper.

    Usage:
        def test_something(generic_test_db):
            from src.domain.models import Article
            generic_test_db.create_table(Article)
            generic_test_db.save(Article, article_instance)

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        GenericDatabase: Generic database instance
    """
    db_path = tmp_path / "test.db"
    return GenericDatabase(str(db_path))


@pytest.fixture(scope="session", autouse=True)
def cleanup_workspace_test_dbs():
    """Clean up any test databases left in workspace after session.

    This fixture runs automatically at the end of the test session
    to remove any database files that were created directly in the
    workspace (not using tmp_path).

    This is a safety net for legacy tests that haven't been migrated
    to use tmp_path fixtures yet.
    """
    yield

    # After all tests complete, clean up known test databases
    workspace_dbs = [
        "test_all_rss_sources.db",
        "test_dedup.db",
        "test_worldreasoner.db",
        "demo_agent.db",
        "test.db",
    ]

    cleaned_count = 0
    for db_name in workspace_dbs:
        db_path = Path(db_name)
        if db_path.exists():
            try:
                db_path.unlink()
                cleaned_count += 1
            except Exception as e:
                print(f"Warning: Could not clean up {db_name}: {e}")

    if cleaned_count > 0:
        print(f"\n✓ Cleaned up {cleaned_count} test database(s) from workspace")


@pytest.fixture(autouse=True)
def reset_test_environment():
    """Reset any global state before each test.

    This fixture runs automatically before each test to ensure
    a clean testing environment.
    """
    # Add any global state resets here if needed in the future
    yield
    # Add any post-test cleanup here if needed
