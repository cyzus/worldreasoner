"""Create the forecasts table in the database.

Run this once to add the forecasts table to your existing database.

Usage:
    python scripts/create_forecasts_table.py
    python scripts/create_forecasts_table.py --db custom.db
"""

import argparse
from src.core.database import GenericDatabase
from src.domain.models import Forecast
from src.utils.logging import logger


def main():
    """Create forecasts table."""
    parser = argparse.ArgumentParser(
        description="Create forecasts table in WorldReasoner database"
    )
    parser.add_argument(
        '--db',
        type=str,
        default='worldreasoner.db',
        help='Path to database file (default: worldreasoner.db)'
    )
    args = parser.parse_args()

    logger.info(f"Creating forecasts table in {args.db}")

    # Initialize database
    db = GenericDatabase(args.db)

    # Create table (idempotent - won't error if table exists)
    db.create_table(Forecast)

    logger.info("Forecasts table created successfully")
    print(f"Forecasts table created in {args.db}")


if __name__ == "__main__":
    main()
