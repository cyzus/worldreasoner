"""Evidence pipeline commands for WorldReasoner CLI.

Provides commands to run and manage the evidence collection pipeline,
including interactive question selection and progress tracking.
"""

import asyncio
import random
from datetime import datetime, timezone
from typing import List, Optional
import typer
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt

from src.core.database import GenericDatabase
from src.cli.core.options import (
    db_option,
    source_option,
    domain_option,
    limit_option,
    sample_option,
    seed_option,
    yes_option,
    get_db_and_manager,
)
from src.cli.core.question_selector import QuestionSelector
from src.cli.core.pipeline_runner import PipelineRunner, PipelineType, PipelineProgress
from src.config.pipeline import SATISFACTION_DEFAULTS
from src.domain.models import Question, Event, Article, ReviewStatus
from src.services.event_review_service import EventReviewService, EventReviewReport
from src.config.settings import get_config
from src.utils.logging import logger

app = typer.Typer(help="Evidence pipeline commands")
console = Console()


@app.command()
def run(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) to process (can be repeated)",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Interactively select questions",
    ),
    source: Optional[str] = source_option(),
    domain: Optional[str] = domain_option(),
    resolved_only: bool = typer.Option(
        False,
        "--resolved",
        help="Only process resolved questions",
    ),
    has_evidence: bool = typer.Option(
        False,
        "--has-evidence",
        help="Only process questions with existing evidence",
    ),
    limit: int = limit_option(),
    force_reprocess: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force reprocessing even if evidence exists",
    ),
    adaptive: bool = typer.Option(
        False,
        "--adaptive",
        "-a",
        help="Use adaptive multi-agent evidence pipeline for deep analysis",
    ),
    agent_max_steps: int = typer.Option(
        30,
        "--max-steps",
        help="Maximum agent steps for adaptive pipeline",
    ),
    min_graph_depth: int = typer.Option(
        3,
        "--min-depth",
        help="Minimum graph depth for adaptive pipeline",
    ),
    skip_indexing: bool = typer.Option(
        False,
        "--skip-indexing",
        help="Skip automatic search indexing after completion",
    ),
    db_path: str = db_option(),
    sample: Optional[int] = sample_option(),
    seed: Optional[int] = seed_option(),
):
    """Run evidence pipeline on selected questions.

    Examples:
        # Interactively select questions from polymarket
        wr evidence run --interactive --source polymarket

        # Process specific questions
        wr evidence run -q q_abc123 -q q_def456

        # Process all resolved politics questions
        wr evidence run --source polymarket --domain politics --resolved

        # Process questions with interactive filtering
        wr evidence run -i --domain politics --limit 20

        # Use adaptive multi-agent pipeline for deep analysis
        wr evidence run -q q_abc123 --adaptive

        # Adaptive pipeline with custom parameters
        wr evidence run -q q_abc123 --adaptive --max-steps 50 --min-depth 5

        # Process a random sample of 10 questions
        wr evidence run --db experiment.db --resolved --sample 10
    """
    db = GenericDatabase(db_path)
    selector = QuestionSelector(db_path)

    # Determine which questions to process
    if question_ids:
        # Use provided question IDs
        questions_to_process = []
        for qid in question_ids:
            q = db.get(Question, qid)
            if q:
                questions_to_process.append(q)
            else:
                console.print(f"[yellow]Warning: Question not found: {qid}[/yellow]")

        if not questions_to_process:
            console.print("[red]No valid questions provided[/red]")
            raise typer.Exit(1)

    elif interactive:
        # Interactive selection
        console.print("[bold cyan]Select questions for evidence pipeline[/bold cyan]")
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence if not has_evidence else None,
            limit=limit,
            multi_select=True,
        )

        if not questions_to_process:
            console.print("[yellow]No questions selected[/yellow]")
            raise typer.Exit(0)

    else:
        # Non-interactive selection with filters
        # When --sample is used, fetch all matching questions first so
        # stratified sampling has the full pool to draw from
        effective_limit = limit if sample is None else 10000
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence if not has_evidence else None,
            limit=effective_limit,
            multi_select=True,
        )

        if not questions_to_process:
            console.print("[yellow]No questions match the filters[/yellow]")
            raise typer.Exit(0)

    # Random sampling of questions (stratified by domain for balance)
    if sample is not None and not question_ids:
        total_available = len(questions_to_process)
        if sample < total_available:
            questions_to_process = _stratified_sample(
                questions_to_process, sample, seed
            )
            # Show domain breakdown
            from collections import Counter

            domain_counts = Counter(
                q.domain.value if hasattr(q.domain, "value") else q.domain
                for q in questions_to_process
            )
            breakdown = ", ".join(f"{d}={c}" for d, c in sorted(domain_counts.items()))
            console.print(
                f"[bold]Stratified sample: {len(questions_to_process)} of {total_available} questions"
                + (f" (seed={seed})" if seed is not None else "")
                + f"[/bold]\n  [dim]{breakdown}[/dim]"
            )
        else:
            console.print(
                f"[dim]Sample size {sample} >= available {total_available}, using all[/dim]"
            )

    # Confirm before running
    console.print(
        f"\n[bold]Will process {len(questions_to_process)} question(s)[/bold]"
    )
    if adaptive:
        console.print("[bold cyan]Mode:[/bold cyan] Adaptive multi-agent pipeline")
        console.print(f"  Max agent steps: {agent_max_steps}")
        console.print(f"  Min graph depth: {min_graph_depth}")
    else:
        console.print("[bold cyan]Mode:[/bold cyan] Standard evidence pipeline")

    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    # Run evidence pipeline
    pipeline_name = "adaptive evidence" if adaptive else "evidence"
    console.print(f"\n[bold cyan]Starting {pipeline_name} pipeline...[/bold cyan]")

    try:
        # Use PipelineRunner to execute the pipeline
        result = asyncio.run(
            _run_evidence_pipeline_async(
                questions_to_process,
                db_path,
                force_reprocess,
                adaptive,
                agent_max_steps,
                min_graph_depth,
                skip_indexing,
            )
        )

        # Display results
        _display_pipeline_results(result)

        if result.failure_count > 0:
            raise typer.Exit(1)

    except Exception as e:
        logger.error(f"Evidence pipeline failed: {e}")
        console.print(f"\n[red]Evidence pipeline failed: {e}[/red]")
        raise typer.Exit(1)


async def _run_evidence_pipeline_async(
    questions: List[Question],
    db_path: str,
    force_reprocess: bool = False,
    adaptive: bool = False,
    agent_max_steps: int = 30,
    min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
    skip_indexing: bool = False,
):
    """Execute the evidence pipeline on selected questions using PipelineRunner."""
    runner = PipelineRunner(db_path=db_path)
    question_ids = [q.id for q in questions]

    # Select pipeline type based on adaptive flag
    pipeline_type = (
        PipelineType.ADAPTIVE_EVIDENCE if adaptive else PipelineType.EVIDENCE
    )

    # Create progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Processing questions...",
            total=len(questions),
        )

        def on_progress(p: PipelineProgress):
            progress.update(
                task,
                completed=p.current,
                description=f"[cyan]{p.stage}: {p.message}",
            )

        # Build kwargs for pipeline execution
        pipeline_kwargs = {"on_progress": on_progress}

        if adaptive:
            # Adaptive pipeline parameters
            pipeline_kwargs.update(
                {
                    "agent_max_steps": agent_max_steps,
                    "min_graph_depth": min_graph_depth,
                    "skip_indexing": skip_indexing,
                }
            )
        else:
            # Standard pipeline parameters
            pipeline_kwargs["force_reprocess"] = force_reprocess
            pipeline_kwargs["skip_indexing"] = skip_indexing

        # Run pipeline with progress callback
        result = await runner.run(
            pipeline_type,
            question_ids=question_ids,
            **pipeline_kwargs,
        )

    return result


def _display_pipeline_results(result):
    """Display formatted pipeline results."""
    console.print("\n[bold]Pipeline Results:[/bold]")
    console.print(f"  Duration: {result.duration_seconds:.1f}s")
    console.print(f"  [green]Succeeded: {result.success_count}[/green]")
    console.print(f"  [yellow]Skipped: {result.skip_count}[/yellow]")
    console.print(f"  [red]Failed: {result.failure_count}[/red]")

    if result.processed:
        console.print("\n[bold green]Successfully Processed:[/bold green]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Question ID")
        table.add_column("Articles", justify="right")

        for item in result.processed:
            table.add_row(
                item["id"],
                str(item.get("articles", 0)),
            )
        console.print(table)

    if result.skipped:
        console.print("\n[bold yellow]Skipped:[/bold yellow]")
        for item in result.skipped:
            console.print(f"  {item['id']}: {item.get('reason', 'Unknown')}")

    if result.failed:
        console.print("\n[bold red]Failed:[/bold red]")
        for item in result.failed:
            console.print(f"  {item['id']}: {item.get('error', 'Unknown error')}")


@app.command()
def clear(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Question ID(s) to clear evidence for (can be repeated)",
    ),
    all_questions: bool = typer.Option(
        False,
        "--all",
        help="Clear evidence for ALL questions in the database",
    ),
    cascade: bool = typer.Option(
        True,
        "--cascade",
        help="Also delete orphaned events and articles",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without making changes",
    ),
    db_path: str = db_option(),
):
    """Clear evidence data for questions.

    Removes causal hypotheses and optionally cascades to orphaned events/articles.
    The questions themselves are kept - only evidence data is removed.

    Examples:
        wr evidence clear -q q_abc123
        wr evidence clear -q q_1 -q q_2 -q q_3 --cascade
        wr evidence clear -q q_abc123 --dry-run
        wr evidence clear --all --db experiment.db
    """
    db, manager = get_db_and_manager(db_path)

    if all_questions:
        all_qs = db.get_many(Question)
        question_ids = [q.id for q in all_qs]
        if not question_ids:
            console.print("[yellow]No questions found in database[/yellow]")
            raise typer.Exit(0)
        console.print(
            f"[yellow]About to clear evidence for ALL {len(question_ids)} questions[/yellow]"
        )

    if not question_ids:
        console.print("[red]Please provide --question/-q or --all[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Clear evidence for {len(question_ids)} question(s)[/bold]")
    console.print(f"  Cascade: {cascade}")
    console.print(f"  Dry run: {dry_run}")

    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    console.print("[cyan]Clearing evidence...[/cyan]\n")

    total_stats = {
        "articles": 0,
        "events": 0,
        "hypotheses_delete": 0,
        "hypotheses_update": 0,
    }

    failed = []

    for question_id in question_ids:
        result = manager.clear_evidence(question_id, cascade=cascade, dry_run=dry_run)

        if "error" in result:
            console.print(
                f"[red]Error processing {question_id}: {result['error']}[/red]"
            )
            failed.append({"id": question_id, "error": result["error"]})
            continue

        if dry_run:
            summary = result["summary"]
            console.print(f"[yellow][DRY RUN] {question_id}:[/yellow]")
            console.print(f"  Articles: {summary['articles']}")
            console.print(f"  Events: {summary['events']}")
            console.print(f"  Hypotheses to delete: {summary['hypotheses_delete']}")
            console.print(f"  Hypotheses to update: {summary['hypotheses_update']}")

            for key in total_stats:
                total_stats[key] += summary.get(key, 0)
        else:
            summary = result["summary"]
            console.print(f"[green]Cleared {question_id}[/green]")
            console.print(f"  Articles: {summary['articles']}")
            console.print(f"  Events: {summary['events']}")
            console.print(f"  Hypotheses deleted: {summary['hypotheses_delete']}")
            console.print(f"  Hypotheses updated: {summary['hypotheses_update']}")

            for key in total_stats:
                total_stats[key] += summary.get(key, 0)

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Articles cleared: {total_stats['articles']}")
    console.print(f"  Events cleared: {total_stats['events']}")
    console.print(f"  Hypotheses deleted: {total_stats['hypotheses_delete']}")
    console.print(f"  Hypotheses updated: {total_stats['hypotheses_update']}")

    if failed:
        console.print(f"\n[red]Failed to clear {len(failed)} question(s)[/red]")
        for item in failed:
            console.print(f"  {item['id']}: {item['error']}")
        raise typer.Exit(1)

    if dry_run:
        console.print("\n[yellow]Dry run completed - no changes made[/yellow]")
    else:
        console.print("\n[green]Evidence cleared successfully[/green]")


# =============================================================================
# Event Review Command
# =============================================================================

REVIEW_STATUS_STYLES = {
    "pending": "yellow",
    "approved": "green",
    "rejected": "red",
    "revised": "blue",
}


def _review_status_label(status: str) -> str:
    """Format review status with color."""
    style = REVIEW_STATUS_STYLES.get(status, "white")
    return f"[{style}]{status.upper()}[/{style}]"


def _display_event_for_review(
    event: Event, db: GenericDatabase, idx: int, total: int
) -> None:
    """Display a single event with full context for review."""
    # Header
    console.print(
        Panel(
            f"[bold cyan]{event.title}[/bold cyan]",
            title=f"Event {idx}/{total} — {event.id}",
            subtitle=_review_status_label(
                event.review_status.value
                if hasattr(event.review_status, "value")
                else event.review_status
            ),
        )
    )

    # Event details
    domain_val = event.domain.value if hasattr(event.domain, "value") else event.domain
    status_val = event.status.value if hasattr(event.status, "value") else event.status
    etype_val = (
        event.event_type.value
        if hasattr(event.event_type, "value")
        else event.event_type
    )

    console.print(f"  [bold]Domain:[/bold]      {domain_val}")
    console.print(f"  [bold]Type:[/bold]        {etype_val}")
    console.print(f"  [bold]Status:[/bold]      {status_val}")

    # Date info (critical for review)
    if event.occurred_date:
        console.print(
            f"  [bold]Occurred:[/bold]    {event.occurred_date.strftime('%Y-%m-%d %H:%M UTC')}"
        )
    if event.predicted_date:
        console.print(
            f"  [bold]Predicted:[/bold]   {event.predicted_date.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    console.print(f"\n  [bold]Description:[/bold]\n  {event.description}")

    # Show source articles with dates for cross-referencing
    if event.article_ids:
        console.print(f"\n  [bold]Source Articles ({len(event.article_ids)}):[/bold]")
        for aid in event.article_ids:
            article = db.get(Article, aid)
            if article:
                pub_date = (
                    article.published_date.strftime("%Y-%m-%d")
                    if article.published_date
                    else "unknown date"
                )
                title = (
                    article.title[:80] + "..."
                    if len(article.title) > 80
                    else article.title
                )
                console.print(f"    [{pub_date}] {title}")
                if article.url:
                    console.print(f"    [dim underline]{article.url}[/dim underline]")
                console.print(f"    [dim]{aid}[/dim]")
            else:
                console.print(f"    [red]{aid} (not found in DB)[/red]")

    if event.review_note:
        console.print(f"\n  [bold]Previous Note:[/bold] {event.review_note}")

    console.print()


@app.command()
def review(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Review events for specific question(s)",
    ),
    status_filter: Optional[str] = typer.Option(
        "pending",
        "--status",
        "-s",
        help="Filter by review status: pending, approved, rejected, revised, all",
    ),
    db_path: str = db_option(),
    summary_only: bool = typer.Option(
        False,
        "--summary",
        help="Show review status summary without interactive review",
    ),
    auto_approve_outcomes: bool = typer.Option(
        True,
        "--auto-approve-outcomes",
        help="Auto-approve outcome events (pre-generated Yes/No events)",
    ),
    sample: Optional[int] = sample_option(),
    seed: Optional[int] = seed_option(),
):
    """Interactively review agent-generated events for accuracy.

    Walk through each event, see its details and source articles,
    then approve, reject, or skip. Rejected events are excluded from
    forecasting pipelines.

    Examples:
        wr evidence review --db experiment.db
        wr evidence review -q q_abc123 --db experiment.db
        wr evidence review --status all --summary --db experiment.db
    """
    db = GenericDatabase(db_path)

    # Build filters
    filters = {}
    if status_filter and status_filter != "all":
        filters["review_status"] = status_filter

    # Get events to review
    if question_ids:
        events = []
        for qid in question_ids:
            q_events = db.get_many(Event, filters={"extracted_for_question_id": qid})
            events.extend(q_events)
        # Apply status filter manually since we merged across questions
        if status_filter and status_filter != "all":
            events = [
                e
                for e in events
                if (
                    e.review_status.value
                    if hasattr(e.review_status, "value")
                    else e.review_status
                )
                == status_filter
            ]
    else:
        events = db.get_many(Event, filters=filters if filters else None)

    if not events:
        console.print("[yellow]No events found matching criteria.[/yellow]")
        raise typer.Exit(0)

    # Summary mode
    if summary_only:
        _show_review_summary(events, db)
        raise typer.Exit(0)

    # Auto-approve outcome events if requested
    auto_approved = 0
    if auto_approve_outcomes:
        for event in events:
            if event.is_outcome and (
                (
                    event.review_status.value
                    if hasattr(event.review_status, "value")
                    else event.review_status
                )
                == "pending"
            ):
                event.review_status = ReviewStatus.APPROVED
                event.review_note = "Auto-approved (outcome event)"
                event.updated_at = datetime.now(timezone.utc)
                db.save(Event, event)
                auto_approved += 1

        if auto_approved:
            console.print(
                f"[green]Auto-approved {auto_approved} outcome events[/green]\n"
            )
            # Re-filter to exclude auto-approved
            events = [
                e
                for e in events
                if not (
                    e.is_outcome
                    and (
                        e.review_status.value
                        if hasattr(e.review_status, "value")
                        else e.review_status
                    )
                    == "approved"
                    and e.review_note == "Auto-approved (outcome event)"
                )
            ]

    # Filter to only pending for interactive review (unless --status was explicit)
    review_events = [
        e
        for e in events
        if (
            e.review_status.value
            if hasattr(e.review_status, "value")
            else e.review_status
        )
        == "pending"
        or (status_filter and status_filter != "pending")
    ]

    if not review_events:
        console.print("[green]All events have been reviewed![/green]")
        raise typer.Exit(0)

    # Random sampling - always shuffle so each run shows different order
    rng = random.Random(seed)
    rng.shuffle(review_events)

    total_pending = len(review_events)
    if sample is not None and sample < len(review_events):
        review_events = review_events[:sample]

    if sample is not None:
        console.print(
            f"[bold]Batch: {len(review_events)} of {total_pending} pending events"
            + (f" (seed={seed})" if seed is not None else "")
            + "[/bold]"
        )

    console.print(
        f"[bold]Reviewing {len(review_events)} events[/bold] "
        f"([dim]a[/dim]=approve, [dim]r[/dim]=reject, [dim]s[/dim]=skip, [dim]q[/dim]=quit)\n"
    )

    reviewed = {"approved": 0, "rejected": 0, "skipped": 0}

    for idx, event in enumerate(review_events, 1):
        _display_event_for_review(event, db, idx, len(review_events))

        while True:
            choice = Prompt.ask(
                "[bold]Action[/bold]",
                choices=["a", "r", "s", "q"],
                default="s",
            )

            if choice == "a":
                event.review_status = ReviewStatus.APPROVED
                event.updated_at = datetime.now(timezone.utc)
                note = Prompt.ask("[dim]Note (optional)[/dim]", default="")
                if note:
                    event.review_note = note
                db.save(Event, event)
                console.print("[green]APPROVED[/green]\n")
                reviewed["approved"] += 1
                break

            elif choice == "r":
                note = Prompt.ask(
                    "[dim]Rejection reason[/dim]",
                    default="Inaccurate event or date",
                )
                event.review_status = ReviewStatus.REJECTED
                event.review_note = note
                event.updated_at = datetime.now(timezone.utc)
                db.save(Event, event)
                console.print("[red]REJECTED[/red]\n")
                reviewed["rejected"] += 1
                break

            elif choice == "s":
                reviewed["skipped"] += 1
                console.print("[yellow]SKIPPED[/yellow]\n")
                break

            elif choice == "q":
                console.print("\n[bold]Review session ended.[/bold]")
                _print_review_stats(reviewed)
                raise typer.Exit(0)

    console.print("\n[bold]Review complete![/bold]")
    _print_review_stats(reviewed)


def _show_review_summary(events: List[Event], db: GenericDatabase) -> None:
    """Show summary table of review statuses grouped by question."""
    # Group by question ID
    by_question: dict = {}
    for event in events:
        qid = event.extracted_for_question_id or "(no question)"
        if qid not in by_question:
            by_question[qid] = {
                "pending": 0,
                "approved": 0,
                "rejected": 0,
                "revised": 0,
                "total": 0,
            }
        status_val = (
            event.review_status.value
            if hasattr(event.review_status, "value")
            else event.review_status
        )
        by_question[qid][status_val] = by_question[qid].get(status_val, 0) + 1
        by_question[qid]["total"] += 1

    table = Table(title="Event Review Summary")
    table.add_column("Question ID", style="cyan", no_wrap=True)
    table.add_column("Total", justify="right")
    table.add_column("Pending", justify="right", style="yellow")
    table.add_column("Approved", justify="right", style="green")
    table.add_column("Rejected", justify="right", style="red")
    table.add_column("Revised", justify="right", style="blue")

    total_row = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "revised": 0}
    for qid, counts in sorted(by_question.items()):
        table.add_row(
            qid,
            str(counts["total"]),
            str(counts["pending"]),
            str(counts["approved"]),
            str(counts["rejected"]),
            str(counts["revised"]),
        )
        for k in total_row:
            total_row[k] += counts[k]

    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_row['total']}[/bold]",
        f"[bold]{total_row['pending']}[/bold]",
        f"[bold]{total_row['approved']}[/bold]",
        f"[bold]{total_row['rejected']}[/bold]",
        f"[bold]{total_row['revised']}[/bold]",
    )
    console.print(table)


def _print_review_stats(reviewed: dict) -> None:
    """Print session statistics with approval rate."""
    total_decided = reviewed["approved"] + reviewed["rejected"]
    console.print(f"  [green]Approved:[/green] {reviewed['approved']}")
    console.print(f"  [red]Rejected:[/red] {reviewed['rejected']}")
    console.print(f"  [yellow]Skipped:[/yellow] {reviewed['skipped']}")
    if total_decided > 0:
        rate = reviewed["approved"] / total_decided * 100
        style = "green" if rate >= 70 else "yellow" if rate >= 40 else "red"
        console.print(
            f"\n  [{style}]Approval rate: {rate:.0f}% ({reviewed['approved']}/{total_decided})[/{style}]"
        )


def _stratified_sample(
    questions: List[Question], n: int, seed: Optional[int] = None
) -> List[Question]:
    """Sample N questions with balanced domain representation.

    Distributes the sample evenly across domains, then fills remaining
    slots from domains with more available questions.

    Args:
        questions: Full list of questions to sample from
        n: Target sample size
        seed: Optional random seed for reproducibility

    Returns:
        Stratified sample of questions
    """
    from collections import defaultdict

    rng = random.Random(seed)

    # Group by domain
    by_domain: dict = defaultdict(list)
    for q in questions:
        domain_val = q.domain.value if hasattr(q.domain, "value") else q.domain
        by_domain[domain_val].append(q)

    # Shuffle within each domain
    for domain_questions in by_domain.values():
        rng.shuffle(domain_questions)

    domains = sorted(by_domain.keys())
    num_domains = len(domains)

    if num_domains == 0:
        return []

    # Round-robin: take per_domain from each, then fill remainder
    per_domain = n // num_domains
    result = []
    overflow = []

    for d in domains:
        pool = by_domain[d]
        take = min(per_domain, len(pool))
        result.extend(pool[:take])
        overflow.extend(pool[take:])

    # Fill remaining slots from overflow (shuffled)
    remaining = n - len(result)
    if remaining > 0:
        rng.shuffle(overflow)
        result.extend(overflow[:remaining])

    # Final shuffle so domains aren't grouped together
    rng.shuffle(result)
    return result


@app.command()
def auto_review(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) to auto-review events for",
    ),
    db_path: str = db_option(),
    sample: Optional[int] = sample_option(),
    seed: Optional[int] = seed_option(),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use for review (default: gemini-2.5-flash)",
    ),
    min_events: int = typer.Option(
        10,
        "--min-events",
        help="Minimum number of events required for criteria",
    ),
    min_depth: int = typer.Option(
        1,
        "--min-depth",
        help="Minimum causal depth required for criteria",
    ),
    skip_criteria: bool = typer.Option(
        False,
        "--skip-criteria",
        help="Skip criteria filtering (review all questions regardless of criteria)",
    ),
    yes: bool = yes_option(),
):
    """Automatically review agent-generated events using LLM.

    This command uses an LLM to verify event accuracy, temporal validity,
    and relevance. Events are approved or rejected based on LLM judgment.

    By default, only questions that meet criteria are reviewed:
    - At least 10 approved events
    - At least 3 causal depth
    - Time coverage (multiple event dates)

    Use --skip-criteria to review all questions regardless of criteria.

    Examples:
        # Auto-review questions meeting criteria (default)
        wr evidence auto-review --db experiment.db

        # Auto-review ALL questions (skip criteria filter)
        wr evidence auto-review --skip-criteria --db experiment.db

        # Auto-review specific question
        wr evidence auto-review -q q_abc123 --db experiment.db

        # Custom criteria
        wr evidence auto-review --min-events 15 --min-depth 4
    """
    db = GenericDatabase(db_path)

    llm_config = get_config().llm
    if model:
        llm_config = llm_config.model_copy(update={"review_model": model})

    service = EventReviewService(db, llm_config=llm_config)
    service.criteria.min_events = min_events
    service.criteria.min_depth = min_depth

    if question_ids:
        if not yes:
            console.print(
                f"[yellow]About to auto-review events for {len(question_ids)} question(s).[/yellow]"
            )
            confirm = Prompt.ask("Continue?", choices=["y", "n"], default="n")
            if confirm.lower() != "y":
                console.print("[red]Aborted.[/red]")
                raise typer.Exit(0)

        async def process_questions():
            for qid in question_ids:
                console.print(f"\n[bold]Reviewing: {qid}[/bold]")
                report = await service.review_events_for_question(qid)
                _display_review_report(report, console)

        asyncio.run(process_questions())

    else:
        pending_events = db.get_many(Event, filters={"review_status": "pending"})
        unique_questions = set(
            e.extracted_for_question_id
            for e in pending_events
            if e.extracted_for_question_id
        )
        total_pending_questions = len(unique_questions)
        total_pending_events = len(pending_events)

        if total_pending_questions == 0:
            console.print("[green]No pending events to review.[/green]")
            raise typer.Exit(0)

        if not sample:
            sample = total_pending_questions

        if not yes:
            console.print(
                f"[yellow]About to auto-review up to {sample} question(s) "
                f"({total_pending_questions} questions, {total_pending_events} events total).[/yellow]"
            )
            confirm = Prompt.ask("Continue?", choices=["y", "n"], default="n")
            if confirm.lower() != "y":
                console.print("[red]Aborted.[/red]")
                raise typer.Exit(0)

        console.print(
            f"\n[bold]Running auto-review on {sample} question(s)...[/bold]\n"
        )

        # Get question IDs first for progress tracking
        pending_events = db.get_many(Event, filters={"review_status": "pending"})
        unique_questions = list(
            set(
                e.extracted_for_question_id
                for e in pending_events
                if e.extracted_for_question_id
            )
        )

        if not skip_criteria:
            filtered = []
            for qid in unique_questions:
                if service._question_meets_criteria_fast(qid):
                    filtered.append(qid)
            unique_questions = filtered

        if seed is not None:
            import random

            random.seed(seed)
            random.shuffle(unique_questions)

        if sample and sample < len(unique_questions):
            unique_questions = unique_questions[:sample]

        total_questions = len(unique_questions)

        async def process_questions():
            reports = []
            for idx, qid in enumerate(unique_questions, 1):
                console.print(f"[bold]Question {idx}/{total_questions}:[/bold] {qid}")
                report = await service.review_events_for_question(qid)
                reports.append(report)
                console.print(
                    f"  → {report.approved_events}/{report.total_events} approved, {'✓' if report.meets_criteria else '✗'} criteria"
                )
            return reports

        reports = asyncio.run(process_questions())

        total_approved = 0
        total_rejected = 0
        total_events = 0

        for report in reports:
            total_approved += report.approved_events
            total_rejected += report.rejected_events
            total_events += report.total_events

        table = Table(title="Auto-Review Summary")
        table.add_column("Question ID", style="cyan")
        table.add_column("Events", justify="right")
        table.add_column("Approved", justify="right", style="green")
        table.add_column("Rejected", justify="right", style="red")
        table.add_column("Meets Criteria", justify="center")

        for report in reports:
            table.add_row(
                report.question_id,
                str(report.total_events),
                str(report.approved_events),
                str(report.rejected_events),
                "✓" if report.meets_criteria else "✗",
            )

        console.print(table)

        console.print(
            f"\n[bold]Total:[/bold] {total_events} events reviewed, "
            f"[green]{total_approved}[/green] approved, "
            f"[red]{total_rejected}[/red] rejected"
        )


def _display_review_report(report: "EventReviewReport", console: Console):
    """Display a single review report."""
    status_color = "green" if report.meets_criteria else "yellow"
    status_icon = "✓" if report.meets_criteria else "✗"

    console.print(f"\n[bold]Question:[/bold] {report.question_id}")
    console.print(
        f"[{status_color}]{status_icon}[/{status_color}] "
        f"{report.approved_events}/{report.total_events} events approved"
    )

    if report.criteria_met:
        criteria_str = ", ".join(
            f"{k}: {'✓' if v else '✗'}" for k, v in report.criteria_met.items()
        )
        console.print(f"  Criteria: {criteria_str}")

    console.print(f"  {report.overall_assessment}")


@app.command()
def list_rejected(
    db_path: str = db_option(),
    limit: int = limit_option(),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show full reason for each event",
    ),
    event_id: Optional[str] = typer.Option(
        None,
        "--event",
        "-e",
        help="Show full details for a specific event ID",
    ),
):
    """List all rejected events with reasons.

    Examples:
        wr evidence list-rejected --db experiment.db
        wr evidence list-rejected --db experiment.db --limit 20
        wr evidence list-rejected --db experiment.db --verbose
        wr evidence list-rejected -e evt_123abc
    """
    from rich.table import Table

    db = GenericDatabase(db_path)
    console = Console()

    # Show specific event details
    if event_id:
        event = db.get(Event, event_id)
        if not event:
            console.print(f"[red]Event {event_id} not found[/red]")
            raise typer.Exit(1)

        if event.review_status.value != "rejected":
            console.print(
                f"[yellow]Event {event_id} is not rejected (status: {event.review_status})[/yellow]"
            )
            raise typer.Exit(0)

        console.print("\n[bold]Event Details[/bold]")
        console.print(f"ID: {event.id}")
        console.print(f"Title: {event.title}")
        console.print(f"Question: {event.extracted_for_question_id}")
        console.print(f"Description: {event.description}")
        console.print("\n[bold]Review Note:[/bold]")
        console.print(event.review_note or "No reason")
        raise typer.Exit(0)

    rejected = db.get_many(Event, filters={"review_status": "rejected"})

    if not rejected:
        console.print("[green]No rejected events found.[/green]")
        raise typer.Exit(0)

    if limit:
        rejected = rejected[:limit]

    console = Console(width=120)

    if verbose:
        for event in rejected:
            reason = event.review_note or "No reason"
            if reason.startswith("LLM Review:"):
                reason = reason[11:]
            console.print(
                f"\n[cyan]{event.id}[/cyan] | {event.extracted_for_question_id}"
            )
            console.print(f"  Title: {event.title}")
            console.print(f"  Reason: {reason}")
        console.print(f"\n[dim]Showing {len(rejected)} rejected events[/dim]")
        raise typer.Exit(0)

    table = Table(title=f"Rejected Events ({len(rejected)} shown)", expand=True)
    table.add_column("Event ID", style="cyan", width=22)
    table.add_column("Question", style="dim", width=28)
    table.add_column("Title", width=32)
    table.add_column("Reason", width=80)

    for event in rejected:
        reason = event.review_note or "No reason"
        if reason.startswith("LLM Review:"):
            reason = reason[11:]

        table.add_row(
            event.id[:20] + ".." if len(event.id) > 22 else event.id,
            (event.extracted_for_question_id or "N/A")[:26],
            event.title[:30] + ".." if len(event.title) > 32 else event.title,
            reason[:78] + ".." if len(reason) > 80 else reason,
        )

    console.print(table)
    console.print(
        f"\n[dim]Showing {len(rejected)} of {len(rejected)} rejected events[/dim]"
    )
    console.print(
        "[dim]Use --verbose or -v to see full reasons, or -e <id> for specific event[/dim]"
    )


@app.command()
def reset(
    db_path: str = db_option(),
    status: str = typer.Option(
        "all",
        "--status",
        "-s",
        help="Reset events with specific status: all, approved, rejected",
    ),
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Reset only events for specific question(s)",
    ),
    yes: bool = yes_option(),
):
    """Reset event review status to pending.

    Examples:
        # Reset all events to pending
        wr evidence reset --db experiment.db

        # Reset only rejected events
        wr evidence reset --status rejected

        # Reset for specific question
        wr evidence reset -q q_abc123

        # Reset approved events only
        wr evidence reset --status approved
    """
    db = GenericDatabase(db_path)

    if question_ids:
        all_events = []
        for qid in question_ids:
            events = db.get_many(Event, filters={"extracted_for_question_id": qid})
            all_events.extend(events)
    else:
        all_events = db.get_many(Event)

    # Filter by status
    to_reset = []
    for e in all_events:
        if status == "all":
            if e.review_status != ReviewStatus.PENDING:
                to_reset.append(e)
        elif status == "approved":
            if e.review_status == ReviewStatus.APPROVED:
                to_reset.append(e)
        elif status == "rejected":
            if e.review_status == ReviewStatus.REJECTED:
                to_reset.append(e)

    if not to_reset:
        console.print("[green]No events to reset.[/green]")
        raise typer.Exit(0)

    if not yes:
        console.print(
            f"[yellow]About to reset {len(to_reset)} events to pending.[/yellow]"
        )
        confirm = Prompt.ask("Continue?", choices=["y", "n"], default="n")
        if confirm.lower() != "y":
            console.print("[red]Aborted.[/red]")
            raise typer.Exit(0)

    count = 0
    for e in to_reset:
        e.review_status = ReviewStatus.PENDING
        e.review_note = None
        e.updated_at = datetime.now(timezone.utc)
        db.save(Event, e)
        count += 1

    console.print(f"[green]Reset {count} events to pending.[/green]")


@app.command()
def rerun(
    db_path: str = db_option("combined.db"),
    threshold: int = typer.Option(
        2,
        "--threshold",
        help="Re-run questions with <= this many unique source articles",
    ),
    ids: Optional[List[str]] = typer.Option(
        None,
        "--ids",
        help="Explicit question IDs to re-run (overrides --threshold scan)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print questions that would be re-run, then stop"
    ),
):
    """Re-run evidence + graph-builder pipelines for low-source questions.

    Examples:
        wr evidence rerun --db combined.db
        wr evidence rerun --db combined.db --threshold 3
        wr evidence rerun --db combined.db --ids q1 q2 q3
        wr evidence rerun --db combined.db --dry-run
    """
    from src.pipelines.evidence.rerun import rerun_evidence

    ok = asyncio.run(
        rerun_evidence(
            db_path=db_path,
            threshold=threshold,
            ids=ids,
            dry_run=dry_run,
            log=console.print,
        )
    )
    if not ok:
        raise typer.Exit(1)
