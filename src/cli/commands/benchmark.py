"""Benchmark commands for WorldReasoner CLI.

Provides commands to run auto-benchmark experiments across
multiple conditions, models, and questions.
"""

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
from src.domain.evaluation.auto_benchmark import (
    AutoBenchmarkProgress,
    AutoBenchmarkService,
)
from src.domain.evaluation.auto_benchmark_reporting import (
    print_auto_benchmark_report,
)
from src.domain.evaluation.conditions import get_conditions
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
    question_file: Optional[str] = typer.Option(
        None,
        "--question-file",
        "-Q",
        help="File with one question ID per line",
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
    slot: str = typer.Option(
        "mid",
        "--slot",
        help="Simulated date position within forecast window: early (20%), mid (50%), late (80%)",
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
    max_workers: int = typer.Option(
        4,
        "--workers",
        "-w",
        help="Number of parallel workers",
    ),
    output_dir: str = typer.Option(
        "experiments/benchmarks",
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

    # Merge question IDs from file
    if question_file:
        from pathlib import Path
        file_ids = [l.strip() for l in Path(question_file).read_text().splitlines() if l.strip()]
        question_ids = list(question_ids or []) + file_ids

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
    console.print(f"  Slot: {slot}")
    console.print(f"  Resume: {resume}")
    console.print(f"  Workers: {max_workers}")
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
                slot=slot,
                on_progress=on_progress,
                resume=resume,
                max_workers=max_workers,
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
def status(
    db_path: str = db_option(),
    domain: Optional[str] = domain_option(),
    source: Optional[str] = source_option(),
):
    """Show which questions are ready to benchmark.

    Uses the same readiness definition as the frontend:
      - Complete (Ready): evidence_satisfied=True AND graph_built=True
      - Needs Graph:      evidence_satisfied=True AND graph_built=False
      - Needs Evidence:   evidence_satisfied=False (articles < threshold or no causal_explanation)

    Examples:
        wr benchmark status --db combined.db
        wr benchmark status --db combined.db --domain politics
        wr benchmark status --db combined.db --source news
    """
    from collections import defaultdict
    from rich.table import Table
    from src.core.database import GenericDatabase
    from src.domain.models import Article, Question
    from src.services.question_monitor_service import QuestionMonitorService
    from datetime import datetime, timezone

    db = GenericDatabase(db_path)
    monitor = QuestionMonitorService(db)
    now = datetime.now(timezone.utc)

    all_questions = db.get_many(Question)

    if domain:
        all_questions = [
            q for q in all_questions
            if (q.domain.value if hasattr(q.domain, "value") else str(q.domain)) == domain
        ]
    if source:
        all_questions = [q for q in all_questions if q.source == source]

    # Bulk-compute evidence_satisfied via QuestionMonitorService (same logic as frontend)
    evidence_satisfied_ids = monitor.get_processed_question_ids(all_questions)

    # Categorise — same order as get_resolved_questions():
    # ground_truth → resolution_date → evidence_satisfied → graph_built
    ready = []
    no_ground_truth = []
    not_resolved = []
    needs_evidence = []
    needs_graph = []

    for q in all_questions:
        if q.ground_truth is None:
            no_ground_truth.append(q)
            continue
        if q.resolution_date is None or q.resolution_date > now:
            not_resolved.append(q)
            continue
        if q.id not in evidence_satisfied_ids:
            needs_evidence.append(q)
            continue
        if not q.graph_built:
            needs_graph.append(q)
            continue
        ready.append(q)

    # Summary table
    summary = Table(title=f"Benchmark Readiness — {db_path}", show_header=True, header_style="bold cyan")
    summary.add_column("Status")
    summary.add_column("Count", justify="right")
    summary.add_column("Notes")

    summary.add_row("[green]Ready[/green]", str(len(ready)), "evidence_satisfied + graph_built + resolved + ground_truth")
    summary.add_row("[yellow]Needs Graph[/yellow]", str(len(needs_graph)), "evidence_satisfied=True but graph_built=False")
    summary.add_row("[yellow]Needs Evidence[/yellow]", str(len(needs_evidence)), "articles < min or no causal_explanation")
    summary.add_row("[dim]Not resolved[/dim]", str(len(not_resolved)), "resolution_date in future")
    summary.add_row("[dim]No ground truth[/dim]", str(len(no_ground_truth)), "missing ground_truth field")
    console.print(summary)

    if not ready:
        return

    # Domain breakdown of ready questions
    by_domain: dict = defaultdict(int)
    by_source: dict = defaultdict(int)
    for q in ready:
        d = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
        by_domain[d] += 1
        by_source[q.source or "unknown"] += 1

    domain_table = Table(title="Ready — by domain", show_header=True, header_style="bold")
    domain_table.add_column("Domain")
    domain_table.add_column("Count", justify="right")
    for d, n in sorted(by_domain.items(), key=lambda x: -x[1]):
        domain_table.add_row(d, str(n))
    console.print(domain_table)

    source_table = Table(title="Ready — by source", show_header=True, header_style="bold")
    source_table.add_column("Source")
    source_table.add_column("Count", justify="right")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        source_table.add_row(s, str(n))
    console.print(source_table)


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


@app.command()
def evaluate(
    db_path: str = db_option("combined.db"),
    conditions: Optional[List[str]] = typer.Option(
        None,
        "--condition",
        "-c",
        help="Condition(s) to evaluate (default: all conditions with data)",
    ),
    include_ids: Optional[str] = typer.Option(
        None,
        "--include-ids",
        help="File with one question ID per line to restrict evaluation",
    ),
    models: Optional[List[str]] = typer.Option(
        None, "--model", "-m", help="Only include forecasts from these model id(s)"
    ),
    exclude_models: Optional[List[str]] = typer.Option(
        None, "--exclude-model", help="Model id(s) to exclude"
    ),
    output_dir: str = typer.Option(
        "experiments/evaluation",
        "--output-dir",
        "-o",
        help="Directory for JSON/Markdown reports",
    ),
):
    """Score benchmark forecasts and write per-condition JSON + Markdown reports.

    Examples:
        wr benchmark evaluate
        wr benchmark evaluate --condition vanilla_llm --condition structured_scenario
        wr benchmark evaluate --db other.db
    """
    from pathlib import Path

    from src.domain.evaluation.benchmark_eval import evaluate_benchmark

    evaluate_benchmark(
        db_path=db_path,
        conditions=conditions,
        include_ids_path=include_ids,
        models=models,
        exclude_models=exclude_models,
        output_dir=Path(output_dir),
        log=console.print,
    )
