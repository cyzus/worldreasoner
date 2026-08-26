"""Commands for creating and validating versioned benchmark releases."""

import asyncio
import json
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple

import typer
from rich.console import Console

from src.config import get_config
from src.core.database import GenericDatabase
from src.core.llm import LiteLLMClient
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    Event,
    EventEvidenceVerification,
)
from src.services.dataset_versioning import DatasetVersionService
from src.services.evidence_quality.article_cleaner import (
    CLEANER_PROMPT_VERSION,
    ArticleMarkdownCleaner,
)
from src.services.evidence_quality.event_grounding import (
    EXTRACTOR_PROMPT_VERSION,
    TRACEABILITY_VERSION,
    VERIFIER_PROMPT_VERSION,
    EventEvidenceExtractor,
    EventEvidenceVerifier,
)
from src.services.evidence_quality.llm_client import LiteLLMStructuredClient
from src.services.evidence_quality.service import EvidenceQualityService


app = typer.Typer(help="Create and validate versioned benchmark datasets.")
console = Console()


@app.command("create-v2")
def create_v2(
    source_db: Path = typer.Option(
        Path("combined_new.db"), "--source-db", help="Submitted v1 database"
    ),
    versions_dir: Path = typer.Option(
        Path("data/versions"), "--versions-dir", help="Release directory"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace existing release snapshots"
    ),
) -> None:
    """Freeze v1 and create a v2.0 working copy with identical questions."""
    versioner = DatasetVersionService(versions_dir)
    v1_db = versions_dir / "v1" / "worldreasoner.db"
    if not v1_db.exists() or overwrite:
        v1 = versioner.create_release(
            source_db=source_db,
            version="v1",
            operations=["immutable snapshot of submitted benchmark"],
            overwrite=overwrite,
        )
        console.print(
            f"[green]Created v1:[/green] {v1['counts'].get('questions', 0)} questions"
        )
    v2 = versioner.create_release(
        source_db=v1_db,
        version="v2.0",
        parent_version="v1",
        operations=["initialized v2.0 working release from immutable v1"],
        overwrite=overwrite,
    )
    console.print(
        f"[green]Created v2.0:[/green] {v2['counts'].get('questions', 0)} questions"
    )


@app.command("normalize-articles")
def normalize_articles(
    db_path: Path = typer.Option(
        Path("data/versions/v2_0/worldreasoner.db"), "--db"
    ),
    dataset_version: str = typer.Option("v2.0", "--version"),
    event_linked_only: bool = typer.Option(
        True,
        "--event-linked-only/--all-articles",
        help="Prioritize articles cited by hindsight events",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", min=1),
) -> None:
    """Run deterministic normalization and quality diagnostics."""
    db = GenericDatabase(str(db_path))
    service = EvidenceQualityService(db, dataset_version)
    articles = _select_articles(db, event_linked_only, limit)
    flag_counts: dict[str, int] = {}
    for article in articles:
        record = service.process_article(article)
        for flag in record.flags:
            flag_counts[flag.value] = flag_counts.get(flag.value, 0) + 1
    console.print(
        json.dumps(
            {"processed": len(articles), "flag_counts": flag_counts},
            indent=2,
            sort_keys=True,
        )
    )


@app.command("clean-articles")
def clean_articles(
    db_path: Path = typer.Option(
        Path("data/versions/v2_0/worldreasoner.db"), "--db"
    ),
    dataset_version: str = typer.Option("v2.0", "--version"),
    model: Optional[str] = typer.Option(None, "--model"),
    timeout: int = typer.Option(
        300,
        "--timeout",
        min=1,
        help="Per-request model timeout in seconds",
    ),
    concurrency: int = typer.Option(
        3,
        "--concurrency",
        min=1,
        max=200,
        help="Maximum articles cleaned concurrently",
    ),
    event_linked_only: bool = typer.Option(
        True, "--event-linked-only/--all-articles"
    ),
    limit: int = typer.Option(10, "--limit", min=1),
    force: bool = typer.Option(
        False, "--force", help="Re-clean records that already have Markdown"
    ),
    selection_file: Optional[Path] = typer.Option(
        None,
        "--selection-file",
        help="Process article IDs from a newline-delimited selection file",
    ),
    usage_report: Optional[Path] = typer.Option(
        None,
        "--usage-report",
        help="Write token counts, estimated cost, and timing as JSON",
    ),
    allow_model_content: bool = typer.Option(
        False,
        "--allow-model-content",
        help="Acknowledge that stored article text is sent to the model endpoint",
    ),
) -> None:
    """Produce human-readable Markdown for a bounded article batch."""
    if not allow_model_content:
        raise typer.BadParameter(
            "Pass --allow-model-content after reviewing the configured model endpoint"
        )
    failures = asyncio.run(
        _clean_articles(
            db_path=db_path,
            dataset_version=dataset_version,
            model=model,
            timeout=timeout,
            concurrency=concurrency,
            event_linked_only=event_linked_only,
            limit=limit,
            force=force,
            selection_file=selection_file,
            usage_report=usage_report,
        )
    )
    if failures:
        raise typer.Exit(1)


@app.command("validate-events")
def validate_events(
    db_path: Path = typer.Option(
        Path("data/versions/v2_0/worldreasoner.db"), "--db"
    ),
    dataset_version: str = typer.Option("v2.0", "--version"),
    extractor_model: Optional[str] = typer.Option(None, "--extractor-model"),
    verifier_model: str = typer.Option(
        ..., "--verifier-model", help="Prefer a different model family from pass A"
    ),
    event_id: Optional[str] = typer.Option(
        None, "--event", help="Validate one specific event ID"
    ),
    selection_file: Optional[Path] = typer.Option(
        None,
        "--selection-file",
        help="Validate event::article pairs from a newline-delimited file",
    ),
    all_sources: bool = typer.Option(
        False,
        "--all-sources",
        help="Validate every cited source instead of only the primary source",
    ),
    limit: int = typer.Option(10, "--limit", min=1),
    sampling: str = typer.Option(
        "sequential",
        "--sampling",
        help="Pair selection: sequential or question-stratified",
    ),
    sample_seed: int = typer.Option(
        20261003,
        "--sample-seed",
        help="Reproducible seed for question-stratified sampling",
    ),
    concurrency: int = typer.Option(
        3,
        "--concurrency",
        min=1,
        max=50,
        help="Maximum event-source pairs validated concurrently",
    ),
    usage_report: Optional[Path] = typer.Option(
        None,
        "--usage-report",
        help="Write token counts, estimated cost, outcomes, and timing as JSON",
    ),
    force: bool = typer.Option(
        False, "--force", help="Revalidate pairs with existing v2 decisions"
    ),
    allow_model_content: bool = typer.Option(
        False,
        "--allow-model-content",
        help="Acknowledge that event and article text is sent to model endpoints",
    ),
) -> None:
    """Run exact evidence extraction and independent event verification."""
    if not allow_model_content:
        raise typer.BadParameter(
            "Pass --allow-model-content after reviewing the configured model endpoints"
        )
    failures = asyncio.run(
        _validate_events(
            db_path=db_path,
            dataset_version=dataset_version,
            extractor_model=extractor_model,
            verifier_model=verifier_model,
            event_id=event_id,
            selection_file=selection_file,
            all_sources=all_sources,
            limit=limit,
            sampling=sampling,
            sample_seed=sample_seed,
            concurrency=concurrency,
            usage_report=usage_report,
            force=force,
        )
    )
    if failures:
        raise typer.Exit(1)


async def _clean_articles(
    db_path: Path,
    dataset_version: str,
    model: Optional[str],
    timeout: int,
    concurrency: int,
    event_linked_only: bool,
    limit: int,
    force: bool,
    selection_file: Optional[Path] = None,
    usage_report: Optional[Path] = None,
) -> int:
    db = GenericDatabase(str(db_path))
    config = get_config().llm
    config_updates = {"timeout": timeout}
    if model:
        config_updates["model"] = model
    config = config.model_copy(update=config_updates)
    raw_llm = LiteLLMClient(config)
    llm = LiteLLMStructuredClient(raw_llm)
    service = EvidenceQualityService(
        db,
        dataset_version,
        cleaner=ArticleMarkdownCleaner(
            llm,
            request_concurrency=concurrency,
        ),
    )
    if selection_file:
        selected_ids = [
            line.strip()
            for line in selection_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Selection contains duplicate article IDs")
        articles_by_id = {
            article.id: article
            for article in _select_articles(db, event_linked_only, None)
        }
        missing_ids = [
            article_id
            for article_id in selected_ids
            if article_id not in articles_by_id
        ]
        if missing_ids:
            raise ValueError(
                "Selection contains unknown or out-of-scope article IDs: "
                + ", ".join(missing_ids[:10])
            )
        articles = [articles_by_id[article_id] for article_id in selected_ids]
    else:
        articles = _select_articles(db, event_linked_only, None)
    existing_records = db.get_many(
        ArticleQualityRecord,
        filters={"dataset_version": dataset_version},
    )
    records = {record.article_id: record for record in existing_records}
    for article in articles:
        if article.id not in records:
            records[article.id] = service.ensure_article_record(article)
    if not force:
        articles = [
            article
            for article in articles
            if not records[article.id].cleaner_model
        ]
    eligible_articles: List[Article] = []
    skipped = 0
    for article in articles:
        record = records[article.id]
        if not service.article_is_eligible_for_cleanup(record):
            skipped += 1
            continue
        eligible_articles.append(article)
    articles = eligible_articles
    articles = articles[:limit]
    if skipped:
        console.print(
            f"Skipped {skipped} snapshots blocked by deterministic quality gates."
        )
    if not articles:
        console.print("No articles require cleanup for this selection.")
        return 0
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)
    failure_details: List[Dict[str, str]] = []

    async def clean_one(index: int, article: Article) -> bool:
        async with semaphore:
            try:
                await service.clean_article(article)
                console.print(f"[{index}/{len(articles)}] cleaned {article.id}")
                return True
            except Exception as error:
                if (
                    isinstance(error, RuntimeError)
                    and "returned no usable content" in str(error)
                ):
                    service.record_terminal_cleanup_failure(article, error)
                failure_details.append(
                    {
                        "article_id": article.id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )
                console.print(
                    f"[{index}/{len(articles)}] [red]failed[/red] {article.id}: "
                    f"{type(error).__name__}: {error}"
                )
                return False

    results = await asyncio.gather(
        *(clean_one(index, article) for index, article in enumerate(articles, 1))
    )
    failures = results.count(False)
    usage = raw_llm.get_usage_report()
    elapsed = time.perf_counter() - started
    report = {
        "artifact": "article-cleanup-run-report",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(elapsed, 3),
        "dataset_version": dataset_version,
        "model": llm.model_name,
        "cleaner_prompt_version": CLEANER_PROMPT_VERSION,
        "concurrency": concurrency,
        "execution_mode": "bounded_async",
        "selected_articles": len(articles),
        "succeeded_articles": results.count(True),
        "failed_articles": failures,
        "failure_details": failure_details,
        "throughput_articles_per_minute": round(
            len(articles) * 60 / max(elapsed, 0.001),
            3,
        ),
        "usage": usage,
    }
    if usage_report:
        usage_report.parent.mkdir(parents=True, exist_ok=True)
        usage_report.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        console.print(f"Usage report: {usage_report}")
    console.print(
        "Usage: "
        f"{usage['prompt_tokens']:,} prompt + "
        f"{usage['completion_tokens']:,} completion tokens; "
        f"estimated ${usage['estimated_cost_usd']:.6f}; "
        f"{usage['calls']} calls; {report['wall_seconds']:.1f}s wall time"
    )
    if failures:
        console.print(f"[yellow]Cleanup completed with {failures} failure(s).[/yellow]")
    return failures


async def _validate_events(
    db_path: Path,
    dataset_version: str,
    extractor_model: Optional[str],
    verifier_model: str,
    event_id: Optional[str],
    selection_file: Optional[Path],
    all_sources: bool,
    limit: int,
    sampling: str,
    sample_seed: int,
    concurrency: int,
    usage_report: Optional[Path],
    force: bool,
) -> int:
    db = GenericDatabase(str(db_path))
    base_config = get_config().llm
    extractor_config = base_config.model_copy(
        update={"model": extractor_model or base_config.model}
    )
    verifier_config = base_config.model_copy(update={"model": verifier_model})
    raw_extractor_llm = LiteLLMClient(extractor_config)
    raw_verifier_llm = LiteLLMClient(verifier_config)
    extractor_llm = LiteLLMStructuredClient(raw_extractor_llm)
    verifier_llm = LiteLLMStructuredClient(raw_verifier_llm)
    service = EvidenceQualityService(
        db,
        dataset_version,
        extractor=EventEvidenceExtractor(extractor_llm),
        verifier=EventEvidenceVerifier(verifier_llm),
    )

    pairs = _select_event_article_pairs(
        db,
        event_id=event_id,
        selection_file=selection_file,
        all_sources=all_sources,
    )
    existing_pairs = _current_validation_pairs(
        db.get_many(EventEvidenceVerification),
        dataset_version,
    )
    requested_pairs = len(pairs)
    already_validated_pairs = sum(
        (event.id, article.id) in existing_pairs for event, article in pairs
    )
    if not force:
        pairs = [
            pair for pair in pairs if (pair[0].id, pair[1].id) not in existing_pairs
        ]

    skipped_details: List[Dict[str, str]] = []
    eligible_pairs = []
    for event, article in pairs:
        record = service.ensure_article_record(article)
        if not service.article_is_eligible_for_llm(record):
            skipped_details.append(
                {
                    "event_id": event.id,
                    "article_id": article.id,
                    "reason": "deterministic_article_gate",
                }
            )
            continue
        eligible_pairs.append((event, article))
    pairs = _sample_validation_pairs(
        eligible_pairs,
        limit=limit,
        sampling=sampling,
        seed=sample_seed,
    )
    if skipped_details:
        console.print(
            f"Skipped {len(skipped_details)} pairs blocked by deterministic gates."
        )
    if not pairs:
        console.print("No event-source pairs require validation for this selection.")
        return 0

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)
    failure_details: List[Dict[str, str]] = []
    action_counts: Dict[str, int] = {}

    async def validate_one(index: int, event: Event, article: Article) -> bool:
        async with semaphore:
            try:
                _, verification = await service.validate_event(event, article)
                action = verification.action.value
                action_counts[action] = action_counts.get(action, 0) + 1
                console.print(
                    f"[{index}/{len(pairs)}] {event.id}::{article.id}: {action}"
                )
                return True
            except Exception as error:
                failure_details.append(
                    {
                        "event_id": event.id,
                        "article_id": article.id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )
                console.print(
                    f"[{index}/{len(pairs)}] [red]failed[/red] "
                    f"{event.id}::{article.id}: {type(error).__name__}: {error}"
                )
                return False

    results = await asyncio.gather(
        *(
            validate_one(index, event, article)
            for index, (event, article) in enumerate(pairs, 1)
        )
    )
    failures = results.count(False)
    extractor_usage = raw_extractor_llm.get_usage_report()
    verifier_usage = raw_verifier_llm.get_usage_report()
    elapsed = time.perf_counter() - started
    report = {
        "artifact": "event-validation-run-report",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(elapsed, 3),
        "dataset_version": dataset_version,
        "extractor_model": extractor_llm.model_name,
        "verifier_model": verifier_llm.model_name,
        "extractor_prompt_version": EXTRACTOR_PROMPT_VERSION,
        "verifier_prompt_version": VERIFIER_PROMPT_VERSION,
        "sampling": sampling,
        "sample_seed": sample_seed,
        "concurrency": concurrency,
        "execution_mode": "bounded_async",
        "requested_pairs": requested_pairs,
        "already_validated_pairs": already_validated_pairs,
        "selected_pairs": len(pairs),
        "succeeded_pairs": results.count(True),
        "failed_pairs": failures,
        "skipped_pairs": len(skipped_details),
        "action_counts": action_counts,
        "failure_details": failure_details,
        "skipped_details": skipped_details,
        "extractor_usage": extractor_usage,
        "verifier_usage": verifier_usage,
        "estimated_cost_usd": round(
            extractor_usage["estimated_cost_usd"]
            + verifier_usage["estimated_cost_usd"],
            6,
        ),
    }
    if usage_report:
        usage_report.parent.mkdir(parents=True, exist_ok=True)
        usage_report.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        console.print(f"Usage report: {usage_report}")
    console.print(
        "Usage: "
        f"{extractor_usage['prompt_tokens'] + verifier_usage['prompt_tokens']:,} "
        "prompt + "
        f"{extractor_usage['completion_tokens'] + verifier_usage['completion_tokens']:,} "
        f"completion tokens; estimated ${report['estimated_cost_usd']:.6f}; "
        f"{report['wall_seconds']:.1f}s wall time"
    )
    if failures:
        console.print(
            f"[yellow]Validation completed with {failures} failure(s).[/yellow]"
        )
    return failures


def _current_validation_pairs(
    records: List[EventEvidenceVerification],
    dataset_version: str,
) -> Set[Tuple[str, str]]:
    """Return pairs decided by the current verifier or traceability gate."""
    current_prompt_versions = {VERIFIER_PROMPT_VERSION, TRACEABILITY_VERSION}
    return {
        (record.event_id, record.article_id)
        for record in records
        if record.dataset_version == dataset_version
        and record.prompt_version in current_prompt_versions
    }


def _sample_validation_pairs(
    pairs: List[Tuple[Event, Article]],
    limit: int,
    sampling: str,
    seed: int,
) -> List[Tuple[Event, Article]]:
    """Select validation pairs reproducibly, balancing domains and questions."""
    if sampling == "sequential":
        return pairs[:limit]
    if sampling != "question-stratified":
        raise ValueError(
            "Unknown sampling mode "
            f"{sampling!r}; expected 'sequential' or 'question-stratified'"
        )

    rng = random.Random(seed)
    grouped: Dict[str, Dict[str, List[Tuple[Event, Article]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for event, article in pairs:
        domain = (
            event.domain.value
            if hasattr(event.domain, "value")
            else str(event.domain)
        )
        question = event.extracted_for_question_id or event.id
        grouped[domain][question].append((event, article))

    domain_queues: Dict[str, Deque[Deque[Tuple[Event, Article]]]] = {}
    for domain, question_groups in grouped.items():
        queues: List[Deque[Tuple[Event, Article]]] = []
        for group_pairs in question_groups.values():
            rng.shuffle(group_pairs)
            queues.append(deque(group_pairs))
        rng.shuffle(queues)
        domain_queues[domain] = deque(queues)

    domains = sorted(domain_queues)
    rng.shuffle(domains)
    selected: List[Tuple[Event, Article]] = []
    target = min(limit, len(pairs))
    while len(selected) < target:
        added = False
        for domain in domains:
            groups = domain_queues[domain]
            if not groups or len(selected) >= target:
                continue
            group = groups.popleft()
            selected.append(group.popleft())
            if group:
                groups.append(group)
            added = True
        if not added:
            break
    return selected


def _select_event_article_pairs(
    db: GenericDatabase,
    event_id: Optional[str],
    selection_file: Optional[Path],
    all_sources: bool,
) -> List[tuple[Event, Article]]:
    if event_id and selection_file:
        raise ValueError("Use either --event or --selection-file, not both")

    if selection_file:
        pair_ids = [
            line.strip()
            for line in selection_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Selection contains duplicate event-source pairs")
        pairs = []
        for pair_id in pair_ids:
            if "::" not in pair_id:
                raise ValueError(
                    f"Invalid pair {pair_id!r}; expected event_id::article_id"
                )
            selected_event_id, article_id = pair_id.split("::", 1)
            event = db.get(Event, selected_event_id)
            article = db.get(Article, article_id)
            if event is None or article is None:
                raise ValueError(f"Unknown event-source pair: {pair_id}")
            if article_id not in set(_event_article_ids(event)):
                raise ValueError(f"Article is not cited by event: {pair_id}")
            pairs.append((event, article))
        return pairs

    events = [db.get(Event, event_id)] if event_id else db.get_many(Event)
    pairs = []
    for event in events:
        if event is None or event.is_outcome:
            continue
        articles = [
            article
            for article_id in _event_article_ids(event)
            if (article := db.get(Article, article_id)) is not None
        ]
        if all_sources:
            pairs.extend((event, article) for article in articles)
        elif articles:
            pairs.append((event, articles[0]))
    return pairs


def _event_article_ids(event: Event) -> List[str]:
    seen: Set[str] = set()
    article_ids = []
    for article_id in [event.source_article_id, *event.article_ids]:
        if article_id and article_id not in seen:
            seen.add(article_id)
            article_ids.append(article_id)
    return article_ids


def _select_articles(
    db: GenericDatabase,
    event_linked_only: bool,
    limit: Optional[int],
) -> List[Article]:
    article_ids: Optional[Set[str]] = None
    if event_linked_only:
        article_ids = set()
        for event in db.get_many(Event):
            if event.source_article_id:
                article_ids.add(event.source_article_id)
            article_ids.update(event.article_ids)

    articles = db.get_many(Article)
    if article_ids is not None:
        articles = [article for article in articles if article.id in article_ids]
    articles.sort(key=lambda article: article.id)
    return articles[:limit] if limit is not None else articles
