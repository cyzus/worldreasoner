"""Goal-oriented question collection CLI.

Collects questions from multiple sources until distribution goals are met.

Usage:
    python examples/run_goal_collection.py --goal config/collection_goal.yaml --db worldreasoner.db

This script:
1. Loads collection goal from YAML config
2. Initializes question sources (markets, news, etc.)
3. Orchestrates collection until goal is met
4. Saves questions to database
"""

import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

from src.config.collection_goal import CollectionGoal
from src.pipelines.question.orchestrator import (
    QuestionCollectionOrchestrator,
    OrchestratorConfig,
)
from src.pipelines.sources.markets import PolymarketRunner
from src.pipelines.sources.news import NewsBasedRunner
from src.pipelines.stages import ArticleCollectionConfig, EventIdentificationConfig, ArticleSource
from src.config.pipeline import QuestionPipelineConfig
from src.config import get_config
from src.utils.logging import logger
from src.core.database import GenericDatabase
from src.domain.models import Question


async def run_goal_collection(
    goal_path: str,
    db_path: str,
    sources_config: str = "config/sources.yaml",
    enable_polymarket: bool = True,
    enable_news: bool = True,
    parallel_sources: bool = True,
) -> None:
    """Run goal-oriented question collection.

    Args:
        goal_path: Path to collection goal YAML config
        db_path: Path to SQLite database
        sources_config: Path to sources configuration
        enable_polymarket: Enable Polymarket source
        enable_news: Enable news-based source
        parallel_sources: Run sources in parallel
    """
    # Load collection goal
    logger.info(f"Loading collection goal from {goal_path}")
    goal = CollectionGoal.from_yaml(goal_path)
    goal.validate_distributions()

    logger.info(f"Goal: {goal.total_questions} questions")
    logger.info(f"  Types: {goal.type_distribution}")
    logger.info(f"  Categories: {goal.category_distribution}")

    # Initialize database
    db = GenericDatabase(db_path)
    db.create_table(Question)

    # Initialize question sources
    sources = {}

    # Polymarket source
    if enable_polymarket:
        logger.info("Initializing Polymarket source...")
        sources["polymarket"] = PolymarketRunner(
            min_volume_usd=0.0,  # No volume filter (relaxed)
            use_agent_enhancement=True,  # Use LLM to categorize
            require_ground_truth=goal.require_ground_truth,  # Fetch resolved or active markets based on goal
        )

    # News-based source
    if enable_news:
        logger.info("Initializing news-based source...")

        # Load article sources from config
        import yaml
        with open(sources_config, 'r') as f:
            sources_data = yaml.safe_load(f)

        article_sources = []
        for source_data in sources_data.get('sources', []):
            article_sources.append(ArticleSource(**source_data))

        # Configure news pipeline stages
        app_config = get_config()

        # Derive domains from collection goal categories
        domains = [cat for cat in goal.category_distribution.keys() if cat != "other"]

        article_config = ArticleCollectionConfig(
            sources=article_sources,
            start_date=datetime.now(timezone.utc) - timedelta(days=7),
            end_date=datetime.now(timezone.utc),
            domains=domains,
        )

        event_config = EventIdentificationConfig(
            min_articles_per_event=3,
            confidence_threshold=0.7,
        )

        # Derive question config from collection goal for consistency
        question_config = QuestionPipelineConfig(
            max_questions=goal.total_questions * 2,  # Overproduce to allow filtering
            domains=list(goal.category_distribution.keys()),
            question_types=list(goal.type_distribution.keys()),
            require_ground_truth=goal.require_ground_truth,  # Use same mode as goal
        )

        sources["news"] = NewsBasedRunner(
            article_config=article_config,
            event_config=event_config,
            question_config=question_config,
            db_path=db_path,
        )

    if not sources:
        logger.error("No sources enabled! Enable at least one source.")
        return

    logger.info(f"Initialized {len(sources)} sources: {list(sources.keys())}")

    # Configure orchestrator
    orchestrator_config = OrchestratorConfig(
        max_iterations=1,
        parallel_sources=parallel_sources,
        save_intermediate_results=True,
    )

    # Create orchestrator
    orchestrator = QuestionCollectionOrchestrator(
        goal=goal,
        sources=sources,
        config=orchestrator_config,
        db_path=db_path,
    )

    # Run collection
    logger.info("\nStarting collection orchestration...")
    result = await orchestrator.collect_until_goal_met()

    # Display results
    logger.info("\n" + "=" * 60)
    logger.info("COLLECTION RESULTS")
    logger.info("=" * 60)
    logger.info(f"Goal met: {result.goal_met}")
    logger.info(f"Questions collected: {len(result.questions)}/{goal.total_questions}")
    logger.info(f"Iterations: {result.iterations}")
    logger.info(f"Duration: {result.duration_seconds():.1f}s")

    if result.errors:
        logger.warning(f"\nErrors encountered: {len(result.errors)}")
        for error in result.errors[:5]:  # Show first 5
            logger.warning(f"  - {error}")

    # Show source breakdown
    logger.info("\nBy Source:")
    for source, count in result.progress.by_source.items():
        logger.info(f"  {source:15} {count:3}")

    logger.info("\nBy Type:")
    for qtype, count in result.progress.by_type.items():
        target = goal.type_distribution.get(qtype, 0)
        logger.info(f"  {qtype:15} {count:3}/{target:3}")

    logger.info("\nBy Category:")
    for category, count in result.progress.by_category.items():
        target = goal.category_distribution.get(category, 0)
        logger.info(f"  {category:15} {count:3}/{target:3}")

    logger.info("=" * 60)

    # Show sample questions
    if result.questions:
        logger.info("\nSample questions collected:")
        for i, q in enumerate(result.questions[:3], 1):
            logger.info(f"\n{i}. [{q.question_type}] {q.question_text}")
            logger.info(f"   Source: {q.metadata.get('source', 'unknown')}")
            logger.info(f"   Category: {q.metadata.get('category', 'other')}")
            logger.info(f"   Resolution: {q.resolution_date.strftime('%Y-%m-%d') if q.resolution_date else 'N/A'}")

    logger.success("\nCollection complete!")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Goal-oriented question collection from multiple sources"
    )

    parser.add_argument(
        "--goal",
        type=str,
        default="config/collection_goal.yaml",
        help="Path to collection goal YAML config",
    )

    parser.add_argument(
        "--db",
        type=str,
        default="worldreasoner.db",
        help="Path to SQLite database",
    )

    parser.add_argument(
        "--sources",
        type=str,
        default="config/sources.yaml",
        help="Path to sources configuration",
    )

    parser.add_argument(
        "--no-polymarket",
        action="store_true",
        help="Disable Polymarket source",
    )

    parser.add_argument(
        "--no-news",
        action="store_true",
        help="Disable news-based source",
    )

    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run sources sequentially instead of in parallel",
    )

    args = parser.parse_args()

    # Validate goal file exists
    if not Path(args.goal).exists():
        logger.error(f"Goal config not found: {args.goal}")
        logger.info("Create one from the example:")
        logger.info("  cp config/collection_goal.example.yaml config/collection_goal.yaml")
        return

    # Run collection
    asyncio.run(
        run_goal_collection(
            goal_path=args.goal,
            db_path=args.db,
            sources_config=args.sources,
            enable_polymarket=not args.no_polymarket,
            enable_news=not args.no_news,
            parallel_sources=not args.sequential,
        )
    )


if __name__ == "__main__":
    main()
