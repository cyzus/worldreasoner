"""Database management commands for WorldReasoner CLI.

Provides question-centric CRUD operations with cascading deletes.
"""

import asyncio
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
import json

from src.core.database import GenericDatabase
from src.core.hybrid_search import HybridSearch
from src.cli.core.options import db_option, json_option, limit_option, domain_option, get_db_and_manager
from src.cli.ui.displays import display_question_list, display_question_detail
from src.cli.ui.tables import (
    display_event_table,
    display_article_table,
)
from src.domain.models import Event, Article
from src.core.search_indexing import auto_index_articles
from src.config.settings import get_config

app = typer.Typer(help="Database management commands")
console = Console()


@app.command()
def stats(
    db_path: str = db_option(),
):
    """Show database statistics."""
    _, manager = get_db_and_manager(db_path)

    stats_data = manager.get_stats()

    table = Table(title="Database Statistics", show_header=True)
    table.add_column("Table", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="green")

    for table_name, count in stats_data.items():
        display_name = table_name.replace("_", " ").title()
        table.add_row(display_name, str(count))

    console.print(table)


@app.command("list")
def list_items(
    item_type: str = typer.Argument(..., help="Type: questions, events, articles"),
    domain: Optional[str] = domain_option(),
    limit: int = limit_option(),
    show_related: bool = typer.Option(
        False, "--related", "-r", help="Show related entity counts"
    ),
    db_path: str = db_option(),
):
    """List database items with filtering."""
    db, manager = get_db_and_manager(db_path)

    if item_type == "questions":
        display_question_list(manager, console, domain=domain, limit=limit)
        return

    elif item_type == "events":
        events = db.get_many(Event)[:limit]
        display_event_table(events, console)

    elif item_type == "articles":
        articles = db.get_many(Article)[:limit]
        display_article_table(articles, console)
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: questions, events, articles")
        raise typer.Exit(1)


@app.command()
def show(
    item_type: str = typer.Argument(..., help="Type: question, event"),
    item_id: str = typer.Argument(..., help="Item ID"),
    db_path: str = db_option(),
    json_output: bool = json_option(),
):
    """Show detailed information about an item."""
    db, manager = get_db_and_manager(db_path)

    if item_type == "question":
        display_question_detail(manager, console, item_id, json_output=json_output)

    elif item_type == "event":
        event = db.get(Event, item_id)
        if not event:
            console.print(f"[red]Event {item_id} not found[/red]")
            raise typer.Exit(1)

        if json_output:
            rprint(json.dumps(event.model_dump(), indent=2, default=str))
        else:
            console.print(
                Panel(f"[bold cyan]{event.title}[/bold cyan]", title=f"Event {item_id}")
            )
            console.print(
                f"\n[bold]Domain:[/bold] {event.domain.value if hasattr(event.domain, 'value') else event.domain}"
            )
            console.print(
                f"[bold]Status:[/bold] {event.status.value if hasattr(event.status, 'value') else event.status}"
            )
            console.print(f"[bold]Articles:[/bold] {len(event.article_ids)}")
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question, event")
        raise typer.Exit(1)


@app.command()
def analyze(
    item_type: str = typer.Argument(..., help="Type: question"),
    item_id: str = typer.Argument(..., help="Item ID"),
    db_path: str = db_option(),
    json_output: bool = json_option(),
):
    """Analyze cascade impact of deleting an item."""
    _, manager = get_db_and_manager(db_path)

    if item_type == "question":
        result = manager.analyze_cascade(item_id)

        if "error" in result:
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(1)

        if json_output:
            rprint(json.dumps(result, indent=2, default=str))
        else:
            console.print(
                Panel(
                    f"[bold yellow]Cascade Analysis for Question {item_id}[/bold yellow]"
                )
            )

            summary = result["summary"]
            console.print("\n[bold]Will Delete:[/bold]")
            console.print(f"  Events: {summary['will_delete_events']}")
            console.print(f"  Articles: {summary['will_delete_articles']}")
            console.print(f"  Causal Hypotheses: {summary['will_delete_hypotheses']}")

            console.print("\n[bold]Will Update:[/bold]")
            console.print(
                f"  Hypotheses (remove from discovered_by): {summary['will_update_hypotheses']}"
            )

            console.print("\n[bold]Will Keep:[/bold]")
            console.print(
                f"  Pre-existing Events: {summary['will_keep_pre_existing_events']}"
            )

            provenance = result["provenance_stats"]
            console.print("\n[bold]Provenance Tracking:[/bold]")
            console.print(
                f"  Articles tracked by field: {provenance['articles_by_field']}"
            )
            console.print(
                f"  Articles tracked by metadata: {provenance['articles_by_metadata']}"
            )
            console.print(f"  Events tracked by field: {provenance['events_by_field']}")
            console.print(
                f"  Events tracked by metadata: {provenance['events_by_metadata']}"
            )
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question")
        raise typer.Exit(1)


@app.command()
def delete(
    item_type: str = typer.Argument(..., help="Type: question, event"),
    item_id: str = typer.Argument(..., help="Item ID"),
    cascade: bool = typer.Option(
        True, "--cascade/--no-cascade", help="Delete related entities"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
    db_path: str = db_option(),
):
    """Delete an item from the database."""
    _, manager = get_db_and_manager(db_path)

    if item_type == "question":
        result = manager.delete_question(item_id, cascade=cascade, dry_run=dry_run)
    elif item_type == "event":
        result = manager.delete_event(item_id, cascade=cascade, dry_run=dry_run)
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question, event")
        raise typer.Exit(1)

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        if "hint" in result:
            console.print(f"[yellow]Hint: {result['hint']}[/yellow]")
        raise typer.Exit(1)

    if dry_run:
        console.print(Panel("[bold yellow]DRY RUN - No changes made[/bold yellow]"))
        rprint(json.dumps(result, indent=2, default=str))
    else:
        console.print("[bold green]Deletion completed[/bold green]")
        summary = result["summary"]
        for entity_type, count in summary.items():
            if count > 0:
                console.print(f"  {entity_type}: {count}")


@app.command("clear-evidence")
def clear_evidence(
    question_id: str = typer.Argument(..., help="Question ID"),
    cascade: bool = typer.Option(
        True, "--cascade/--no-cascade", help="Delete related data"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
    db_path: str = db_option(),
):
    """Remove evidence data for a question (keeps the question itself).

    Useful for re-running the evidence pipeline on a question.
    """
    _, manager = get_db_and_manager(db_path)

    result = manager.clear_evidence(question_id, cascade=cascade, dry_run=dry_run)

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    if dry_run:
        console.print(
            Panel(
                f"[bold yellow]DRY RUN - Preview for Question {question_id}[/bold yellow]"
            )
        )
        summary = result["summary"]
        console.print("\n[bold]Would Delete:[/bold]")
        console.print(f"  Articles: {summary['articles']}")
        console.print(f"  Events: {summary['events']}")
        console.print(f"  Causal Hypotheses: {summary['hypotheses_delete']}")
        console.print("\n[bold]Would Update:[/bold]")
        console.print(
            f"  Hypotheses (remove from discovered_by): {summary['hypotheses_update']}"
        )
    else:
        console.print(
            f"[bold green]Evidence cleared for question {question_id}[/bold green]"
        )
        summary = result["summary"]
        console.print("\n[bold]Deleted:[/bold]")
        for entity_type, count in summary.items():
            if count > 0:
                display_name = entity_type.replace("_", " ").title()
                console.print(f"  {display_name}: {count}")


@app.command()
def update(
    item_type: str = typer.Argument(..., help="Type: question"),
    item_id: str = typer.Argument(..., help="Item ID"),
    field: str = typer.Option(..., "--field", "-f", help="Field to update"),
    value: str = typer.Option(..., "--value", "-v", help="New value"),
    db_path: str = db_option(),
):
    """Update a field on an item."""
    _, manager = get_db_and_manager(db_path)

    if item_type == "question":
        result = manager.update_question(item_id, {field: value})

        if "error" in result:
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(1)

        console.print(f"[bold green]Updated {item_type} {item_id}[/bold green]")
        console.print(f"  Updated fields: {', '.join(result['updated'])}")
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question")
        raise typer.Exit(1)


@app.command("build-index")
def build_index(
    db_path: str = db_option(),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Embedding model (default: from config)"
    ),
    rebuild: bool = typer.Option(
        False, "--rebuild", "-r", help="Rebuild all indexes from scratch"
    ),
    batch_size: int = typer.Option(
        2, "--batch-size", "-b", help="Batch size for embeddings"
    ),
    show_stats: bool = typer.Option(
        True, "--stats/--no-stats", help="Show index statistics"
    ),
):
    """Build or rebuild search indexes for hybrid search.

    Indexes articles for both FTS5 (full-text search) and semantic embeddings.
    By default, only indexes new articles. Use --rebuild to reindex everything.

    Examples:
        wr db build-index
        wr db build-index --rebuild
        wr db build-index --model text-embedding-3-large
        wr db build-index --db data/worldreasoner.db --batch-size 10
    """
    db = GenericDatabase(db_path)

    # Get embedding model from config if not provided
    if model is None:
        config = get_config()
        model = config.llm.embedding_model
        console.print(f"[dim]Using embedding model from config: {model}[/dim]")

    # Get current stats before indexing
    search = HybridSearch(db_path, embedding_model=model)
    before_stats = search.get_index_stats()

    # Show current status
    db.create_table(Article)
    total_articles = len(db.get_many(Article))

    if show_stats:
        console.print(
            Panel(
                f"[bold]Database:[/bold] {db_path}\n"
                f"[bold]Total Articles:[/bold] {total_articles}\n"
                f"[bold]FTS Indexed:[/bold] {before_stats['fts_indexed']}\n"
                f"[bold]Embeddings Indexed:[/bold] {before_stats['embeddings_indexed']}\n"
                f"[bold]Model:[/bold] {model}",
                title="Current Index Status",
            )
        )

    if total_articles == 0:
        console.print(
            "[yellow]No articles found in database. Nothing to index.[/yellow]"
        )
        return

    # Determine what to do
    if rebuild:
        console.print(
            "\n[bold yellow]Rebuilding all indexes from scratch...[/bold yellow]"
        )
        skip_existing = False
    else:
        to_index = total_articles - before_stats["embeddings_indexed"]
        if to_index == 0:
            console.print("[green]All articles already indexed.[/green]")
            return
        console.print(f"\n[bold cyan]Indexing {to_index} new articles...[/bold cyan]")
        skip_existing = True

    # Run the indexing
    try:
        with console.status("[bold green]Indexing articles..."):
            result = asyncio.run(
                auto_index_articles(
                    db_path=db_path, embedding_model=model, skip_existing=skip_existing
                )
            )

        # Show results
        if result["status"] == "success":
            console.print("\n[bold green]Indexing Complete![/bold green]")
            console.print(f"  New articles indexed: {result['newly_indexed']}")
            console.print(f"  Total indexed: {result['final_indexed']}")
        elif result["status"] == "up_to_date":
            console.print("\n[bold green]All articles already indexed![/bold green]")
        elif result["status"] == "failed":
            console.print(
                f"\n[bold red]Indexing failed: {result.get('error', 'Unknown error')}[/bold red]"
            )
            raise typer.Exit(1)

        # Show final stats
        if show_stats:
            after_stats = search.get_index_stats()
            table = Table(title="Index Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green", justify="right")

            table.add_row("Total Articles", str(total_articles))
            table.add_row("FTS5 Indexed", str(after_stats["fts_indexed"]))
            table.add_row("Embeddings Indexed", str(after_stats["embeddings_indexed"]))
            table.add_row("Embedding Models", ", ".join(after_stats["models"]))

            console.print("\n")
            console.print(table)

    except Exception as e:
        console.print(f"\n[bold red]Error building index: {e}[/bold red]")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)
