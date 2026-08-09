"""Commands for creating and validating versioned benchmark releases."""

import asyncio
import json
from pathlib import Path
from typing import List, Optional, Set

import typer
from rich.console import Console

from src.config import get_config
from src.core.database import GenericDatabase
from src.core.llm import LiteLLMClient
from src.domain.models import Article, Event, EventEvidenceVerification
from src.services.dataset_versioning import DatasetVersionService
from src.services.evidence_quality.article_cleaner import ArticleMarkdownCleaner
from src.services.evidence_quality.event_grounding import (
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
    event_linked_only: bool = typer.Option(
        True, "--event-linked-only/--all-articles"
    ),
    limit: int = typer.Option(10, "--limit", min=1),
    force: bool = typer.Option(
        False, "--force", help="Re-clean records that already have Markdown"
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
            event_linked_only=event_linked_only,
            limit=limit,
            force=force,
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
    limit: int = typer.Option(10, "--limit", min=1),
    force: bool = typer.Option(
        False, "--force", help="Revalidate events with existing v2 decisions"
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
            limit=limit,
            force=force,
        )
    )
    if failures:
        raise typer.Exit(1)


async def _clean_articles(
    db_path: Path,
    dataset_version: str,
    model: Optional[str],
    event_linked_only: bool,
    limit: int,
    force: bool,
) -> int:
    db = GenericDatabase(str(db_path))
    config = get_config().llm
    if model:
        config = config.model_copy(update={"model": model})
    llm = LiteLLMStructuredClient(LiteLLMClient(config))
    service = EvidenceQualityService(
        db,
        dataset_version,
        cleaner=ArticleMarkdownCleaner(llm),
    )
    articles = _select_articles(db, event_linked_only, None)
    if not force:
        articles = [
            article
            for article in articles
            if not (
                (record := service.get_article_record(article.id))
                and record.clean_markdown
            )
        ]
    articles = articles[:limit]
    if not articles:
        console.print("No articles require cleanup for this selection.")
        return 0
    failures = 0
    for index, article in enumerate(articles, 1):
        try:
            await service.clean_article(article)
            console.print(f"[{index}/{len(articles)}] cleaned {article.id}")
        except Exception as error:
            failures += 1
            console.print(
                f"[{index}/{len(articles)}] [red]failed[/red] {article.id}: "
                f"{type(error).__name__}: {error}"
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
    limit: int,
    force: bool,
) -> int:
    db = GenericDatabase(str(db_path))
    base_config = get_config().llm
    extractor_config = base_config.model_copy(
        update={"model": extractor_model or base_config.model}
    )
    verifier_config = base_config.model_copy(update={"model": verifier_model})
    extractor_llm = LiteLLMStructuredClient(LiteLLMClient(extractor_config))
    verifier_llm = LiteLLMStructuredClient(LiteLLMClient(verifier_config))
    service = EvidenceQualityService(
        db,
        dataset_version,
        extractor=EventEvidenceExtractor(extractor_llm),
        verifier=EventEvidenceVerifier(verifier_llm),
    )

    processed = 0
    failures = 0
    events = [db.get(Event, event_id)] if event_id else db.get_many(Event)
    events = [event for event in events if event is not None]
    existing_event_ids = {
        record.event_id
        for record in db.get_many(EventEvidenceVerification)
        if record.dataset_version == dataset_version
    }
    for event in events:
        if event.is_outcome:
            continue
        if not force and event.id in existing_event_ids:
            continue
        article = _event_article(db, event)
        if article is None:
            continue
        processed += 1
        try:
            _, verification = await service.validate_event(event, article)
            console.print(
                f"[{processed}/{limit}] {event.id}: {verification.action.value}"
            )
        except Exception as error:
            failures += 1
            console.print(
                f"[{processed}/{limit}] [red]failed[/red] {event.id}: "
                f"{type(error).__name__}: {error}"
            )
        if processed >= limit:
            break
    if processed == 0:
        console.print("No events require validation for this selection.")
    if failures:
        console.print(
            f"[yellow]Validation completed with {failures} failure(s).[/yellow]"
        )
    return failures


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


def _event_article(db: GenericDatabase, event: Event) -> Optional[Article]:
    candidates = [event.source_article_id] + list(event.article_ids)
    for article_id in candidates:
        if not article_id:
            continue
        article = db.get(Article, article_id)
        if article:
            return article
    return None
