"""Shared test fixtures and configuration for all tests.

This module provides reusable fixtures for database management,
ensuring proper cleanup and isolation between tests.

## Temporary Database Locations

By default, pytest creates temp databases in your system's temp directory:
- Windows: C:\\Users\\<username>\\AppData\\Local\\Temp\\pytest-of-<username>\\pytest-<N>\\
- Linux/Mac: /tmp/pytest-of-<username>/pytest-<N>/

## Debugging: Keep Databases for Inspection

If you want to inspect databases during/after tests, use one of these options:

Option 1: Use --basetemp to specify a custom location:
    pytest tests/ --basetemp=./test-output
    # Databases will be in ./test-output/test_<testname>/test.db

Option 2: Use persistent_test_db_path fixture instead:
    def test_something(persistent_test_db_path):
        # Database will be in ./test-dbs/<testname>.db (NOT auto-cleaned)

Option 3: Use pytest --keeptemp flag (if available in your pytest version):
    pytest tests/ --keeptemp

Option 4: Print the database path in your test:
    def test_something(test_db_path):
        print(f"\\nDatabase location: {test_db_path}")
        # Run with: pytest -s to see output
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.domain.models.domain import Domain


def create_test_question(**kwargs) -> Question:
    """Create a valid test question with all required fields.

    Args:
        **kwargs: Override default values. Use 'source_name' which will
        be mapped to 'source' field internally.

    Returns:
        Question: Valid question instance for testing
    """
    # Handle source_name -> source mapping
    if "source_name" in kwargs:
        kwargs["source"] = kwargs.pop("source_name")

    defaults = {
        "id": "test_q_1",
        "question_text": "This is a test question with at least 20 characters?",
        "question_type": "boolean",
        "domain": Domain.GENERAL,
        "source": "test",
        "difficulty": 3,
        "cutoff_date": datetime.now(timezone.utc),
        "resolution_date": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return Question(**defaults)


@pytest.fixture
def test_db_path(tmp_path):
    """Provide a temporary database path that auto-cleans after test.

    The database file is created in pytest's temporary directory
    and automatically cleaned up when the test finishes.

    Default location (auto-cleaned):
    - Windows: C:\\Users\\<user>\\AppData\\Local\\Temp\\pytest-of-<user>\\pytest-<N>\\test.db
    - Linux/Mac: /tmp/pytest-of-<user>/pytest-<N>/test.db

    To see the exact location, run with -s flag:
        pytest -s tests/your_test.py

    To keep databases for inspection, use:
        pytest --basetemp=./test-output tests/

    Usage:
        def test_something(test_db_path):
            print(f"DB at: {test_db_path}")  # See with pytest -s
            stage = ArticleCollectionStage(config, db_path=test_db_path)
            # Database will be cleaned up automatically

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        str: Path to temporary database file
    """
    db_path = tmp_path / "test.db"
    return str(db_path)


@pytest.fixture
def persistent_test_db_path(request):
    """Provide a persistent database path for debugging (NOT auto-cleaned).

    Use this fixture when you want to inspect the database after the test.
    Databases are saved to ./test-dbs/<testname>.db

    WARNING: These databases are NOT automatically cleaned up.
    You must manually delete them or run: rm -rf test-dbs/

    Usage:
        def test_something(persistent_test_db_path):
            # Database will be in ./test-dbs/test_something.db
            stage = ArticleCollectionStage(config, db_path=persistent_test_db_path)
            # Database persists after test for inspection

    Args:
        request: pytest's request fixture (provides test name)

    Returns:
        str: Path to persistent database file
    """
    # Create test-dbs directory if it doesn't exist
    test_db_dir = Path("test-dbs")
    test_db_dir.mkdir(exist_ok=True)

    # Use test name as database filename
    test_name = request.node.name
    db_path = test_db_dir / f"{test_name}.db"

    # Remove old database if exists
    if db_path.exists():
        db_path.unlink()

    return str(db_path)


@pytest.fixture
def test_db(tmp_path):
    """Provide a temporary GenericDatabase instance that auto-cleans.

    Creates a fully initialized GenericDatabase instance in a temporary directory.
    All tables (articles, events, questions) are created automatically.

    Usage:
        def test_something(test_db):
            test_db.save(Article, article_instance)
            test_db.save(Event, event_instance)
            # Database will be cleaned up automatically

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        GenericDatabase: Initialized database instance
    """
    db_path = tmp_path / "test.db"
    db = GenericDatabase(str(db_path))
    # Initialize schema
    from src.domain.models import Article, Event, Question, CausalHypothesis
    # Import EventOutcomeImpact to ensure it can be created
    # Check if we can import it from models or directly
    try:
        from src.domain.models import EventOutcomeImpact
        db.create_table(EventOutcomeImpact)
    except ImportError:
        # Fallback if not exported in generic models
        from src.domain.models.event_outcome_impact import EventOutcomeImpact
        db.create_table(EventOutcomeImpact)
        
    db.create_table(Article)
    db.create_table(Event)
    db.create_table(Question)
    db.create_table(CausalHypothesis)
    return db


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
