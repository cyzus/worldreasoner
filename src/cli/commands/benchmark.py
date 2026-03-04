"""Benchmark commands for WorldReasoner CLI.

Provides commands to run auto-benchmark experiments across
multiple conditions, models, and questions.
"""

import asyncio
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from src.cli.core.options import db_option, source_option, domain_option, yes_option
from src.core.database import GenericDatabase
from src.domain.evaluation.auto_benchmark import (
    AutoBenchmarkProgress,
    AutoBenchmarkService,
)
from src.domain.evaluation.auto_benchmark_reporting import (
    print_auto_benchmark_report,
)
from src.domain.evaluation.conditions import ConditionName, get_conditions
from src.config import get_config
from src.utils.logging import logger

app = typer.Typer(help="LLM benchmark research commands")
console = Console()


@app.command()
def run(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) (repeatable)",
    ),
    models: Optional[List[str]] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model ID(s) (repeatable, defaults to config model)",
    ),
    condition_names: Optional[List[str]] = typer.Option(
        None,
        "--condition",
        "-c",
        help="Condition name(s) (repeatable, defaults to all 6)",
    ),
    offset_days: int = typer.Option(
        0,
        "--offset-days",
        help="Days before resolution date for simulated date",
    ),
    max_questions: Optional[int] = typer.Option(
        None,
        "--max-questions",
        "-n",
        help="Limit number of questions",
    ),
    source: Optional[str] = source_option(),
    domain: Optional[str] = domain_option(),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Skip already-completed triples",
    ),
    min_evidence: int = typer.Option(
        3,
        "--min-evidence",
        help="Minimum articles+events required per question (0 to include all)",
    ),
    output_dir: str = typer.Option(
        "benchmarks",
        "--output-dir",
        help="Output directory for results",
    ),
    db_path: str = db_option(),
    yes: bool = yes_option(),
):
    """Run auto-benchmark across conditions, models, and questions.

    Runs all 6 experimental conditions (or a subset) across one or more
    models and all resolved questions, producing comparative results.

    Examples:
        # Run all conditions with default model on all resolved questions
        wr benchmark run -y

        # Single condition, single model, 1 question
        wr benchmark run -c vanilla_llm -m gemini/gemini-2.5-flash -n 1 -y

        # Multiple models
        wr benchmark run -m gemini/gemini-2.5-flash -m gpt-5 -n 5 -y

        # Resume interrupted run
        wr benchmark run --resume -y
    """
    config = get_config()

    # Resolve models
    model_list = models or [config.llm.model]

    # Validate conditions
    try:
        conditions = get_conditions(condition_names)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Get resolved questions
    service = AutoBenchmarkService(
        db_path=db_path, config=config, output_dir=output_dir
    )
    questions = service.get_resolved_questions(
        question_ids=question_ids,
        min_context_items=min_evidence,
        max_questions=max_questions,
        source=source,
        domain=domain,
    )

    if not questions:
        console.print("[red]No resolved questions found matching criteria[/red]")
        raise typer.Exit(1)

    # Show plan
    total_triples = len(conditions) * len(model_list) * len(questions)
    console.print("\n[bold cyan]Auto-Benchmark Plan[/bold cyan]")
    console.print(f"  Conditions: {', '.join(c.display_name for c in conditions)}")
    console.print(f"  Models: {', '.join(model_list)}")
    console.print(f"  Questions: {len(questions)}")
    console.print(f"  Total runs: {total_triples}")
    console.print(f"  Offset days: {offset_days}")
    console.print(f"  Resume: {resume}")
    console.print(f"  Output: {output_dir}/")

    if not yes and not typer.confirm("\nProceed with benchmark?"):
        raise typer.Exit(0)

    # Run benchmark with progress
    console.print("\n[bold cyan]Running auto-benchmark...[/bold cyan]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Starting...",
                total=total_triples,
            )

            def on_progress(p: AutoBenchmarkProgress):
                progress.update(
                    task,
                    completed=p.overall_current,
                    description=(
                        f"[{p.condition_index}/{p.condition_total}] "
                        f"{p.condition_name} | {p.model_name} | {p.question_id}"
                    ),
                )

            result = service.run_auto_benchmark(
                questions=questions,
                models=model_list,
                conditions=conditions,
                offset_days=offset_days,
                on_progress=on_progress,
                resume=resume,
            )

        # Display results
        console.print()
        print_auto_benchmark_report(result)

        console.print(
            f"\n[green]Results saved to {output_dir}/{result.run_id}.json[/green]"
        )

    except Exception as e:
        logger.error(f"Auto-benchmark failed: {e}")
        console.print(f"\n[red]Auto-benchmark failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def conditions():
    """List available experimental conditions."""
    from rich.table import Table

    all_conditions = get_conditions()

    table = Table(
        title="Experimental Conditions",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="bold")
    table.add_column("Display Name")
    table.add_column("Mode")
    table.add_column("Causal Tools", justify="center")
    table.add_column("Oracle", justify="center")
    table.add_column("Max Steps", justify="right")
    table.add_column("Description")

    for c in all_conditions:
        table.add_row(
            c.name.value,
            c.display_name,
            c.mode,
            "Yes" if c.enable_causal_tools else "No",
            "Yes" if c.is_oracle else "No",
            str(c.max_steps),
            c.description,
        )

    console.print(table)
