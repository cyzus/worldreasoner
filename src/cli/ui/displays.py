"""Shared display functions for question show/list.

Used by both `wr db` and `wr question` commands for consistent output.
"""

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from src.cli.core.question_manager import QuestionManager, QuestionFilter
from src.cli.ui.tables import display_question_table


def display_question_list(
    manager: QuestionManager,
    console: Console,
    domain: Optional[str] = None,
    limit: int = 50,
) -> None:
    """Display a filtered question table with evidence status."""
    filter_obj = QuestionFilter(domain=domain)
    questions = manager.query_questions(filter_obj, limit=limit)
    evidence_map = manager.get_evidence_status(questions)
    display_question_table(questions, evidence_map, console)


def display_question_detail(
    manager: QuestionManager,
    console: Console,
    item_id: str,
    json_output: bool = False,
) -> None:
    """Display detailed information about a single question."""
    result = manager.show_question(item_id)
    if not result:
        console.print(f"[red]Question {item_id} not found[/red]")
        raise SystemExit(1)

    if json_output:
        rprint(json.dumps(result, indent=2, default=str))
        return

    q = result["question"]
    console.print(
        Panel(
            f"[bold cyan]{q['question_text']}[/bold cyan]",
            title=f"Question {item_id}",
        )
    )
    console.print(f"\n[bold]Domain:[/bold] {q['domain']}")
    console.print(f"[bold]Type:[/bold] {q['question_type']}")
    console.print(f"[bold]Quality Score:[/bold] {q.get('quality_score', 'N/A')}")
    console.print(f"[bold]Resolution Date:[/bold] {q.get('resolution_date', 'N/A')}")
    console.print(f"[bold]Ground Truth:[/bold] {q.get('ground_truth', 'N/A')}")

    console.print("\n[bold]Related Entities:[/bold]")
    console.print(f"  Events: {len(result['events'])}")
    console.print(f"  Articles: {result['article_count']}")
    console.print(f"  Causal Hypotheses: {len(result['causal_hypotheses'])}")

    if result["causal_hypotheses"]:
        console.print("\n[bold]Causal Hypotheses:[/bold]")
        for h in result["causal_hypotheses"][:5]:
            console.print(f"  - {h['source_event_id']} -> {h['target_event_id']}")
            console.print(
                f"    {h['relation_type']} (confidence: {h['confidence']:.2f})"
            )


def display_question_stats(
    manager: QuestionManager,
    console: Console,
) -> None:
    """Display question-focused statistics."""
    stats_data = manager.get_stats()

    table = Table(title="Question Statistics", show_header=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="green")

    table.add_row("Questions", str(stats_data.get("questions", 0)))
    table.add_row("Events", str(stats_data.get("events", 0)))
    table.add_row("Articles", str(stats_data.get("articles", 0)))
    table.add_row("Causal Hypotheses", str(stats_data.get("causal_hypotheses", 0)))

    console.print(table)
