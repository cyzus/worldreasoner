"""Forecasting commands for WorldReasoner CLI.

Provides commands to run LLM forecasts on selected questions
with interactive question selection.
"""

import asyncio
from typing import List, Optional
import typer
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.panel import Panel
from rich.table import Table

from src.core.database import GenericDatabase
from src.cli.core.options import db_option, source_option, domain_option, limit_option
from src.cli.core.question_selector import QuestionSelector
from src.cli.core.pipeline_runner import PipelineRunner, PipelineType, PipelineProgress
from src.domain.models import Question
from src.utils.logging import logger

app = typer.Typer(help="Forecasting commands")
console = Console()


@app.command()
def run(
    question_id: Optional[str] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID to forecast on",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Interactively select a question",
    ),
    source: Optional[str] = source_option(),
    domain: Optional[str] = domain_option(),
    has_evidence: bool = typer.Option(
        False,
        "--has-evidence",
        help="Only select from questions with evidence",
    ),
    limit: int = limit_option(),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use for forecasting (e.g., gpt-4o, gemini-2.0-flash)",
    ),
    mode: str = typer.Option(
        "container",
        "--mode",
        help=(
            "Forecasting mode:\n"
            "  knowledge_only — training knowledge only, no search tools\n"
            "  container      — temporal search (articles before simulated_date)\n"
            "  real_time      — live internet search, ignores simulated_date"
        ),
    ),
    enable_causal_tools: bool = typer.Option(
        False,
        "--enable-causal-tools",
        help="Enable causal reasoning tools (identify events, create causal links, inspect graph)",
    ),
    slot: str = typer.Option(
        "mid",
        "--slot",
        help="Simulated date position within forecast window: early (20%), mid (50%), late (80%)",
    ),
    skip_indexing: bool = typer.Option(
        False,
        "--skip-indexing",
        help="Skip automatic search indexing after completion",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output result as JSON (suppresses interactive prompts)",
    ),
    db_path: str = db_option(),
):
    """Run forecast on a question.

    Executes an LLM forecast on a selected question, optionally using
    web search tools to gather current information.

    Examples:
        # Interactively select a question
        wr forecast run --interactive

        # Forecast on a specific question
        wr forecast run -q q_abc123

        # Interactively select from politics questions with evidence
        wr forecast run -i --source polymarket --domain politics --has-evidence

        # Run with specific model and knowledge-only mode
        wr forecast run -q q_abc123 --model gemini-2.0-flash --knowledge-only
    """
    db = GenericDatabase(db_path)
    selector = QuestionSelector(db_path)

    # Determine which question to forecast on
    if question_id:
        # Use provided question ID
        question = db.get(Question, question_id)
        if not question:
            console.print(f"[red]Question not found: {question_id}[/red]")
            raise typer.Exit(1)

    elif interactive:
        # Interactive single selection
        console.print("[bold cyan]Select a question for forecasting[/bold cyan]")
        questions = selector.select_questions(
            source=source,
            domain=domain,
            has_evidence=has_evidence if has_evidence else None,
            limit=limit,
            multi_select=False,  # Single select for forecasting
        )

        if not questions:
            console.print("[yellow]No question selected[/yellow]")
            raise typer.Exit(0)

        question = questions[0]

    else:
        console.print("[red]Please provide either --question or --interactive[/red]")
        raise typer.Exit(1)

    if not json_output:
        # Show question details and confirm
        console.print("\n")
        selector.show_question_details(question.id)
        console.print("\n[bold]Configuration:[/bold]")
        console.print(f"  Model: {model or 'default'}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Causal tools: {'enabled' if enable_causal_tools else 'disabled'}")
        console.print(f"  Slot: {slot}")
        if not typer.confirm("\nRun forecast?"):
            raise typer.Exit(0)
        console.print("\n[bold cyan]Running forecast...[/bold cyan]")

    try:
        result = asyncio.run(
            _run_forecast_async(
                [question],
                db_path,
                model,
                mode,
                enable_causal_tools,
                slot,
                skip_indexing,
            )
        )

        if json_output:
            import json as _json
            import sys
            out = result.processed[0] if result.processed else (result.failed[0] if result.failed else {})
            sys.stdout.write(_json.dumps(out) + "\n")
        else:
            _display_forecast_result(result, question)

        if result.failure_count > 0:
            raise typer.Exit(1)

    except Exception as e:
        logger.error(f"Forecast failed: {e}")
        if json_output:
            import json as _json, sys
            sys.stdout.write(_json.dumps({"error": str(e)}) + "\n")
        else:
            console.print(f"\n[red]Forecast failed: {e}[/red]")
        raise typer.Exit(1)


async def _run_forecast_async(
    questions: List[Question],
    db_path: str,
    model: Optional[str] = None,
    mode: str = "container",
    enable_causal_tools: bool = False,
    slot: str = "mid",
    skip_indexing: bool = False,
):
    """Execute forecast on questions using PipelineRunner."""
    runner = PipelineRunner(db_path=db_path)
    question_ids = [q.id for q in questions]

    # Create progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Generating forecast...",
            total=len(questions),
        )

        def on_progress(p: PipelineProgress):
            progress.update(
                task,
                completed=p.current,
                description=f"[cyan]{p.stage}: {p.message}",
            )

        # Run forecast pipeline
        result = await runner.run(
            PipelineType.FORECAST,
            question_ids=question_ids,
            on_progress=on_progress,
            model=model,
            mode=mode,
            enable_causal_tools=enable_causal_tools,
            slot=slot,
            skip_indexing=skip_indexing,
        )

    return result


def _display_forecast_result(result, question: Question):
    """Display formatted forecast result for single question."""
    if result.processed:
        item = result.processed[0]
        panel = Panel(
            f"[green]Forecast generated[/green]\n"
            f"Question: {question.question_text}\n"
            f"Prediction: {item.get('prediction', 'N/A')}\n"
            f"Confidence: {item.get('confidence', 'N/A')}\n"
            f"Forecast ID: {item.get('forecast_id', 'N/A')}",
            title="Forecast Result",
            border_style="green",
        )
        console.print(panel)
    elif result.failed:
        item = result.failed[0]
        console.print(
            f"[red]Forecast failed: {item.get('error', 'Unknown error')}[/red]"
        )


@app.command()
def batch(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) to forecast (can be repeated)",
    ),
    source: Optional[str] = source_option(),
    domain: Optional[str] = domain_option(),
    limit: int = limit_option(default=20),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use",
    ),
    mode: str = typer.Option(
        "container",
        "--mode",
        help="Forecasting mode: knowledge_only, container, or real_time",
    ),
    enable_causal_tools: bool = typer.Option(
        False,
        "--enable-causal-tools",
        help="Enable causal reasoning tools",
    ),
    db_path: str = db_option(),
):
    """Run forecasts on multiple questions (batch mode).

    Examples:
        wr forecast batch -q q_1 -q q_2 -q q_3
        wr forecast batch --source polymarket --domain politics --limit 10
    """
    db = GenericDatabase(db_path)
    selector = QuestionSelector(db_path)

    # Determine which questions to forecast on
    if question_ids:
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

    else:
        # Filter-based selection
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            limit=limit,
            multi_select=True,
        )

        if not questions_to_process:
            console.print("[yellow]No questions match the filters[/yellow]")
            raise typer.Exit(0)

    # Confirm before running
    console.print(
        f"\n[bold]Will forecast on {len(questions_to_process)} question(s)[/bold]"
    )
    console.print(f"  Model: {model or 'default'}")
    console.print(f"  Mode: {mode}")
    console.print(f"  Causal tools: {'enabled' if enable_causal_tools else 'disabled'}")

    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    # Run batch forecasts
    console.print("\n[bold cyan]Running batch forecasts...[/bold cyan]")

    try:
        result = asyncio.run(
            _run_forecast_async(
                questions_to_process,
                db_path,
                model,
                mode,
                enable_causal_tools,
            )
        )

        # Display results
        _display_batch_forecast_results(result)

        if result.failure_count > 0:
            raise typer.Exit(1)

    except Exception as e:
        logger.error(f"Batch forecast failed: {e}")
        console.print(f"\n[red]Batch forecast failed: {e}[/red]")
        raise typer.Exit(1)


def _display_batch_forecast_results(result):
    """Display formatted batch forecast results."""
    console.print("\n[bold]Forecast Results:[/bold]")
    console.print(f"  Duration: {result.duration_seconds:.1f}s")
    console.print(f"  [green]Succeeded: {result.success_count}[/green]")
    console.print(f"  [yellow]Skipped: {result.skip_count}[/yellow]")
    console.print(f"  [red]Failed: {result.failure_count}[/red]")

    if result.processed:
        console.print("\n[bold green]Successfully Forecasted:[/bold green]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Question ID")
        table.add_column("Prediction")
        table.add_column("Confidence", justify="right")

        for item in result.processed:
            table.add_row(
                item["id"],
                str(item.get("prediction", "N/A")),
                f"{item.get('confidence', 0):.2f}",
            )
        console.print(table)

    if result.failed:
        console.print("\n[bold red]Failed:[/bold red]")
        for item in result.failed:
            console.print(f"  {item['id']}: {item.get('error', 'Unknown error')}")
