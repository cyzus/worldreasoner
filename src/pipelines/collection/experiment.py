"""Experiment dataset collection orchestration.

Importable home for the logic that used to live in
``scripts/run_experiment_collection.py``. Collects a distribution-balanced set
of questions across domains, time horizons, and question types. The
``wr question collect`` CLI command wraps :func:`run_experiment_collection`.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.config.collection_goal import CollectionGoal, TimeHorizon
from src.config.pipeline import QuestionPipelineConfig
from src.core.database import GenericDatabase
from src.domain.models import Article, CausalHypothesis, Event, Question
from src.pipelines.collection.orchestrator import (
    OrchestratorConfig,
    QuestionCollectionOrchestrator,
)
from src.pipelines.collection.progress import classify_question_time_horizon
from src.pipelines.collection.runner_polymarket import PolymarketRunner
from src.utils.logging import logger


def print_plan(goal: CollectionGoal) -> None:
    """Display the collection plan without executing."""
    print("\n" + "=" * 60)
    print("  EXPERIMENT COLLECTION PLAN")
    print("=" * 60)

    print(f"\n  Total questions: {goal.total_questions}")
    print(f"  Require ground truth: {goal.require_ground_truth}")
    print(
        f"  Resolution window: {goal.quality.min_resolution_days}d "
        f"to {goal.quality.max_resolution_days}d"
    )

    print("\n  Type Distribution:")
    for qtype, count in goal.type_distribution.items():
        qtype_str = qtype.value if hasattr(qtype, "value") else str(qtype)
        print(f"    {qtype_str:15} {count:4} questions")

    print("\n  Domain Distribution:")
    for domain, count in goal.category_distribution.items():
        domain_str = domain.value if hasattr(domain, "value") else str(domain)
        print(f"    {domain_str:15} {count:4} questions")

    if goal.time_horizon_distribution:
        print("\n  Time Horizon Distribution:")
        for horizon, count in goal.time_horizon_distribution.items():
            horizon_str = horizon.value if hasattr(horizon, "value") else str(horizon)
            day_range = TimeHorizon.get_day_range(TimeHorizon(horizon_str))
            print(
                f"    {horizon_str:15} {count:4} questions "
                f"({day_range[0]}-{day_range[1]} days)"
            )

    print("\n  Source Minimums:")
    for source, count in goal.source_minimums.items():
        print(f"    {source:15} {count:4} questions")

    print("\n  Quality Requirements:")
    print(
        f"    Difficulty: {goal.quality.min_difficulty}-{goal.quality.max_difficulty}"
    )
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

    print(f"\n  Status: {'GOAL MET' if goal_met else 'GOAL NOT MET'}")
    print(f"  Total collected: {len(questions)}/{goal.total_questions}")
    print(f"  Iterations: {iterations}")
    print(f"  Duration: {duration_s:.1f}s")
    if errors:
        print(f"  Errors: {len(errors)}")

    by_type: defaultdict = defaultdict(int)
    by_domain: defaultdict = defaultdict(int)
    by_source: defaultdict = defaultdict(int)
    by_horizon: defaultdict = defaultdict(int)
    with_ground_truth = 0
    with_criteria = 0

    for q in questions:
        qtype = (
            q.question_type.value
            if hasattr(q.question_type, "value")
            else str(q.question_type)
        )
        domain = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
        by_type[qtype] += 1
        by_domain[domain] += 1
        by_source[q.source] += 1
        by_horizon[classify_question_time_horizon(q)] += 1
        if q.ground_truth is not None:
            with_ground_truth += 1
        if q.resolution_criteria:
            with_criteria += 1

    print("\n  By Type:")
    for qtype, target in goal.type_distribution.items():
        qtype_str = qtype.value if hasattr(qtype, "value") else str(qtype)
        actual = by_type.get(qtype_str, 0)
        status = "OK" if actual >= target else f"NEED {target - actual} MORE"
        print(f"    {qtype_str:15} {actual:4}/{target:4}  {status}")

    print("\n  By Domain:")
    for domain, target in goal.category_distribution.items():
        domain_str = domain.value if hasattr(domain, "value") else str(domain)
        actual = by_domain.get(domain_str, 0)
        status = "OK" if actual >= target else f"NEED {target - actual} MORE"
        print(f"    {domain_str:15} {actual:4}/{target:4}  {status}")

    if goal.time_horizon_distribution:
        print("\n  By Time Horizon:")
        for horizon, target in goal.time_horizon_distribution.items():
            horizon_str = horizon.value if hasattr(horizon, "value") else str(horizon)
            actual = by_horizon.get(horizon_str, 0)
            status = "OK" if actual >= target else f"NEED {target - actual} MORE"
            print(f"    {horizon_str:15} {actual:4}/{target:4}  {status}")
        unknown = by_horizon.get("unknown", 0)
        if unknown > 0:
            print(
                f"    {'unknown':15} {unknown:4}       "
                f"(missing estimated_start_time)"
            )

    print("\n  By Source:")
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {source:15} {count:4}")

    print("\n  Quality:")
    print(f"    With ground truth: {with_ground_truth}/{len(questions)}")
    print(f"    With criteria: {with_criteria}/{len(questions)}")

    if questions:
        print("\n  Sample Questions:")
        for i, q in enumerate(questions[:5], 1):
            qtype = (
                q.question_type.value
                if hasattr(q.question_type, "value")
                else str(q.question_type)
            )
            domain = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
            horizon = classify_question_time_horizon(q)
            text = (
                q.question_text[:80] + "..."
                if len(q.question_text) > 80
                else q.question_text
            )
            print(f"\n    {i}. {text}")
            print(
                f"       Type: {qtype} | Domain: {domain} | "
                f"Horizon: {horizon} | Source: {q.source}"
            )
            if q.ground_truth is not None:
                print(f"       Ground truth: {q.ground_truth}")

    print("\n" + "=" * 60)


def export_dataset_summary(questions: list, output_path: str) -> None:
    """Export a JSON summary of the collected dataset."""
    summary: dict = {
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
        qtype = (
            q.question_type.value
            if hasattr(q.question_type, "value")
            else str(q.question_type)
        )
        domain = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
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

        summary["questions"].append(
            {
                "id": q.id,
                "text": q.question_text[:200],
                "type": qtype,
                "domain": domain,
                "source": q.source,
                "time_horizon": horizon,
                "difficulty": q.difficulty,
                "has_ground_truth": q.ground_truth is not None,
                "resolution_date": (
                    q.resolution_date.isoformat() if q.resolution_date else None
                ),
                "estimated_start_time": (
                    q.estimated_start_time.isoformat()
                    if q.estimated_start_time
                    else None
                ),
            }
        )

    if difficulties:
        summary["quality"]["avg_difficulty"] = sum(difficulties) / len(difficulties)

    summary["distributions"] = {
        k: dict(v) for k, v in summary["distributions"].items()
    }

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
            all_sources.append(ArticleSource(**src_data))
        except Exception as e:
            logger.warning(f"Skipping invalid source: {e}")

    domain_strs = [d.value if hasattr(d, "value") else str(d) for d in domains]
    filtered = [s for s in all_sources if s.domain in domain_strs]
    if not filtered:
        logger.warning(f"No sources match domains {domain_strs}, using all sources")
        return all_sources
    return filtered


def _create_news_runner(article_sources, domains, question_types, goal, db_path):
    """Create a NewsBasedRunner with experiment-appropriate configuration."""
    from src.pipelines.collection import ArticleCollectionConfig, NewsBasedRunner

    domain_strs = [d.value if hasattr(d, "value") else str(d) for d in domains]
    qtype_strs = [t.value if hasattr(t, "value") else str(t) for t in question_types]

    days_back = abs(goal.quality.min_resolution_days)
    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=days_back),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=15,
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
        db_path=db_path,
    )


async def run_experiment_collection(
    goal_path: str = "config/collection_goal_experiment.yaml",
    db_path: str = "experiment.db",
    sources_config: str = "config/sources.yaml",
    max_iterations: int = 3,
    enable_polymarket: bool = True,
    enable_news: bool = True,
    parallel_sources: bool = True,
    dry_run: bool = False,
    export_path: Optional[str] = None,
    skip_indexing: bool = False,
) -> bool:
    """Run experiment dataset collection until distribution goals are met.

    Returns True if the goal was met, False otherwise.
    """
    if not Path(goal_path).exists():
        print(f"Error: Goal config not found: {goal_path}")
        return False

    goal = CollectionGoal.from_yaml(goal_path)
    goal.validate_distributions()

    print_plan(goal)
    if dry_run:
        return True

    print("\n  Starting collection...\n")

    db = GenericDatabase(db_path)
    db.create_table(Question)
    db.create_table(Article)
    db.create_table(Event)
    db.create_table(CausalHypothesis)

    sources: dict = {}
    if enable_polymarket:
        sources["polymarket"] = PolymarketRunner(
            min_volume_usd=0.0,
            require_ground_truth=goal.require_ground_truth,
        )
        logger.info("Polymarket source enabled")

    if enable_news:
        domains = list(goal.category_distribution.keys())
        article_sources = _load_article_sources(sources_config, domains)
        sources["news"] = _create_news_runner(
            article_sources=article_sources,
            domains=domains,
            question_types=list(goal.type_distribution.keys()),
            goal=goal,
            db_path=db_path,
        )
        logger.info(
            f"News source enabled with {len(article_sources)} article sources"
        )

    if not sources:
        print("Error: No sources enabled! Enable Polymarket or news.")
        return False

    orchestrator = QuestionCollectionOrchestrator(
        goal=goal,
        sources=sources,
        config=OrchestratorConfig(
            max_iterations=max_iterations,
            parallel_sources=parallel_sources,
            save_intermediate_results=True,
        ),
        db_path=db_path,
    )

    started_at = datetime.now(timezone.utc)
    result = await orchestrator.collect_until_goal_met()
    duration_s = (datetime.now(timezone.utc) - started_at).total_seconds()

    print_results(
        questions=result.questions,
        goal=goal,
        goal_met=result.goal_met,
        iterations=result.iterations,
        duration_s=duration_s,
        errors=result.errors,
    )

    if export_path:
        export_dataset_summary(result.questions, export_path)

    if not skip_indexing and result.questions:
        try:
            from src.core.search_indexing import auto_index_articles

            print("\n  Indexing articles for search...")
            await auto_index_articles(db_path=db_path)
            print("  Indexing complete.")
        except Exception as e:
            logger.warning(f"Auto-indexing failed: {e}")

    if not result.goal_met:
        print(
            "\n  TIP: Run again to resume collection "
            "(existing questions are loaded from DB)."
        )
    return result.goal_met
