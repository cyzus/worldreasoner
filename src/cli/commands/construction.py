"""Commands for the versioned benchmark-construction workflow."""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from src.config.pipeline import SATISFACTION_DEFAULTS, EvidenceSatisfactionConfig
from src.domain.models import Question
from src.pipelines.construction.orchestrator import ConstructionPipeline
from src.pipelines.construction.sdk_runtime import AgentsSDKRuntime

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("run")
def run_construction(
    topic: str = typer.Option(
        ...,
        "--topic",
        help="Resolved event topic used to generate the question.",
    ),
    db_path: Path = typer.Option(
        ...,
        "--db",
        help="Path to a new SQLite database for this construction run.",
    ),
    model: str = typer.Option(
        "gemini/gemini-3.1-pro-preview",
        "--model",
        help="LiteLLM model identifier used by all bounded specialists.",
    ),
    dataset_version: str = typer.Option("v2-live", "--dataset-version"),
    max_search_results: int = typer.Option(5, min=1, max=10),
    min_approved_articles: int = typer.Option(
        SATISFACTION_DEFAULTS.min_articles,
        "--min-approved-articles",
        min=1,
        help="Minimum cleaned, approved articles required before synthesis.",
    ),
    min_graph_events: int = typer.Option(
        SATISFACTION_DEFAULTS.min_graph_events,
        "--min-graph-events",
        min=2,
    ),
    min_graph_depth: int = typer.Option(
        SATISFACTION_DEFAULTS.min_graph_depth,
        "--min-graph-depth",
        min=1,
    ),
    cleaner_concurrency: int = typer.Option(3, min=1, max=8),
    max_evidence_rounds: int = typer.Option(
        3,
        "--max-evidence-rounds",
        min=1,
        max=10,
        help="Bounded collect-clean-reassess rounds before evidence failure.",
    ),
    allow_model_content: bool = typer.Option(
        False,
        "--allow-model-content",
        help="Acknowledge that fetched article snapshots are sent to the model.",
    ),
    source_url: List[str] = typer.Option(
        [],
        "--source-url",
        help="Repeatable live source URL used for seeding and evidence recovery.",
    ),
) -> None:
    """Build one question, evidence dossier, explanation, and graph end to end."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    if db_path.exists() and db_path.stat().st_size > 0:
        raise typer.BadParameter(
            f"Refusing to use non-empty database: {db_path}. Choose a new path."
        )
    if not allow_model_content:
        raise typer.BadParameter(
            "Pass --allow-model-content to permit article cleanup and synthesis."
        )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = AgentsSDKRuntime(model_id=model)
    pipeline = ConstructionPipeline(
        db_path=db_path,
        runtime=runtime,
        dataset_version=dataset_version,
        max_search_results=max_search_results,
        requirements=EvidenceSatisfactionConfig(
            min_articles=min_approved_articles,
            min_graph_events=min_graph_events,
            min_graph_depth=min_graph_depth,
        ),
        cleaner_concurrency=cleaner_concurrency,
        max_evidence_rounds=max_evidence_rounds,
        source_urls=source_url,
    )
    result = asyncio.run(pipeline.run(topic))
    console.print(json.dumps(result.model_dump(), indent=2))


@app.command("resume-graph")
def resume_graph(
    db_path: Path = typer.Option(..., "--db", help="Existing construction database."),
    run_id: str = typer.Option(..., "--run-id"),
    model: str = typer.Option(
        "gemini/gemini-3.1-pro-preview", "--model"
    ),
) -> None:
    """Resume graph construction from a validated dossier and explanation."""
    if not db_path.exists():
        raise typer.BadParameter(f"Database does not exist: {db_path}")
    runtime = AgentsSDKRuntime(model_id=model)
    pipeline = ConstructionPipeline(db_path=db_path, runtime=runtime)
    result = asyncio.run(pipeline.resume_graph(run_id))
    console.print(json.dumps(result.model_dump(), indent=2))


@app.command("questions")
def construct_existing_questions(
    question_ids: Optional[List[str]] = typer.Option(
        None,
        "--question",
        "-q",
        help="Existing resolved question ID; repeat for a batch.",
    ),
    all_resolved: bool = typer.Option(
        False,
        "--all-resolved",
        help="Process every resolved question not marked to skip evidence.",
    ),
    db_path: Path = typer.Option(
        ...,
        "--db",
        help="Existing benchmark database.",
    ),
    model: str = typer.Option(
        "gemini/gemini-3.1-pro-preview",
        "--model",
    ),
    dataset_version: str = typer.Option("v2-live", "--dataset-version"),
    max_search_results: int = typer.Option(5, min=1, max=10),
    min_approved_articles: int = typer.Option(
        SATISFACTION_DEFAULTS.min_articles,
        "--min-approved-articles",
        min=1,
    ),
    min_graph_events: int = typer.Option(
        SATISFACTION_DEFAULTS.min_graph_events,
        "--min-graph-events",
        min=2,
    ),
    min_graph_depth: int = typer.Option(
        SATISFACTION_DEFAULTS.min_graph_depth,
        "--min-graph-depth",
        min=1,
    ),
    cleaner_concurrency: int = typer.Option(3, min=1, max=8),
    max_evidence_rounds: int = typer.Option(3, min=1, max=10),
    allow_model_content: bool = typer.Option(
        False,
        "--allow-model-content",
        help="Acknowledge that fetched snapshots are sent to the model.",
    ),
) -> None:
    """Build evidence, explanation, and graphs for resolved DB questions."""
    if not db_path.exists():
        raise typer.BadParameter(f"Database does not exist: {db_path}")
    if not allow_model_content:
        raise typer.BadParameter(
            "Pass --allow-model-content to permit article cleanup and synthesis."
        )
    if all_resolved and question_ids:
        raise typer.BadParameter(
            "Use either --all-resolved or one or more --question values."
        )
    if not all_resolved and not question_ids:
        raise typer.BadParameter(
            "Provide --all-resolved or at least one --question value."
        )
    runtime = AgentsSDKRuntime(model_id=model)
    pipeline = ConstructionPipeline(
        db_path=db_path,
        runtime=runtime,
        dataset_version=dataset_version,
        max_search_results=max_search_results,
        requirements=EvidenceSatisfactionConfig(
            min_articles=min_approved_articles,
            min_graph_events=min_graph_events,
            min_graph_depth=min_graph_depth,
        ),
        cleaner_concurrency=cleaner_concurrency,
        max_evidence_rounds=max_evidence_rounds,
    )
    selected_ids = list(question_ids or [])
    if all_resolved:
        selected_ids = sorted(
            question.id
            for question in pipeline.db.get_many(Question)
            if question.ground_truth is not None and not question.skip_evidence
        )
    result = asyncio.run(pipeline.run_questions(selected_ids))
    console.print(json.dumps(result.model_dump(), indent=2))
