import typer
from rich.console import Console

from src.core.database import GenericDatabase
from src.domain.models import Question
from src.pipelines.graph_builder.pipeline import GraphBuilderPipeline
from src.utils.logging import setup_logging

app = typer.Typer(help="Manage graph building and auditing.")
console = Console()


@app.command("build")
def build_graphs(
    db_path: str = typer.Option(
        "data/worldreasoner.db", "--db", help="Path to database"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Max questions to process"),
    question_id: str = typer.Option(
        None, "--question", "-q", help="Specific question ID"
    ),
    model_id: str = typer.Option(
        "claude-3-5-sonnet-20241022", "--model", help="Model ID"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Run the GraphBuilder pipeline on pending questions."""
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level=level)

    pipeline = GraphBuilderPipeline(db_path=db_path, model_id=model_id, temperature=0.2)

    if question_id:
        db = GenericDatabase(db_path)
        q = db.get(Question, question_id)
        if not q:
            console.print(f"[red]Question {question_id} not found.[/red]")
            raise typer.Exit(1)

        if q.graph_built:
            console.print(
                f"[yellow]Question {question_id} already has a graph built. Use --force to rebuild (not implemented yet).[/yellow]"
            )
            raise typer.Exit(1)

        if not q.causal_explanation:
            console.print(
                f"[red]Question {question_id} lacks a causal_explanation. Run hindsight agent first.[/red]"
            )
            raise typer.Exit(1)

        console.print(f"Building graph for single question: {question_id}...")
        success = pipeline._process_single_question(q)
        if success:
            console.print(f"[green]Successfully built graph for {question_id}[/green]")
        else:
            console.print(f"[red]Failed to build graph for {question_id}[/red]")

    else:
        console.print(
            f"Running graph builder pipeline on up to {limit} pending questions..."
        )
        results = pipeline.process_pending(limit=limit)
        console.print("\n[bold]Pipeline Results:[/bold]")
        console.print(f"Processed: {results['processed']}")
        console.print(f"Success: [green]{results['success']}[/green]")
        console.print(f"Failed: [red]{results['failed']}[/red]")


@app.command("audit")
def audit_graph(
    db_path: str = typer.Option(
        "data/worldreasoner.db", "--db", help="Path to database"
    ),
    question_id: str = typer.Option(
        ..., "--question", "-q", help="Specific question ID"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Run the Graph Audit pipeline on a specific question."""
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level=level)
    from src.pipelines.graph_builder.audit import GraphAuditPipeline

    pipeline = GraphAuditPipeline(db_path=db_path)
    result = pipeline.audit_question(question_id)

    if result.get("status") == "error":
        console.print(f"[red]{result.get('message')}[/red]")
        raise typer.Exit(1)

    console.print(f"Audit results for question {question_id}:")
    console.print(f"Events found: {result.get('events_count', 0)}")
    console.print(f"Hypotheses found: {result.get('hypotheses_count', 0)}")

    if result.get("status") == "pass":
        console.print("[green]PASS[/green] - No issues detected.")
    else:
        console.print("[red]FAIL[/red] - Issues detected:")
        for issue in result.get("issues", []):
            console.print(f"  - {issue}")
        raise typer.Exit(1)
