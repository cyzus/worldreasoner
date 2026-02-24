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
from src.cli.core.question_selector import QuestionSelector
from src.cli.core.question_manager import QuestionManager
from src.cli.core.pipeline_runner import PipelineRunner, PipelineType, PipelineProgress
from src.domain.models import Question, Event, Article, ReviewStatus
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
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Filter by question source (e.g., polymarket)",
    ),
    domain: Optional[str] = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter by domain (e.g., politics, technology)",
    ),
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
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        help="Maximum number of questions to process",
    ),
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
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
    sample: Optional[int] = typer.Option(
        None,
        "--sample",
        help="Process a random sample of N questions from the filtered set",
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Random seed for reproducible sampling",
    ),
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
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence if not has_evidence else None,
            limit=limit,
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
            breakdown = ", ".join(
                f"{d}={c}" for d, c in sorted(domain_counts.items())
            )
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
    min_graph_depth: int = 3,
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
                }
            )
        else:
            # Standard pipeline parameters
            pipeline_kwargs["force_reprocess"] = force_reprocess

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
        table.add_column("Hypotheses", justify="right")

        for item in result.processed:
            table.add_row(
                item["id"],
                str(item.get("articles", 0)),
                str(item.get("hypotheses", 0)),
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
    question_ids: List[str] = typer.Option(
        ...,
        "--question",
        "-q",
        help="Question ID(s) to clear evidence for (can be repeated)",
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
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
):
    """Clear evidence data for questions.

    Removes causal hypotheses and optionally cascades to orphaned events/articles.
    The questions themselves are kept - only evidence data is removed.

    Examples:
        wr evidence clear -q q_abc123
        wr evidence clear -q q_1 -q q_2 -q q_3 --cascade
        wr evidence clear -q q_abc123 --dry-run
    """
    if not question_ids:
        console.print("[red]Please provide at least one question ID[/red]")
        raise typer.Exit(1)

    db = GenericDatabase(db_path)
    manager = QuestionManager(db)

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
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
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
    sample: Optional[int] = typer.Option(
        None,
        "--sample",
        "-n",
        help="Review a random sample of N events (default: review all)",
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Random seed for reproducible sampling",
    ),
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
            by_question[qid] = {"pending": 0, "approved": 0, "rejected": 0, "revised": 0, "total": 0}
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
        console.print(f"\n  [{style}]Approval rate: {rate:.0f}% ({reviewed['approved']}/{total_decided})[/{style}]")


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
