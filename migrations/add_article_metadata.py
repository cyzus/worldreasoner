"""Migration: Add metadata column to articles table.

This migration adds the metadata field to the articles table for existing databases.

Usage:
    python migrations/add_article_metadata.py
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.utils.logging import logger


def migrate_add_metadata_column(db_path: str):
    """Add metadata column to articles table.

    Args:
        db_path: Path to the database file
    """
    logger.info(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(articles)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'metadata' in column_names:
            logger.info("Column 'metadata' already exists in articles table. No migration needed.")
            return

        # Add the metadata column
        logger.info("Adding 'metadata' column to articles table...")
        cursor.execute("""
            ALTER TABLE articles
            ADD COLUMN metadata TEXT DEFAULT '{}'
        """)

        conn.commit()
        logger.info("Successfully added 'metadata' column to articles table!")

    except sqlite3.OperationalError as e:
        if "no such table: articles" in str(e):
            logger.warning("Articles table doesn't exist yet. No migration needed.")
        else:
            logger.error(f"Migration failed: {e}")
            raise
    finally:
        conn.close()


def main():
    """Run the migration."""
    logger.info("=" * 80)
    logger.info("Migration: Add metadata column to articles table")
    logger.info("=" * 80)

    # Get database path from config
    config = get_config()
    db_path = config.database.db_path

    logger.info(f"\nTarget database: {db_path}")

    # Confirm with user
    response = input("\nProceed with migration? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        logger.info("Migration cancelled.")
        return

    # Run migration
    try:
        migrate_add_metadata_column(db_path)
        logger.info("\n" + "=" * 80)
        logger.info("Migration completed successfully!")
        logger.info("=" * 80)
    except Exception as e:
        logger.error("\n" + "=" * 80)
        logger.error("Migration failed!")
        logger.error("=" * 80)
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
