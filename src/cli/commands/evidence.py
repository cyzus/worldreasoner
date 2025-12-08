"""Evidence pipeline commands for WorldReasoner CLI.

Provides commands to run and manage the evidence collection pipeline,
including interactive question selection and progress tracking.
"""

import asyncio
from typing import List, Optional
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

from src.core.database import GenericDatabase
from src.cli.core.question_selector import QuestionSelector
from src.cli.core.question_manager import QuestionManager
from src.domain.models import Question
from src.utils.logging import logger

app = typer.Typer(help="Evidence pipeline commands")
console = Console()


@app.command()
def run(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Specific question ID(s) to process (can be repeated)",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Interactively select questions",
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
    resolved_only: bool = typer.Option(
        False,
        "--resolved",
        help="Only process resolved questions",
    ),
    has_evidence: bool = typer.Option(
        False,
        "--has-evidence",
        help="Only process questions with existing evidence",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        help="Maximum number of questions to process",
    ),
    force_reprocess: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force reprocessing even if evidence exists",
    ),
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
):
    """Run evidence pipeline on selected questions.

    Examples:
        # Interactively select questions from polymarket
        wr evidence run --interactive --source polymarket

        # Process specific questions
        wr evidence run -q q_abc123 -q q_def456

        # Process all resolved politics questions
        wr evidence run --source polymarket --domain politics --resolved

        # Process questions with interactive filtering
        wr evidence run -i --domain politics --limit 20
    """
    db = GenericDatabase(db_path)
    selector = QuestionSelector(db_path)

    # Determine which questions to process
    if question_ids:
        # Use provided question IDs
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

    elif interactive:
        # Interactive selection
        console.print("[bold cyan]Select questions for evidence pipeline[/bold cyan]")
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence if not has_evidence else None,
            limit=limit,
            multi_select=True,
        )

        if not questions_to_process:
            console.print("[yellow]No questions selected[/yellow]")
            raise typer.Exit(0)

    else:
        # Non-interactive selection with filters
        questions_to_process = selector.select_questions(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence if not has_evidence else None,
            limit=limit,
            multi_select=True,
        )

        if not questions_to_process:
            console.print("[yellow]No questions match the filters[/yellow]")
            raise typer.Exit(0)

    # Confirm before running
    console.print(f"\n[bold]Will process {len(questions_to_process)} question(s)[/bold]")
    
    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    # Run evidence pipeline
    console.print("\n[bold cyan]Starting evidence pipeline...[/bold cyan]")

    try:
        _run_evidence_pipeline(
            questions_to_process,
            db_path,
            force_reprocess,
        )
        console.print("\n[green]Evidence pipeline completed successfully[/green]")
    except Exception as e:
        logger.error(f"Evidence pipeline failed: {e}")
        console.print(f"\n[red]Evidence pipeline failed: {e}[/red]")
        raise typer.Exit(1)


def _run_evidence_pipeline(
    questions: List[Question],
    db_path: str,
    force_reprocess: bool = False,
):
    """Execute the evidence pipeline on selected questions.
    
    This is a placeholder that will be updated to integrate with
    the actual EvidencePipeline once PipelineRunner is ready.
    """
    from src.utils.logging import logger

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Processing questions...",
            total=len(questions),
        )

        for i, question in enumerate(questions, 1):
            progress.update(
                task,
                description=f"[cyan]Processing {i}/{len(questions)}: {question.id}",
            )

            try:
                # TODO: Integrate with actual EvidencePipeline
                # For now, just log and simulate processing
                logger.info(f"Would process question: {question.id}")
                progress.advance(task)

            except Exception as e:
                logger.error(f"Failed to process {question.id}: {e}")
                console.print(f"[red]Failed to process {question.id}: {e}[/red]")


@app.command()
def clear(
    question_ids: List[str] = typer.Option(
        ...,
        "--question",
        "-q",
        help="Question ID(s) to clear evidence for (can be repeated)",
    ),
    cascade: bool = typer.Option(
        True,
        "--cascade",
        help="Also delete orphaned events and articles",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without making changes",
    ),
    db_path: str = typer.Option(
        "worldreasoner.db",
        "--db",
        help="Path to the database",
    ),
):
    """Clear evidence data for questions.

    Removes causal hypotheses and optionally cascades to orphaned events/articles.
    The questions themselves are kept - only evidence data is removed.

    Examples:
        wr evidence clear -q q_abc123
        wr evidence clear -q q_1 -q q_2 -q q_3 --cascade
        wr evidence clear -q q_abc123 --dry-run
    """
    if not question_ids:
        console.print("[red]Please provide at least one question ID[/red]")
        raise typer.Exit(1)

    db = GenericDatabase(db_path)
    manager = QuestionManager(db)

    console.print(f"\n[bold]Clear evidence for {len(question_ids)} question(s)[/bold]")
    console.print(f"  Cascade: {cascade}")
    console.print(f"  Dry run: {dry_run}")

    if not typer.confirm("Continue?"):
        raise typer.Exit(0)

    console.print("[cyan]Clearing evidence...[/cyan]\n")
    
    total_stats = {
        "articles": 0,
        "events": 0,
        "hypotheses_delete": 0,
        "hypotheses_update": 0,
    }
    
    failed = []

    for question_id in question_ids:
        result = manager.clear_evidence(question_id, cascade=cascade, dry_run=dry_run)

        if "error" in result:
            console.print(f"[red]Error processing {question_id}: {result['error']}[/red]")
            failed.append({"id": question_id, "error": result["error"]})
            continue

        if dry_run:
            summary = result["summary"]
            console.print(f"[yellow][DRY RUN] {question_id}:[/yellow]")
            console.print(f"  Articles: {summary['articles']}")
            console.print(f"  Events: {summary['events']}")
            console.print(f"  Hypotheses to delete: {summary['hypotheses_delete']}")
            console.print(f"  Hypotheses to update: {summary['hypotheses_update']}")
            
            for key in total_stats:
                total_stats[key] += summary.get(key, 0)
        else:
            summary = result["summary"]
            console.print(f"[green]Cleared {question_id}[/green]")
            console.print(f"  Articles: {summary['articles']}")
            console.print(f"  Events: {summary['events']}")
            console.print(f"  Hypotheses deleted: {summary['hypotheses_delete']}")
            console.print(f"  Hypotheses updated: {summary['hypotheses_update']}")
            
            for key in total_stats:
                total_stats[key] += summary.get(key, 0)

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Articles cleared: {total_stats['articles']}")
    console.print(f"  Events cleared: {total_stats['events']}")
    console.print(f"  Hypotheses deleted: {total_stats['hypotheses_delete']}")
    console.print(f"  Hypotheses updated: {total_stats['hypotheses_update']}")
    
    if failed:
        console.print(f"\n[red]Failed to clear {len(failed)} question(s)[/red]")
        for item in failed:
            console.print(f"  {item['id']}: {item['error']}")
        raise typer.Exit(1)
    
    if dry_run:
        console.print("\n[yellow]Dry run completed - no changes made[/yellow]")
    else:
        console.print("\n[green]Evidence cleared successfully[/green]")
