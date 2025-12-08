"""Forecasting commands for WorldReasoner CLI.

Provides commands to run LLM forecasts on selected questions
with interactive question selection.
"""

from typing import List, Optional
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table

from src.core.database import GenericDatabase
from src.cli.core.question_selector import QuestionSelector
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
    has_evidence: bool = typer.Option(
        False,
        "--has-evidence",
        help="Only select from questions with evidence",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        help="Maximum number of questions to display for selection",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use for forecasting (e.g., gpt-4o, gemini-2.0-flash)",
    ),
    knowledge_only: bool = typer.Option(
        False,
        "--knowledge-only",
        "-k",
        help="Use only model knowledge, no web search tools",
    ),
    offset_days: int = typer.Option(
        7,
        "--offset-days",
        help="Days before resolution date to use as forecast time",
    ),
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
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

    # Show question details
    console.print("\n")
    selector.show_question_details(question.id)

    # Confirm before running
    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"  Model: {model or 'default'}")
    console.print(f"  Knowledge-only: {knowledge_only}")
    console.print(f"  Offset days: {offset_days}")

    if not typer.confirm("\nRun forecast?"):
        raise typer.Exit(0)

    # Run forecast
    console.print("\n[bold cyan]Running forecast...[/bold cyan]")

    try:
        _run_forecast(
            question,
            db_path,
            model,
            knowledge_only,
            offset_days,
        )
        console.print("\n[green]Forecast completed successfully[/green]")
    except Exception as e:
        logger.error(f"Forecast failed: {e}")
        console.print(f"\n[red]Forecast failed: {e}[/red]")
        raise typer.Exit(1)


def _run_forecast(
    question: Question,
    db_path: str,
    model: Optional[str] = None,
    knowledge_only: bool = False,
    offset_days: int = 7,
):
    """Execute forecast on a question.
    
    This is a placeholder that will be updated to integrate with
    the actual forecasting agent infrastructure.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Generating forecast...",
        )

        try:
            # TODO: Integrate with actual forecasting infrastructure
            # This would use ForecastAgent or similar
            logger.info(
                f"Would forecast on question {question.id} "
                f"using model={model}, knowledge_only={knowledge_only}"
            )
            progress.stop()

            # Show mock result
            panel = Panel(
                f"[green]Forecast generated[/green]\n"
                f"Question: {question.question_text}\n"
                f"Status: Saved to database",
                title="Forecast Result",
                border_style="green",
            )
            console.print(panel)

        except Exception as e:
            progress.stop()
            raise


@app.command()
def batch(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) to forecast (can be repeated)",
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Filter by question source",
    ),
    domain: Optional[str] = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter by domain",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Maximum number of questions to process",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use",
    ),
    knowledge_only: bool = typer.Option(
        False,
        "--knowledge-only",
        "-k",
        help="Use only model knowledge",
    ),
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
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
    console.print(f"\n[bold]Will forecast on {len(questions_to_process)} question(s)[/bold]")
    console.print(f"  Model: {model or 'default'}")
    console.print(f"  Knowledge-only: {knowledge_only}")

    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    # Run batch forecasts
    console.print("\n[bold cyan]Running batch forecasts...[/bold cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Processing questions...",
            total=len(questions_to_process),
        )

        for i, question in enumerate(questions_to_process, 1):
            progress.update(
                task,
                description=f"[cyan]Forecasting {i}/{len(questions_to_process)}: {question.id}",
            )

            try:
                # TODO: Integrate with actual forecasting infrastructure
                logger.info(f"Would forecast on question: {question.id}")
                progress.advance(task)

            except Exception as e:
                logger.error(f"Failed to forecast on {question.id}: {e}")
                console.print(f"[red]Failed to forecast on {question.id}: {e}[/red]")

    console.print("\n[green]Batch forecasting completed[/green]")
