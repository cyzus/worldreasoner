"""Main entry point for the WorldReasoner unified CLI.

This module provides the `wr` command with subcommands for:
- Database management (wr db)
- Evidence pipeline (wr evidence) - to be added in Phase 3
- Forecasting (wr forecast) - to be added in Phase 3
- Benchmarking (wr benchmark) - to be added in Phase 3
- And more...

Usage:
    wr --help
    wr db stats
    wr db list questions --domain politics
"""

import typer
from rich.console import Console

from src.cli.commands import benchmark, db, evidence, forecast, graph, question
from src.core.database import GenericDatabase
from src.config import get_config

# Create the main Typer app
app = typer.Typer(
    name="wr",
    help="WorldReasoner CLI - LLM Forecasting Research & Pipeline Management",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

# Register command groups
app.add_typer(db.app, name="db", help="Database management commands")
app.add_typer(
    question.app, name="question", help="Question management and collection commands"
)
app.add_typer(evidence.app, name="evidence", help="Evidence pipeline commands")
app.add_typer(forecast.app, name="forecast", help="Forecasting commands")
app.add_typer(graph.app, name="graph", help="Graph building and audit commands")
app.add_typer(benchmark.app, name="benchmark", help="LLM benchmark research commands")


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
):
    """WorldReasoner CLI for forecasting research and pipeline management.

    The unified CLI consolidates all example scripts and database management
    into a single command-line interface with consistent UX.

    Examples:
        wr db stats
        wr db list questions --domain politics
        wr db show question q_abc123
        wr db clear-evidence q_abc123 --dry-run

    For help on any command:
        wr <command> --help
    """
    # Store verbose flag in context for subcommands to access
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    if verbose:
        console.print("[dim]Verbose mode enabled[/dim]")

    # Ensure all database tables exist before any subcommand runs
    try:
        cfg = get_config()
        db = GenericDatabase(cfg.database.db_path)
        tables = db.initialize_all_tables()
        if verbose:
            console.print(f"[dim]Initialized database; ensured {tables} tables[/dim]")
    except Exception as e:
        console.print(
            f"[yellow]Warning:[/yellow] Failed to initialize database tables: {e}"
        )


def cli():
    """Entry point for the CLI when installed via pip."""
    app()


if __name__ == "__main__":
    app()
