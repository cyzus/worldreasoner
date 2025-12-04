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
from src.pipelines.question.sources.markets import PolymarketRunner
from src.pipelines.question.sources.news import NewsBasedRunner
from src.pipelines.stages import ArticleCollectionConfig, EventIdentificationConfig, ArticleSource
from src.config.pipeline import QuestionPipelineConfig
from src.config import get_config
from src.utils.logging import logger
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.utils.search_indexing import auto_index_articles, should_auto_index


async def run_goal_collection(
    goal_path: str,
    db_path: str,
    sources_config: str = "config/sources.yaml",
    enable_polymarket: bool = True,
    enable_news: bool = True,
    parallel_sources: bool = True,
    skip_indexing: bool = False,
) -> None:
    """Run goal-oriented question collection.

    Args:
        goal_path: Path to collection goal YAML config
        db_path: Path to SQLite database
        sources_config: Path to sources configuration
        enable_polymarket: Enable Polymarket source
        enable_news: Enable news-based source
        parallel_sources: Run sources in parallel
        skip_indexing: Skip automatic search indexing after completion
    """
    # Load collection goal
    logger.info(f"📋 Loading collection goal from {goal_path}")
    goal = CollectionGoal.from_yaml(goal_path)
    goal.validate_distributions()

    logger.info("")
    logger.info("🎯 COLLECTION GOAL")
    logger.info("-" * 20)
    logger.info(f"Target: {goal.total_questions} questions")
    logger.info(f"Types: {goal.type_distribution}")
    logger.info(f"Categories: {goal.category_distribution}")
    logger.info("")

    # Initialize database
    logger.info("💾 Initializing database...")
    db = GenericDatabase(db_path)
    db.create_table(Question)

    # Initialize question sources
    logger.info("🔧 Initializing sources...")
    sources = {}

    # Polymarket source
    if enable_polymarket:
        logger.info("  📊 Polymarket source")
        sources["polymarket"] = PolymarketRunner(
            min_volume_usd=0.0,  # No volume filter (relaxed)
            use_agent_enhancement=True,  # Use LLM to categorize
            require_ground_truth=goal.require_ground_truth,  # Fetch resolved or active markets based on goal
        )

    # News-based source
    if enable_news:
        logger.info("  📰 News-based source")

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
            start_date=datetime.now(timezone.utc) - timedelta(days=abs(goal.quality.min_resolution_days)),
            end_date=datetime.now(timezone.utc),
            domains=domains,
        )

        event_config = EventIdentificationConfig()

        # Derive question config from collection goal for consistency
        question_config = QuestionPipelineConfig(
            max_questions=goal.total_questions,  # Overproduce to allow filtering
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
        logger.error("❌ No sources enabled! Enable at least one source.")
        return

    logger.info(f"✅ Initialized {len(sources)} sources: {', '.join(sources.keys())}")
    logger.info("")

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
    logger.info("Starting collection orchestration...")
    result = await orchestrator.collect_until_goal_met()

    # Display results
    logger.info("")
    logger.info("🎯 COLLECTION COMPLETE")
    logger.info("=" * 50)

    # Summary stats
    status_icon = "✅" if result.goal_met else "⚠️"
    logger.info(f"{status_icon} Goal: {'MET' if result.goal_met else 'NOT MET'}")
    logger.info(f"📊 Questions: {len(result.questions)}/{goal.total_questions}")
    logger.info(f"🔄 Iterations: {result.iterations}")
    logger.info(f"⏱️  Duration: {result.duration_seconds():.1f}s")

    if result.errors:
        logger.warning(f"❌ Errors: {len(result.errors)}")
        for error in result.errors[:3]:  # Show first 3
            logger.warning(f"   • {error}")
        if len(result.errors) > 3:
            logger.warning(f"   ... and {len(result.errors) - 3} more")

    logger.info("")

    # Distribution breakdowns
    logger.info("📈 DISTRIBUTION BREAKDOWN")
    logger.info("-" * 30)

    # Sources
    if result.progress.by_source:
        logger.info("📍 Sources:")
        for source, count in sorted(result.progress.by_source.items()):
            logger.info(f"   {source:12} {count:3}")
        logger.info("")

    # Types
    if result.progress.by_type:
        logger.info("🏷️  Types:")
        for qtype, count in sorted(result.progress.by_type.items()):
            target = goal.type_distribution.get(qtype, 0)
            status = "✅" if count >= target else "❌"
            logger.info(f"   {status} {qtype:12} {count:2}/{target:<2}")
        logger.info("")

    # Categories
    if result.progress.by_category:
        logger.info("📂 Categories:")
        for category, count in sorted(result.progress.by_category.items()):
            target = goal.category_distribution.get(category, 0)
            status = "✅" if count >= target else "❌"
            logger.info(f"   {status} {category:12} {count:2}/{target:<2}")

    # Show missing items if goal not met
    if not result.goal_met:
        logger.info("")
        logger.info("❌ MISSING ITEMS")
        logger.info("-" * 30)

        # Missing types
        if hasattr(result, 'missing_types') and result.missing_types:
            logger.info("Missing question types:")
            for qtype, needed in result.missing_types.items():
                target = goal.type_distribution.get(qtype, 0)
                collected = target - needed
                logger.info(f"   • {qtype:12} {collected}/{target}")
            logger.info("")

        # Missing categories
        if hasattr(result, 'missing_categories') and result.missing_categories:
            logger.info("Missing categories:")
            for category, needed in result.missing_categories.items():
                target = goal.category_distribution.get(category, 0)
                collected = target - needed
                logger.info(f"   • {category:12} {collected}/{target}")

    logger.info("")

    # Sample questions
    if result.questions:
        logger.info("💡 SAMPLE QUESTIONS")
        logger.info("-" * 30)
        for i, q in enumerate(result.questions[:3], 1):
            # Format question type nicely
            qtype_str = str(q.question_type).replace('QuestionType.', '')
            source_str = q.source or "unknown"
            domain_str = str(q.domain).replace('Domain.', '')

            logger.info(f"{i}. {q.question_text}")
            logger.info(f"   ├─ Type: {qtype_str}")
            logger.info(f"   ├─ Source: {source_str}")
            logger.info(f"   └─ Domain: {domain_str}")

        if len(result.questions) > 3:
            logger.info(f"   ... and {len(result.questions) - 3} more questions")

    # Quality score statistics
    if result.questions and result.questions[0].quality_score is not None:
        logger.info("")
        logger.info("⭐ QUALITY SCORE STATS")
        logger.info("-" * 30)
        scores = [q.quality_score for q in result.questions if q.quality_score is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            min_score = min(scores)
            max_score = max(scores)
            logger.info(f"   - Average: {avg_score:.2f}")
            logger.info(f"   - Min:     {min_score:.2f}")
            logger.info(f"   - Max:     {max_score:.2f}")
            
            # Show top 3 best questions
            logger.info("   Top 3 Questions:")
            sorted_questions = sorted(result.questions, key=lambda q: q.quality_score or 0.0, reverse=True)
            for i, q in enumerate(sorted_questions[:3], 1):
                logger.info(f"     {i}. (Score: {q.quality_score:.2f}) {q.question_text[:80]}...")

    logger.info("")

    # Auto-index articles for search if not skipped
    if should_auto_index(skip_indexing):
        logger.info("🔍 INDEXING ARTICLES")
        logger.info("-" * 30)
        index_stats = await auto_index_articles(db_path=db_path)
        if index_stats['status'] == 'success':
            logger.info(f"✅ Indexed {index_stats['newly_indexed']} new articles")
            logger.info(f"   Total indexed: {index_stats['final_indexed']}")
        elif index_stats['status'] == 'up_to_date':
            logger.info("✅ Search index is up to date")
        elif index_stats['status'] == 'no_articles':
            logger.info("⚠️  No articles to index")
        else:
            logger.info(f"❌ Indexing failed: {index_stats.get('error', 'Unknown error')}")

    logger.success("🎉 Collection complete!")


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

    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip automatic search indexing after pipeline completion",
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
            skip_indexing=args.skip_indexing,
        )
    )


if __name__ == "__main__":
    main()
