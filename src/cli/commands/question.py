"""Question collection and query commands for WorldReasoner CLI.

Provides commands to collect questions from various sources including
Polymarket, news sources, and goal-oriented orchestration, as well as
list/show/search/status commands for querying stored questions.
"""

import asyncio
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.config.collection_goal import CollectionGoal
from src.cli.core.options import (
    db_option,
    domain_option,
    limit_option,
    json_option,
    get_db_and_manager,
)
from src.cli.ui.displays import (
    display_question_list,
    display_question_detail,
    display_question_stats,
)
from src.utils.logging import logger

app = typer.Typer(help="Question management and collection commands")
console = Console()


# =============================================================================
# Query Commands
# =============================================================================


@app.command("list")
def list_questions(
    db_path: str = db_option(),
    domain: Optional[str] = domain_option(),
    limit: int = limit_option(),
):
    """List questions with filtering.

    Examples:
        wr question list
        wr question list --domain politics --limit 20
        wr question list --db experiment.db
    """
    _, manager = get_db_and_manager(db_path)
    display_question_list(manager, console, domain=domain, limit=limit)


@app.command()
def show(
    item_id: str = typer.Argument(..., help="Question ID"),
    db_path: str = db_option(),
    json_output: bool = json_option(),
):
    """Show detailed information about a question.

    Examples:
        wr question show q_abc123
        wr question show q_abc123 --json
        wr question show q_abc123 --db experiment.db
    """
    _, manager = get_db_and_manager(db_path)
    display_question_detail(manager, console, item_id, json_output=json_output)


@app.command()
def status(
    db_path: str = db_option(),
):
    """Show question-focused statistics.

    Examples:
        wr question status
        wr question status --db experiment.db
    """
    _, manager = get_db_and_manager(db_path)
    display_question_stats(manager, console)


@app.command()
def search(
    text: str = typer.Argument(..., help="Search text to match against questions"),
    db_path: str = db_option(),
    domain: Optional[str] = domain_option(),
    limit: int = limit_option(default=20),
):
    """Search questions by text (keyword match).

    Examples:
        wr question search "election"
        wr question search "bitcoin" --domain finance
        wr question search "climate" --db experiment.db --limit 10
    """
    from src.cli.core.question_manager import QuestionFilter
    from src.cli.ui.tables import display_question_table

    _, manager = get_db_and_manager(db_path)

    filter_obj = QuestionFilter(domain=domain)
    questions = manager.query_questions(filter_obj, limit=500)

    # Keyword filter on question text
    search_lower = text.lower()
    matched = [q for q in questions if search_lower in q.question_text.lower()][:limit]

    if not matched:
        console.print(f"[yellow]No questions matching '{text}'[/yellow]")
        raise typer.Exit(0)

    evidence_map = manager.get_evidence_status(matched)
    display_question_table(matched, evidence_map, console)


# =============================================================================
# Collection Commands
# =============================================================================


@app.command()
def goal(
    goal_config: str = typer.Option(
        "config/collection_goal.yaml",
        "--goal",
        "-g",
        help="Path to collection goal YAML config",
    ),
    db_path: str = db_option(),
    sources_config: str = typer.Option(
        "config/sources.yaml",
        "--sources",
        help="Path to sources configuration",
    ),
    no_polymarket: bool = typer.Option(
        False,
        "--no-polymarket",
        help="Disable Polymarket source",
    ),
    no_news: bool = typer.Option(
        False,
        "--no-news",
        help="Disable news-based source",
    ),
    sequential: bool = typer.Option(
        False,
        "--sequential",
        help="Run sources sequentially instead of in parallel",
    ),
    skip_indexing: bool = typer.Option(
        False,
        "--skip-indexing",
        help="Skip automatic search indexing after completion",
    ),
):
    """Run goal-oriented question collection from multiple sources.

    Orchestrates collection from Polymarket, news sources, etc. until
    distribution goals are met (types, categories, resolution status).

    Examples:
        # Run with default config
        wr question goal

        # Use custom goal config
        wr question goal --goal config/my_goal.yaml

        # Only use Polymarket
        wr question goal --no-news

        # Run sources sequentially
        wr question goal --sequential
    """
    # Validate goal file exists
    goal_path = Path(goal_config)
    if not goal_path.exists():
        console.print(f"[red]Goal config not found: {goal_config}[/red]")
        console.print("\nCreate one from the example:")
        console.print(
            "  [cyan]cp config/collection_goal.example.yaml config/collection_goal.yaml[/cyan]"
        )
        raise typer.Exit(1)

    # Load and display goal
    try:
        goal_obj = CollectionGoal.from_yaml(str(goal_path))
        goal_obj.validate_distributions()
    except Exception as e:
        console.print(f"[red]Failed to load goal config: {e}[/red]")
        raise typer.Exit(1)

    # Display goal summary
    console.print("\n[bold cyan]Collection Goal[/bold cyan]")
    console.print(f"  Target: {goal_obj.total_questions} questions")
    console.print(f"  Types: {dict(goal_obj.type_distribution)}")
    console.print(f"  Categories: {dict(goal_obj.category_distribution)}")
    console.print(f"  Require resolved: {goal_obj.require_ground_truth}")

    # Display enabled sources
    sources_enabled = []
    if not no_polymarket:
        sources_enabled.append("Polymarket")
    if not no_news:
        sources_enabled.append("News")

    if not sources_enabled:
        console.print("\n[red]No sources enabled! Enable at least one source.[/red]")
        raise typer.Exit(1)

    console.print(f"  Sources: {', '.join(sources_enabled)}")
    console.print(f"  Parallel: {not sequential}")

    if not typer.confirm("\nStart collection?"):
        raise typer.Exit(0)

    # Run collection
    console.print("\n[bold cyan]Starting collection orchestration...[/bold cyan]")

    try:
        result = asyncio.run(
            _run_goal_collection_async(
                goal_path=str(goal_path),
                goal=goal_obj,
                db_path=db_path,
                sources_config=sources_config,
                enable_polymarket=not no_polymarket,
                enable_news=not no_news,
                parallel_sources=not sequential,
                skip_indexing=skip_indexing,
            )
        )

        # Display results
        _display_collection_results(result, goal_obj)

        if result.failure_count > 0:
            raise typer.Exit(1)

    except Exception as e:
        logger.error(f"Collection failed: {e}")
        console.print(f"\n[red]Collection failed: {e}[/red]")
        raise typer.Exit(1)


async def _run_goal_collection_async(
    goal_path: str,
    goal: CollectionGoal,
    db_path: str,
    sources_config: str,
    enable_polymarket: bool,
    enable_news: bool,
    parallel_sources: bool,
    skip_indexing: bool,
):
    """Execute goal-oriented collection asynchronously using PipelineRunner."""
    from src.cli.core.pipeline_runner import (
        PipelineRunner,
        PipelineType,
        PipelineProgress,
    )

    runner = PipelineRunner(db_path=db_path)

    # Create progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Initializing collection...",
            total=5,
        )

        def on_progress(p: PipelineProgress):
            progress.update(
                task,
                completed=p.current,
                description=f"[cyan]{p.stage}: {p.message}",
            )

        # Run collection pipeline
        result = await runner.run(
            PipelineType.COLLECTION,
            question_ids=[],  # Not used for collection
            on_progress=on_progress,
            goal_path=goal_path,
            sources_config=sources_config,
            enable_polymarket=enable_polymarket,
            enable_news=enable_news,
            parallel_sources=parallel_sources,
            skip_indexing=skip_indexing,
        )

    return result


def _display_collection_results(result, goal: CollectionGoal):
    """Display formatted collection results from PipelineResult."""
    console.print("\n[bold]Collection Complete[/bold]")
    console.print("=" * 50)

    # Extract metadata from last processed item (contains collection metadata)
    metadata = result.processed[-1] if result.processed else {}
    questions = (
        result.processed[:-1] if result.processed else []
    )  # All except last (metadata)

    # Summary
    goal_met = metadata.get("goal_met", False)
    iterations = metadata.get("iterations", 0)
    status = "[green]✓ Goal MET[/green]" if goal_met else "[red]✗ Goal NOT MET[/red]"
    console.print(f"Status: {status}")
    console.print(f"Questions: {len(questions)}/{goal.total_questions}")
    console.print(f"Iterations: {iterations}")
    console.print(f"Duration: {result.duration_seconds:.1f}s")

    if result.failed:
        console.print(f"[yellow]Errors: {len(result.failed)}[/yellow]")

    # Distribution breakdown
    console.print("\n[bold]Distribution Breakdown[/bold]")

    # Sources
    by_source = metadata.get("by_source", {})
    if by_source:
        console.print("\n[cyan]By Source:[/cyan]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Source")
        table.add_column("Count", justify="right")

        for source, count in sorted(by_source.items()):
            table.add_row(source, str(count))
        console.print(table)

    # Types
    by_type = metadata.get("by_type", {})
    if by_type:
        console.print("\n[cyan]By Type:[/cyan]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Type")
        table.add_column("Collected", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Status")

        for qtype, count in sorted(by_type.items()):
            target = goal.type_distribution.get(qtype, 0)
            status = "[green]✓[/green]" if count >= target else "[red]✗[/red]"
            table.add_row(qtype, str(count), str(target), status)
        console.print(table)

    # Categories
    by_category = metadata.get("by_category", {})
    if by_category:
        console.print("\n[cyan]By Category:[/cyan]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Category")
        table.add_column("Collected", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Status")

        for category, count in sorted(by_category.items()):
            target = goal.category_distribution.get(category, 0)
            status = "[green]✓[/green]" if count >= target else "[red]✗[/red]"
            table.add_row(category, str(count), str(target), status)
        console.print(table)

    # Sample questions
    if questions:
        console.print("\n[bold]Sample Questions[/bold]")
        for i, q in enumerate(questions[:3], 1):
            qtype = q.get("type", "").replace("QuestionType.", "")
            domain = q.get("domain", "").replace("Domain.", "")
            console.print(f"\n{i}. {q.get('text', 'N/A')}")
            console.print(
                f"   Type: {qtype} | Source: {q.get('source', 'N/A')} | Domain: {domain}"
            )

        if len(questions) > 3:
            console.print(f"\n   ... and {len(questions) - 3} more questions")


@app.command()
def collect(
    goal_config: str = typer.Option(
        "config/collection_goal_experiment.yaml",
        "--goal",
        "-g",
        help="Path to collection goal YAML config",
    ),
    db_path: str = db_option("experiment.db"),
    sources_config: str = typer.Option(
        "config/sources.yaml", "--sources", help="Path to article sources config"
    ),
    max_iterations: int = typer.Option(
        3, "--max-iterations", help="Maximum orchestration iterations"
    ),
    no_polymarket: bool = typer.Option(
        False, "--no-polymarket", help="Disable Polymarket source"
    ),
    no_news: bool = typer.Option(False, "--no-news", help="Disable news-based source"),
    sequential: bool = typer.Option(
        False, "--sequential", help="Run sources sequentially instead of in parallel"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show collection plan without running"
    ),
    export: Optional[str] = typer.Option(
        None, "--export", help="Export dataset summary to JSON file"
    ),
    skip_indexing: bool = typer.Option(
        False, "--skip-indexing", help="Skip automatic search indexing after collection"
    ),
):
    """Collect a distribution-balanced experiment dataset until goals are met.

    Examples:
        wr question collect
        wr question collect --dry-run
        wr question collect --no-news --export dataset_summary.json
        wr question collect --db experiment.db --max-iterations 5
    """
    from src.pipelines.collection.experiment import run_experiment_collection

    goal_met = asyncio.run(
        run_experiment_collection(
            goal_path=goal_config,
            db_path=db_path,
            sources_config=sources_config,
            max_iterations=max_iterations,
            enable_polymarket=not no_polymarket,
            enable_news=not no_news,
            parallel_sources=not sequential,
            dry_run=dry_run,
            export_path=export,
            skip_indexing=skip_indexing,
        )
    )
    if not goal_met and not dry_run:
        raise typer.Exit(1)


@app.command()
def select(
    db_path: str = db_option("combined.db"),
    n: int = typer.Option(120, "--n", help="Total questions to select"),
    polymarket_n: int = typer.Option(
        100, "--polymarket-n", help="Target number of polymarket questions"
    ),
    min_score: float = typer.Option(
        0.8, "--min-score", help="Minimum quality score"
    ),
    min_sources: int = typer.Option(
        3, "--min-sources", help="Minimum unique sources"
    ),
    domain_cap: float = typer.Option(
        0.25, "--domain-cap", help="Max fraction of selections per domain"
    ),
    questions_per_session: int = typer.Option(4, "--questions-per-session"),
    overlap_sessions: int = typer.Option(
        3, "--overlap-sessions", help="Number of overlap (inter-rater) sessions"
    ),
    out_include: str = typer.Option(
        "include_ids.txt", "--out-include", help="Output file for selected IDs"
    ),
    out_overlap: str = typer.Option(
        "overlap.txt", "--out-overlap", help="Output file for overlap IDs"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print stats only, don't write files"
    ),
):
    """Select high-quality, domain-balanced questions for an annotation study."""
    from src.domain.selection import select_questions

    select_questions(
        db_path=db_path,
        n=n,
        polymarket_n=polymarket_n,
        min_score=min_score,
        min_sources=min_sources,
        domain_cap=domain_cap,
        questions_per_session=questions_per_session,
        overlap_sessions=overlap_sessions,
        out_include=out_include,
        out_overlap=out_overlap,
        dry_run=dry_run,
        log=console.print,
    )


@app.command("add")
def add(
    text: str = typer.Option(
        ..., "--text", help="Question text (must be at least 20 characters)"
    ),
    resolution_date: str = typer.Option(
        ...,
        "--resolution-date",
        help="Resolution date (YYYY-MM-DD or ISO datetime)",
    ),
    domain: str = typer.Option(
        "general",
        "--domain",
        "-d",
        help="Domain: politics, finance, tech, health, climate, culture, business, science, sports, general",
    ),
    question_type: str = typer.Option(
        "binary",
        "--type",
        help="Question type: binary, mcq, quantity, timeframe",
    ),
    source: str = typer.Option("manual", "--source", help="Question source label"),
    difficulty: int = typer.Option(
        3, "--difficulty", min=1, max=5, help="Difficulty rating 1-5"
    ),
    options: Optional[str] = typer.Option(
        None, "--options", help="Comma-separated options (required for mcq)"
    ),
    resolution_criteria: Optional[str] = typer.Option(
        None, "--resolution-criteria", help="How the question resolves"
    ),
    ground_truth: Optional[str] = typer.Option(
        None, "--ground-truth", help="Known outcome, if already resolved"
    ),
    db_path: str = db_option(),
):
    """Add a manually-authored question to a dataset.

    Examples:
        wr question add --text "Will X happen by 2025?" --resolution-date 2025-12-31 --domain politics
        wr question add --text "..." --resolution-date 2025-06-30 --type mcq --options "A,B,C"
    """
    from src.domain.models import Question
    from src.domain.models.domain import Domain
    from src.domain.models.question import QuestionType
    from src.domain.models.id_generator import generate_timestamped_id
    from src.utils.date_utils import parse_flexible_datetime

    if len(text.strip()) < 20:
        console.print(
            "[red]Question text must be at least 20 characters.[/red]"
        )
        raise typer.Exit(1)

    try:
        domain_enum = Domain(domain.lower())
    except ValueError:
        console.print(
            f"[red]Invalid domain '{domain}'.[/red] Valid: "
            f"{', '.join(d.value for d in Domain)}"
        )
        raise typer.Exit(1)

    try:
        type_enum = QuestionType(question_type.lower())
    except ValueError:
        console.print(
            f"[red]Invalid type '{question_type}'.[/red] Valid: "
            f"{', '.join(t.value for t in QuestionType)}"
        )
        raise typer.Exit(1)

    options_list = None
    if options:
        options_list = [o.strip() for o in options.split(",") if o.strip()]
    if type_enum == QuestionType.MCQ and not options_list:
        console.print("[red]--options is required for mcq questions.[/red]")
        raise typer.Exit(1)

    db, _ = get_db_and_manager(db_path)
    # Ensure the target database has its schema (the global callback only
    # initializes the configured default db, not an arbitrary --db).
    db.initialize_all_tables()

    question = Question(
        id=generate_timestamped_id("q_manual"),
        question_text=text.strip(),
        question_type=type_enum,
        domain=domain_enum,
        source=source,
        difficulty=difficulty,
        resolution_date=parse_flexible_datetime(resolution_date),
        resolution_criteria=resolution_criteria,
        ground_truth=ground_truth,
        options=options_list,
    )

    db.save(Question, question)
    console.print(
        f"[green]Added question[/green] [cyan]{question.id}[/cyan] "
        f"to [cyan]{db_path}[/cyan]"
    )


@app.command("add-polymarket")
def add_polymarket(
    identifiers: List[str] = typer.Argument(
        ...,
        help="Polymarket event/market slugs, polymarket.com URLs, or numeric ids",
    ),
    db_path: str = db_option(),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Resolve and preview without saving"
    ),
):
    """Add specific Polymarket questions to a dataset by slug, URL, or id.

    Fetches exactly the markets you name (no quality filtering or target counts)
    and saves them to the given database, skipping any that already exist.

    Examples:
        wr question add-polymarket will-trump-win-2024 --db combined.db
        wr question add-polymarket https://polymarket.com/event/some-event
        wr question add-polymarket slug-a slug-b 12345 --dry-run
    """
    from src.pipelines.collection import PolymarketRunner
    from src.domain.models import Question

    db, _ = get_db_and_manager(db_path)
    # Ensure the target database has its schema (the global callback only
    # initializes the configured default db, not an arbitrary --db).
    db.initialize_all_tables()

    # require_ground_truth=False so both resolved and active markets resolve;
    # ground truth is still extracted from the market data when present.
    runner = PolymarketRunner(require_ground_truth=False)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(
            f"Resolving {len(identifiers)} Polymarket identifier(s)...", total=None
        )
        result = asyncio.run(runner.collect_by_identifiers(identifiers))

    if result.error_message:
        console.print(f"[yellow]Warnings:[/yellow] {result.error_message}")

    if not result.questions:
        console.print("[red]No questions resolved.[/red]")
        raise typer.Exit(1)

    # Preview table
    table = Table(title=f"Resolved {len(result.questions)} question(s)")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Domain")
    table.add_column("Question")
    for q in result.questions:
        table.add_row(
            q.id,
            q.question_type.value
            if hasattr(q.question_type, "value")
            else str(q.question_type),
            q.domain.value if hasattr(q.domain, "value") else str(q.domain),
            (q.question_text[:80] + "...")
            if len(q.question_text) > 80
            else q.question_text,
        )
    console.print(table)

    if dry_run:
        console.print("[dim]Dry run - nothing saved.[/dim]")
        return

    saved = 0
    skipped = 0
    for q in result.questions:
        if db.get(Question, q.id):
            skipped += 1
            continue
        db.save(Question, q)
        saved += 1

    console.print(
        f"[green]Saved {saved}[/green], skipped {skipped} duplicate(s) "
        f"into [cyan]{db_path}[/cyan]"
    )


@app.command("refresh-polymarket")
def refresh_polymarket(
    db_path: str = db_option(),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n", help="Max unresolved questions to check"
    ),
):
    """Backfill ground truth for previously-unresolved Polymarket questions.

    Re-fetches each stored Polymarket question that has no ground truth yet and
    copies the outcome over for any whose market has since resolved.

    Examples:
        wr question refresh-polymarket --db combined.db
        wr question refresh-polymarket -n 50
    """
    from src.pipelines.collection import refresh_polymarket_ground_truth

    db, _ = get_db_and_manager(db_path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Checking unresolved Polymarket questions...", total=None)
        result = asyncio.run(refresh_polymarket_ground_truth(db, limit=limit))

    if result.candidates == 0:
        console.print("[dim]No unresolved Polymarket questions found.[/dim]")
        return

    console.print(
        f"Checked [cyan]{result.candidates}[/cyan] unresolved question(s): "
        f"[green]{result.updated} resolved[/green], "
        f"{result.still_unresolved} still open."
    )
    if result.updated_ids:
        for qid in result.updated_ids:
            console.print(f"  [green]resolved[/green] {qid}")
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} error(s):[/yellow]")
        for err in result.errors[:10]:
            console.print(f"  [yellow]-[/yellow] {err}")
