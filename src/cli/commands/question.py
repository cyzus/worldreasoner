"""Question collection commands for WorldReasoner CLI.

Provides commands to collect questions from various sources including
Polymarket, news sources, and goal-oriented orchestration.
"""

import asyncio
from pathlib import Path
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.config.collection_goal import CollectionGoal
from src.utils.logging import logger

app = typer.Typer(help="Question collection commands")
console = Console()


@app.command()
def goal(
    goal_config: str = typer.Option(
        "config/collection_goal.yaml",
        "--goal",
        "-g",
        help="Path to collection goal YAML config",
    ),
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
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
        goal = CollectionGoal.from_yaml(str(goal_path))
        goal.validate_distributions()
    except Exception as e:
        console.print(f"[red]Failed to load goal config: {e}[/red]")
        raise typer.Exit(1)

    # Display goal summary
    console.print("\n[bold cyan]Collection Goal[/bold cyan]")
    console.print(f"  Target: {goal.total_questions} questions")
    console.print(f"  Types: {dict(goal.type_distribution)}")
    console.print(f"  Categories: {dict(goal.category_distribution)}")
    console.print(f"  Require resolved: {goal.require_ground_truth}")

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
                goal=goal,
                db_path=db_path,
                sources_config=sources_config,
                enable_polymarket=not no_polymarket,
                enable_news=not no_news,
                parallel_sources=not sequential,
                skip_indexing=skip_indexing,
            )
        )

        # Display results
        _display_collection_results(result, goal)

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
