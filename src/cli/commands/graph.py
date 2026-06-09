import json as _json
import sys
import typer
from rich.console import Console

from src.config import get_config
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.utils.logging import setup_logging
from src.cli.core.options import db_option

app = typer.Typer(help="Manage graph building and auditing.")
console = Console()


@app.command("build")
def build_graphs(
    db_path: str = db_option(),
    limit: int = typer.Option(10, "--limit", "-n", help="Max questions to process"),
    question_id: str = typer.Option(
        None, "--question", "-q", help="Specific question ID"
    ),
    model_id: str = typer.Option(
        None,
        "--model",
        help="Model ID (defaults to config.llm.model)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Rebuild graph even if one already exists"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output result as JSON"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Build causal graphs for questions that have a causal explanation.

    Examples:
        # Build graphs for up to 20 pending questions
        wr graph build -n 20

        # Build graph for a specific question
        wr graph build -q <question_id>

        # Force rebuild an existing graph
        wr graph build -q <question_id> --force

        # Machine-readable output
        wr graph build -n 10 --json
    """
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level=level)
    from src.pipelines.graph_builder.pipeline import GraphBuilderPipeline

    selected_model_id = model_id or get_config().llm.model
    pipeline = GraphBuilderPipeline(
        db_path=db_path,
        model_id=selected_model_id,
        temperature=0.2,
    )

    if question_id:
        db = GenericDatabase(db_path)
        q = db.get(Question, question_id)
        if not q:
            if json_output:
                sys.stdout.write(_json.dumps({"error": f"Question {question_id} not found"}) + "\n")
            else:
                console.print(f"[red]Question {question_id} not found.[/red]")
            raise typer.Exit(1)

        if q.graph_built and not force:
            msg = f"Question {question_id} already has a graph. Use --force to rebuild."
            if json_output:
                sys.stdout.write(_json.dumps({"status": "skipped", "reason": msg}) + "\n")
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            raise typer.Exit(0)

        if not q.causal_explanation:
            msg = f"Question {question_id} has no causal_explanation. Run evidence pipeline first."
            if json_output:
                sys.stdout.write(_json.dumps({"error": msg}) + "\n")
            else:
                console.print(f"[red]{msg}[/red]")
            raise typer.Exit(1)

        if not json_output:
            console.print(f"Building graph for question: {question_id}...")
        success = pipeline._process_single_question(q)
        result = {"question_id": question_id, "status": "success" if success else "failed"}
        if json_output:
            sys.stdout.write(_json.dumps(result) + "\n")
        elif success:
            console.print(f"[green]Graph built for {question_id}[/green]")
        else:
            console.print(f"[red]Failed to build graph for {question_id}[/red]")
        raise typer.Exit(0 if success else 1)

    else:
        if not json_output:
            console.print(f"Building graphs for up to {limit} pending questions...")
        results = pipeline.process_pending(limit=limit)
        if json_output:
            sys.stdout.write(_json.dumps(results) + "\n")
        else:
            console.print("\n[bold]Results:[/bold]")
            console.print(f"  Processed: {results['processed']}")
            console.print(f"  Success:   [green]{results['success']}[/green]")
            console.print(f"  Failed:    [red]{results['failed']}[/red]")


@app.command("audit")
def audit_graph(
    db_path: str = db_option(),
    question_id: str = typer.Option(
        ..., "--question", "-q", help="Question ID to audit"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output result as JSON"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Audit a causal graph for quality issues.

    Checks for chronology violations, orphaned events, missing links,
    and other structural problems.

    Examples:
        wr graph audit -q <question_id>
        wr graph audit -q <question_id> --json
    """
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level=level)
    from src.pipelines.graph_builder.audit import GraphAuditPipeline

    pipeline = GraphAuditPipeline(db_path=db_path)
    result = pipeline.audit_question(question_id)

    if json_output:
        sys.stdout.write(_json.dumps(result) + "\n")
        raise typer.Exit(0 if result.get("status") != "error" else 1)

    if result.get("status") == "error":
        console.print(f"[red]{result.get('message')}[/red]")
        raise typer.Exit(1)

    console.print(f"Audit for question {question_id}:")
    console.print(f"  Events:     {result.get('events_count', 0)}")
    console.print(f"  Hypotheses: {result.get('hypotheses_count', 0)}")

    if result.get("status") == "pass":
        console.print("[green]PASS[/green] — no issues detected.")
    else:
        console.print("[red]FAIL[/red] — issues detected:")
        for issue in result.get("issues", []):
            console.print(f"  - {issue}")
        raise typer.Exit(1)
