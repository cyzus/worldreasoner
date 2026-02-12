"""Rich reporting for auto-benchmark results.

Provides formatted table output for comparing experimental conditions.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.domain.evaluation.auto_benchmark import AutoBenchmarkResult


console = Console()


def print_auto_benchmark_report(result: AutoBenchmarkResult) -> None:
    """Print a full auto-benchmark report with Rich formatting."""
    # Header
    console.print(
        Panel(
            f"Run ID: {result.run_id}\n"
            f"Duration: {result.duration_seconds:.1f}s\n"
            f"Conditions: {len(result.configuration['conditions'])}\n"
            f"Models: {', '.join(result.configuration['models'])}\n"
            f"Questions: {result.configuration['question_count']}",
            title="Auto-Benchmark Results",
            border_style="cyan",
        )
    )

    # Per-condition tables
    for cond_name, model_results in result.condition_results.items():
        for model_name, cond_result in model_results.items():
            table = Table(
                title=f"{cond_result.display_name} | {model_name}",
                show_header=True,
                header_style="bold cyan",
            )
            table.add_column("Metric", style="bold")
            table.add_column("Value", justify="right")

            table.add_row("Total Questions", str(cond_result.total_questions))
            table.add_row("Successful", f"[green]{cond_result.successful}[/green]")
            table.add_row("Failed", f"[red]{cond_result.failed}[/red]")
            table.add_row("Accuracy", f"{cond_result.accuracy:.1%}")

            brier_str = (
                f"{cond_result.avg_brier_score:.4f}"
                if cond_result.avg_brier_score is not None
                else "N/A"
            )
            table.add_row("Avg Brier Score", brier_str)

            log_str = (
                f"{cond_result.avg_log_score:.4f}"
                if cond_result.avg_log_score is not None
                else "N/A"
            )
            table.add_row("Avg Log Score", log_str)

            console.print(table)
            console.print()

    # Leaderboard
    print_leaderboard(result.comparative_summary)


def print_leaderboard(comparative_summary: dict) -> None:
    """Print the comparative leaderboard table."""
    leaderboard = comparative_summary.get("leaderboard", [])
    if not leaderboard:
        console.print("[yellow]No leaderboard data available[/yellow]")
        return

    table = Table(
        title="Comparative Leaderboard",
        show_header=True,
        header_style="bold green",
    )
    table.add_column("Rank", justify="center", style="bold")
    table.add_column("Condition")
    table.add_column("Model")
    table.add_column("Accuracy", justify="right")
    table.add_column("Brier", justify="right")
    table.add_column("Log Score", justify="right")
    table.add_column("Questions", justify="right")

    for i, entry in enumerate(leaderboard, 1):
        brier_str = (
            f"{entry['avg_brier_score']:.4f}"
            if entry.get("avg_brier_score") is not None
            else "N/A"
        )
        log_str = (
            f"{entry['avg_log_score']:.4f}"
            if entry.get("avg_log_score") is not None
            else "N/A"
        )
        questions_str = f"{entry['successful']}/{entry['total_questions']}"

        # Highlight top entry
        style = "bold green" if i == 1 else None

        table.add_row(
            str(i),
            entry["display_name"],
            entry["model"],
            f"{entry['accuracy']:.1%}",
            brier_str,
            log_str,
            questions_str,
            style=style,
        )

    console.print(table)
