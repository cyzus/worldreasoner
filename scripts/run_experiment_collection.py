"""Run the experiment dataset collection (300 questions).

Collects 300 high-quality questions distributed across:
  - 6 domains: Finance, Politics, Sports, Culture, Climate, Health
  - 3 time horizons: Short (<=7d), Medium (7-90d), Long (90d+)
  - 4 question types: Binary, MCQ, Quantity, Timeframe

Usage:
    # Full collection (all sources, default config)
    python scripts/run_experiment_collection.py

    # Polymarket only (faster, binary/MCQ heavy)
    python scripts/run_experiment_collection.py --no-news

    # Resume from existing database
    python scripts/run_experiment_collection.py --db experiment.db

    # Custom goal config
    python scripts/run_experiment_collection.py --goal config/collection_goal_experiment.yaml

    # Dry run (show plan without collecting)
    python scripts/run_experiment_collection.py --dry-run

    # More iterations to fill gaps
    python scripts/run_experiment_collection.py --max-iterations 5
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_config
from src.config.collection_goal import CollectionGoal, TimeHorizon
from src.config.pipeline import QuestionPipelineConfig
from src.core.database import GenericDatabase
from src.domain.models import Question, Article, Event, CausalHypothesis
from src.pipelines.collection.orchestrator import (
    QuestionCollectionOrchestrator,
    OrchestratorConfig,
)
from src.pipelines.collection.runner_polymarket import PolymarketRunner
from src.pipelines.collection.progress import classify_question_time_horizon
from src.utils.logging import logger


def print_plan(goal: CollectionGoal) -> None:
    """Display the collection plan without executing."""
    print("\n" + "=" * 60)
    print("  EXPERIMENT COLLECTION PLAN")
    print("=" * 60)

    print(f"\n  Total questions: {goal.total_questions}")
    print(f"  Require ground truth: {goal.require_ground_truth}")
    print(f"  Resolution window: {goal.quality.min_resolution_days}d to {goal.quality.max_resolution_days}d")

    print("\n  Type Distribution:")
    for qtype, count in goal.type_distribution.items():
        qtype_str = qtype.value if hasattr(qtype, 'value') else str(qtype)
        print(f"    {qtype_str:15} {count:4} questions")

    print("\n  Domain Distribution:")
    for domain, count in goal.category_distribution.items():
        domain_str = domain.value if hasattr(domain, 'value') else str(domain)
        print(f"    {domain_str:15} {count:4} questions")

    if goal.time_horizon_distribution:
        print("\n  Time Horizon Distribution:")
        for horizon, count in goal.time_horizon_distribution.items():
            horizon_str = horizon.value if hasattr(horizon, 'value') else str(horizon)
            day_range = TimeHorizon.get_day_range(TimeHorizon(horizon_str))
            print(f"    {horizon_str:15} {count:4} questions ({day_range[0]}-{day_range[1]} days)")

    print("\n  Source Minimums:")
    for source, count in goal.source_minimums.items():
        print(f"    {source:15} {count:4} questions")

    print("\n  Quality Requirements:")
    print(f"    Difficulty: {goal.quality.min_difficulty}-{goal.quality.max_difficulty}")
    print(f"    Min confidence: {goal.quality.min_confidence_score}")
    print(f"    Require criteria: {goal.quality.require_resolution_criteria}")

    print("\n" + "=" * 60)


def print_results(
    questions: list,
    goal: CollectionGoal,
    goal_met: bool,
    iterations: int,
    duration_s: float,
    errors: list,
) -> None:
    """Display collection results with distribution analysis."""
    print("\n" + "=" * 60)
    print("  COLLECTION RESULTS")
    print("=" * 60)

    status = "GOAL MET" if goal_met else "GOAL NOT MET"
    print(f"\n  Status: {status}")
    print(f"  Total collected: {len(questions)}/{goal.total_questions}")
    print(f"  Iterations: {iterations}")
    print(f"  Duration: {duration_s:.1f}s")
    if errors:
        print(f"  Errors: {len(errors)}")

    # Distribution breakdown
    by_type = defaultdict(int)
    by_domain = defaultdict(int)
    by_source = defaultdict(int)
    by_horizon = defaultdict(int)
    with_ground_truth = 0
    with_criteria = 0

    for q in questions:
        qtype = q.question_type.value if hasattr(q.question_type, 'value') else str(q.question_type)
        domain = q.domain.value if hasattr(q.domain, 'value') else str(q.domain)
        by_type[qtype] += 1
        by_domain[domain] += 1
        by_source[q.source] += 1
        horizon = classify_question_time_horizon(q)
        by_horizon[horizon] += 1
        if q.ground_truth is not None:
            with_ground_truth += 1
        if q.resolution_criteria:
            with_criteria += 1

    print(f"\n  By Type:")
    for qtype, target in goal.type_distribution.items():
        qtype_str = qtype.value if hasattr(qtype, 'value') else str(qtype)
        actual = by_type.get(qtype_str, 0)
        status = "OK" if actual >= target else f"NEED {target - actual} MORE"
        print(f"    {qtype_str:15} {actual:4}/{target:4}  {status}")

    print(f"\n  By Domain:")
    for domain, target in goal.category_distribution.items():
        domain_str = domain.value if hasattr(domain, 'value') else str(domain)
        actual = by_domain.get(domain_str, 0)
        status = "OK" if actual >= target else f"NEED {target - actual} MORE"
        print(f"    {domain_str:15} {actual:4}/{target:4}  {status}")

    if goal.time_horizon_distribution:
        print(f"\n  By Time Horizon:")
        for horizon, target in goal.time_horizon_distribution.items():
            horizon_str = horizon.value if hasattr(horizon, 'value') else str(horizon)
            actual = by_horizon.get(horizon_str, 0)
            status = "OK" if actual >= target else f"NEED {target - actual} MORE"
            print(f"    {horizon_str:15} {actual:4}/{target:4}  {status}")

        unknown = by_horizon.get("unknown", 0)
        if unknown > 0:
            print(f"    {'unknown':15} {unknown:4}       (missing estimated_start_time)")

    print(f"\n  By Source:")
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {source:15} {count:4}")

    print(f"\n  Quality:")
    print(f"    With ground truth: {with_ground_truth}/{len(questions)}")
    print(f"    With criteria: {with_criteria}/{len(questions)}")

    # Sample questions
    if questions:
        print(f"\n  Sample Questions:")
        for i, q in enumerate(questions[:5], 1):
            qtype = q.question_type.value if hasattr(q.question_type, 'value') else str(q.question_type)
            domain = q.domain.value if hasattr(q.domain, 'value') else str(q.domain)
            horizon = classify_question_time_horizon(q)
            text = q.question_text[:80] + "..." if len(q.question_text) > 80 else q.question_text
            print(f"\n    {i}. {text}")
            print(f"       Type: {qtype} | Domain: {domain} | Horizon: {horizon} | Source: {q.source}")
            if q.ground_truth is not None:
                print(f"       Ground truth: {q.ground_truth}")

    print("\n" + "=" * 60)


def export_dataset_summary(questions: list, output_path: str) -> None:
    """Export a JSON summary of the collected dataset."""
    summary = {
        "collection_date": datetime.now(timezone.utc).isoformat(),
        "total_questions": len(questions),
        "distributions": {
            "by_type": defaultdict(int),
            "by_domain": defaultdict(int),
            "by_source": defaultdict(int),
            "by_time_horizon": defaultdict(int),
        },
        "quality": {
            "with_ground_truth": 0,
            "with_resolution_criteria": 0,
            "avg_difficulty": 0.0,
        },
        "questions": [],
    }

    difficulties = []
    for q in questions:
        qtype = q.question_type.value if hasattr(q.question_type, 'value') else str(q.question_type)
        domain = q.domain.value if hasattr(q.domain, 'value') else str(q.domain)
        horizon = classify_question_time_horizon(q)

        summary["distributions"]["by_type"][qtype] += 1
        summary["distributions"]["by_domain"][domain] += 1
        summary["distributions"]["by_source"][q.source] += 1
        summary["distributions"]["by_time_horizon"][horizon] += 1

        if q.ground_truth is not None:
            summary["quality"]["with_ground_truth"] += 1
        if q.resolution_criteria:
            summary["quality"]["with_resolution_criteria"] += 1
        if q.difficulty:
            difficulties.append(q.difficulty)

        summary["questions"].append({
            "id": q.id,
            "text": q.question_text[:200],
            "type": qtype,
            "domain": domain,
            "source": q.source,
            "time_horizon": horizon,
            "difficulty": q.difficulty,
            "has_ground_truth": q.ground_truth is not None,
            "resolution_date": q.resolution_date.isoformat() if q.resolution_date else None,
            "estimated_start_time": q.estimated_start_time.isoformat() if q.estimated_start_time else None,
        })

    if difficulties:
        summary["quality"]["avg_difficulty"] = sum(difficulties) / len(difficulties)

    # Convert defaultdicts to regular dicts for JSON
    summary["distributions"] = {k: dict(v) for k, v in summary["distributions"].items()}

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n  Dataset summary exported to: {output_path}")


def _load_article_sources(sources_config: str, domains: list) -> list:
    """Load and filter article sources from YAML config."""
    import yaml
    from src.pipelines.collection import ArticleSource

    with open(sources_config, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    all_sources = []
    for src_data in config_data.get("sources", []):
        try:
            source = ArticleSource(**src_data)
            all_sources.append(source)
        except Exception as e:
            logger.warning(f"Skipping invalid source: {e}")

    # Filter to matching domains
    domain_strs = [d.value if hasattr(d, 'value') else str(d) for d in domains]
    filtered = [s for s in all_sources if s.domain in domain_strs]

    if not filtered:
        logger.warning(f"No sources match domains {domain_strs}, using all sources")
        return all_sources

    return filtered


def _create_news_runner(article_sources, domains, question_types, goal):
    """Create a NewsBasedRunner with experiment-appropriate configuration."""
    from datetime import timedelta
    from src.pipelines.collection import ArticleCollectionConfig, NewsBasedRunner

    domain_strs = [d.value if hasattr(d, 'value') else str(d) for d in domains]
    qtype_strs = [t.value if hasattr(t, 'value') else str(t) for t in question_types]

    days_back = abs(goal.quality.min_resolution_days)
    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=days_back),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=8,
        domains=domain_strs,
    )

    question_config = QuestionPipelineConfig(
        max_questions=goal.total_questions,
        domains=domain_strs,
        question_types=qtype_strs,
        require_ground_truth=goal.require_ground_truth,
        article_batch_size=20,
    )

    return NewsBasedRunner(
        article_config=article_config,
        question_config=question_config,
        db_path="worldreasoner.db",  # Will be overridden by caller
    )


async def run_collection(args) -> None:
    """Execute the experiment collection pipeline."""
    goal_path = args.goal
    db_path = args.db

    # Load goal
    if not Path(goal_path).exists():
        print(f"Error: Goal config not found: {goal_path}")
        print("Create one from the example or use the experiment config:")
        print("  python scripts/run_experiment_collection.py --goal config/collection_goal_experiment.yaml")
        sys.exit(1)

    goal = CollectionGoal.from_yaml(goal_path)
    goal.validate_distributions()

    # Dry run - just show the plan
    if args.dry_run:
        print_plan(goal)
        return

    print_plan(goal)
    print("\n  Starting collection...\n")

    # Initialize database
    db = GenericDatabase(db_path)
    db.create_table(Question)
    db.create_table(Article)
    db.create_table(Event)
    db.create_table(CausalHypothesis)

    # Initialize sources
    sources = {}

    if not args.no_polymarket:
        sources["polymarket"] = PolymarketRunner(
            min_volume_usd=0.0,
            require_ground_truth=goal.require_ground_truth,
        )
        logger.info("Polymarket source enabled")

    if not args.no_news:
        domains = list(goal.category_distribution.keys())
        article_sources = _load_article_sources(args.sources, domains)

        news_runner = _create_news_runner(
            article_sources=article_sources,
            domains=domains,
            question_types=list(goal.type_distribution.keys()),
            goal=goal,
        )
        news_runner.db_path = db_path
        sources["news"] = news_runner
        logger.info(f"News source enabled with {len(article_sources)} article sources")

    if not sources:
        print("Error: No sources enabled! Remove --no-polymarket or --no-news.")
        sys.exit(1)

    # Configure orchestrator
    orchestrator_config = OrchestratorConfig(
        max_iterations=args.max_iterations,
        parallel_sources=not args.sequential,
        save_intermediate_results=True,
    )

    # Run orchestration
    started_at = datetime.now(timezone.utc)

    orchestrator = QuestionCollectionOrchestrator(
        goal=goal,
        sources=sources,
        config=orchestrator_config,
        db_path=db_path,
    )

    result = await orchestrator.collect_until_goal_met()

    duration_s = (datetime.now(timezone.utc) - started_at).total_seconds()

    # Display results
    print_results(
        questions=result.questions,
        goal=goal,
        goal_met=result.goal_met,
        iterations=result.iterations,
        duration_s=duration_s,
        errors=result.errors,
    )

    # Export summary
    if args.export:
        export_dataset_summary(result.questions, args.export)

    # Auto-index articles for search
    if not args.skip_indexing and result.questions:
        try:
            from src.utils.search_indexing import auto_index_articles
            print("\n  Indexing articles for search...")
            await auto_index_articles(db_path=db_path)
            print("  Indexing complete.")
        except Exception as e:
            logger.warning(f"Auto-indexing failed: {e}")

    if not result.goal_met:
        print("\n  TIP: Run again to resume collection (existing questions are loaded from DB).")
        print(f"       python scripts/run_experiment_collection.py --db {db_path} --max-iterations {args.max_iterations + 3}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Collect 300 questions for the WorldReasoner experiment dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full collection with default experiment config
  python scripts/run_experiment_collection.py

  # Dry run (show plan only)
  python scripts/run_experiment_collection.py --dry-run

  # Polymarket only, export summary
  python scripts/run_experiment_collection.py --no-news --export dataset_summary.json

  # Resume from existing database with more iterations
  python scripts/run_experiment_collection.py --db experiment.db --max-iterations 5
        """,
    )

    parser.add_argument(
        "--goal",
        default="config/collection_goal_experiment.yaml",
        help="Path to collection goal YAML config (default: config/collection_goal_experiment.yaml)",
    )
    parser.add_argument(
        "--db",
        default="experiment.db",
        help="Path to database file (default: experiment.db)",
    )
    parser.add_argument(
        "--sources",
        default="config/sources.yaml",
        help="Path to article sources config (default: config/sources.yaml)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum orchestration iterations (default: 3)",
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
        "--dry-run",
        action="store_true",
        help="Show collection plan without running",
    )
    parser.add_argument(
        "--export",
        default=None,
        help="Export dataset summary to JSON file",
    )
    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip automatic search indexing after collection",
    )

    args = parser.parse_args()
    asyncio.run(run_collection(args))


if __name__ == "__main__":
    main()
