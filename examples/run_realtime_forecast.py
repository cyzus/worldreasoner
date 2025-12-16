"""Run real-time forecasting with live information.

This script demonstrates how to use the ForecastAgent in real-time mode,
which enables access to web_search and web_fetch tools for live information.

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. MCP server running (default: http://127.0.0.1:8110/mcp)

Usage:
    # Forecast with existing question from database
    python examples/run_realtime_forecast.py --question-id q_tech_20251117_003

    # Forecast with ad-hoc question
    python examples/run_realtime_forecast.py --question-text "Will Bitcoin exceed $100k today?"

    # Custom database and max steps
    python examples/run_realtime_forecast.py --question-text "..." --db custom.db --max-steps 20
"""

import argparse
from datetime import datetime, timezone

from src.config import get_config
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.domain.models.question import QuestionType
from src.utils.enums import Domain
from src.agents.forecast_agent import ForecastAgent
from src.utils.logging import logger


def main():
    """Main entry point for real-time forecasting."""
    parser = argparse.ArgumentParser(description="Real-time forecasting with live information")

    # Question selection (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question-id", help="Existing question ID from database")
    group.add_argument("--question-text", help="Ad-hoc question text for real-time forecast")

    # Configuration
    parser.add_argument("--max-steps", type=int, default=15, help="Maximum agent steps (default: 15)")
    parser.add_argument("--db", default="worldreasoner.db", help="Database path (default: worldreasoner.db)")

    args = parser.parse_args()

    # Load configuration and database
    config = get_config()
    db = GenericDatabase(args.db)

    # Get or create question
    if args.question_id:
        question = db.get(Question, args.question_id)
        if not question:
            logger.error(f"Question not found: {args.question_id}")
            return
        logger.info(f"Using existing question: {args.question_id}")
    else:
        # Create ad-hoc question for real-time forecast
        question = Question(
            id=f"q_realtime_{int(datetime.now(timezone.utc).timestamp())}",
            question_text=args.question_text,
            question_type=QuestionType.BOOLEAN,
            domain=Domain.GENERAL,
            resolution_date=datetime.now(timezone.utc),  # Will resolve "now"
            created_at=datetime.now(timezone.utc)
        )
        logger.info(f"Created ad-hoc question: {question.id}")

    # Display question details
    print("=" * 80)
    print("REAL-TIME FORECASTING")
    print("=" * 80)
    print(f"\nQuestion: {question.question_text}")
    print(f"Question ID: {question.id}")
    print(f"Mode: real_time (web search and fetch enabled)")
    print(f"Simulated date: {datetime.now(timezone.utc).date()} (today)")
    print("\n" + "=" * 80)

    # Create real-time forecast agent
    agent = ForecastAgent(
        question=question,
        simulated_date=datetime.now(timezone.utc).isoformat(),
        knowledge_cutoff=config.llm.knowledge_cutoff,
        config=config,
        mode="real_time",
        max_steps=args.max_steps
    )

    logger.info("Starting real-time forecast agent...")
    print("\nAgent is running (web tools enabled)...\n")

    # Run the agent
    result = agent.run(f"Make a forecast: {question.question_text}")

    # Display result
    print("\n" + "=" * 80)
    print("FORECAST RESULT")
    print("=" * 80)
    print(result)
    print("\n" + "=" * 80)

    logger.info("Real-time forecast completed")


if __name__ == "__main__":
    main()
