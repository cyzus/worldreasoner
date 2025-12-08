"""Database management commands for WorldReasoner CLI.

Provides question-centric CRUD operations with cascading deletes.
"""

import sys
from typing import Optional, List
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
import json

from src.core.database import GenericDatabase
from src.cli.core.question_manager import QuestionManager
from src.domain.models import Event, Article

app = typer.Typer(help="Database management commands")
console = Console()


def get_db_and_manager(db_path: str):
    """Helper to create database and manager instances."""
    db = GenericDatabase(db_path)
    manager = QuestionManager(db)
    return db, manager


@app.command()
def stats(
    db_path: str = typer.Option("worldreasoner.db", "--db", "-d", help="Database path"),
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
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum results to show"),
    show_related: bool = typer.Option(False, "--related", "-r", help="Show related entity counts"),
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
):
    """List database items with filtering."""
    db, manager = get_db_and_manager(db_path)

    if item_type == "questions":
        results = manager.list_questions(
            domain=domain,
            limit=limit,
            show_related=show_related
        )

        table = Table(title=f"Questions (showing {len(results)})", show_header=True)
        table.add_column("ID", style="cyan", no_wrap=True, max_width=16)
        table.add_column("Question", style="white", overflow="ellipsis", max_width=50)
        table.add_column("Domain", style="yellow", no_wrap=True)
        table.add_column("Type", style="magenta", no_wrap=True)
        table.add_column("Quality", justify="right", style="green")
        if show_related:
            table.add_column("Events", justify="right", style="blue")

        for item in results:
            row = [
                item["id"][:14] + "...",
                item["question_text"][:47] + "..." if len(item["question_text"]) > 50 else item["question_text"],
                item["domain"],
                item["type"],
                f"{item['quality_score']:.2f}" if item['quality_score'] else "N/A",
            ]
            if show_related:
                row.append(str(item.get("related_event_count", 0)))
            table.add_row(*row)

        console.print(table)

    elif item_type == "events":
        events = db.get_many(Event)[:limit]

        table = Table(title=f"Events (showing {len(events)})", show_header=True)
        table.add_column("ID", style="cyan", no_wrap=True, max_width=16)
        table.add_column("Title", style="white", overflow="ellipsis", max_width=60)
        table.add_column("Domain", style="yellow")

        for event in events:
            table.add_row(
                event.id[:14] + "...",
                event.title[:57] + "..." if len(event.title) > 60 else event.title,
                event.domain.value if hasattr(event.domain, 'value') else str(event.domain)
            )

        console.print(table)

    elif item_type == "articles":
        articles = db.get_many(Article)[:limit]

        table = Table(title=f"Articles (showing {len(articles)})", show_header=True)
        table.add_column("ID", style="cyan", no_wrap=True, max_width=16)
        table.add_column("Title", style="white", overflow="ellipsis", max_width=60)
        table.add_column("Source", style="green")

        for article in articles:
            table.add_row(
                article.id[:14] + "...",
                article.title[:57] + "..." if len(article.title) > 60 else article.title,
                article.source or "N/A"
            )

        console.print(table)
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: questions, events, articles")
        raise typer.Exit(1)


@app.command()
def show(
    item_type: str = typer.Argument(..., help="Type: question, event"),
    item_id: str = typer.Argument(..., help="Item ID"),
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show detailed information about an item."""
    db, manager = get_db_and_manager(db_path)

    if item_type == "question":
        result = manager.show_question(item_id)
        if not result:
            console.print(f"[red]Question {item_id} not found[/red]")
            raise typer.Exit(1)

        if json_output:
            rprint(json.dumps(result, indent=2, default=str))
        else:
            q = result["question"]
            console.print(Panel(f"[bold cyan]{q['question_text']}[/bold cyan]", title=f"Question {item_id}"))
            console.print(f"\n[bold]Domain:[/bold] {q['domain']}")
            console.print(f"[bold]Type:[/bold] {q['question_type']}")
            console.print(f"[bold]Quality Score:[/bold] {q.get('quality_score', 'N/A')}")
            console.print(f"[bold]Resolution Date:[/bold] {q.get('resolution_date', 'N/A')}")
            console.print(f"[bold]Ground Truth:[/bold] {q.get('ground_truth', 'N/A')}")

            console.print(f"\n[bold]Related Entities:[/bold]")
            console.print(f"  Events: {len(result['events'])}")
            console.print(f"  Articles: {result['article_count']}")
            console.print(f"  Causal Hypotheses: {len(result['causal_hypotheses'])}")

            if result['causal_hypotheses']:
                console.print("\n[bold]Causal Hypotheses:[/bold]")
                for h in result['causal_hypotheses'][:5]:
                    console.print(f"  - {h['source_event_id']} -> {h['target_event_id']}")
                    console.print(f"    {h['relation_type']} (confidence: {h['confidence']:.2f})")

    elif item_type == "event":
        event = db.get(Event, item_id)
        if not event:
            console.print(f"[red]Event {item_id} not found[/red]")
            raise typer.Exit(1)

        if json_output:
            rprint(json.dumps(event.model_dump(), indent=2, default=str))
        else:
            console.print(Panel(f"[bold cyan]{event.title}[/bold cyan]", title=f"Event {item_id}"))
            console.print(f"\n[bold]Domain:[/bold] {event.domain.value if hasattr(event.domain, 'value') else event.domain}")
            console.print(f"[bold]Status:[/bold] {event.status.value if hasattr(event.status, 'value') else event.status}")
            console.print(f"[bold]Articles:[/bold] {len(event.article_ids)}")
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question, event")
        raise typer.Exit(1)


@app.command()
def analyze(
    item_type: str = typer.Argument(..., help="Type: question"),
    item_id: str = typer.Argument(..., help="Item ID"),
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
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
            console.print(Panel(f"[bold yellow]Cascade Analysis for Question {item_id}[/bold yellow]"))

            summary = result["summary"]
            console.print("\n[bold]Will Delete:[/bold]")
            console.print(f"  Events: {summary['will_delete_events']}")
            console.print(f"  Articles: {summary['will_delete_articles']}")
            console.print(f"  Causal Hypotheses: {summary['will_delete_hypotheses']}")

            console.print(f"\n[bold]Will Update:[/bold]")
            console.print(f"  Hypotheses (remove from discovered_by): {summary['will_update_hypotheses']}")

            console.print(f"\n[bold]Will Keep:[/bold]")
            console.print(f"  Pre-existing Events: {summary['will_keep_pre_existing_events']}")

            provenance = result["provenance_stats"]
            console.print(f"\n[bold]Provenance Tracking:[/bold]")
            console.print(f"  Articles tracked by field: {provenance['articles_by_field']}")
            console.print(f"  Articles tracked by metadata: {provenance['articles_by_metadata']}")
            console.print(f"  Events tracked by field: {provenance['events_by_field']}")
            console.print(f"  Events tracked by metadata: {provenance['events_by_metadata']}")
    else:
        console.print(f"[red]Unknown item type: {item_type}[/red]")
        console.print("Valid types: question")
        raise typer.Exit(1)


@app.command()
def delete(
    item_type: str = typer.Argument(..., help="Type: question, event"),
    item_id: str = typer.Argument(..., help="Item ID"),
    cascade: bool = typer.Option(True, "--cascade/--no-cascade", help="Delete related entities"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
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
    cascade: bool = typer.Option(True, "--cascade/--no-cascade", help="Delete related data"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
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
        console.print(Panel(f"[bold yellow]DRY RUN - Preview for Question {question_id}[/bold yellow]"))
        summary = result["summary"]
        console.print("\n[bold]Would Delete:[/bold]")
        console.print(f"  Articles: {summary['articles']}")
        console.print(f"  Events: {summary['events']}")
        console.print(f"  Causal Hypotheses: {summary['hypotheses_delete']}")
        console.print(f"\n[bold]Would Update:[/bold]")
        console.print(f"  Hypotheses (remove from discovered_by): {summary['hypotheses_update']}")
    else:
        console.print(f"[bold green]Evidence cleared for question {question_id}[/bold green]")
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
    db_path: str = typer.Option("worldreasoner.db", "--db", help="Database path"),
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
