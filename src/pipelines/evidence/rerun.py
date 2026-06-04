"""Re-run the evidence + graph-builder pipelines for low-source questions.

Importable home for the logic that used to live in ``scripts/rerun_evidence.py``.
The ``wr evidence rerun`` CLI command wraps :func:`rerun_evidence`.
"""

import sqlite3
from pathlib import Path
from typing import Callable, List, Optional

from src.pipelines.executor import PipelineExecutor
from src.pipelines.types import PipelineProgress, PipelineType


def find_low_source_questions(db_path: str, threshold: int) -> List[str]:
    """Return question IDs with <= ``threshold`` unique non-outcome source articles."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT q.id, COUNT(DISTINCT e.source_article_id) AS unique_sources
            FROM questions q
            JOIN events e ON e.extracted_for_question_id = q.id
            WHERE e.source_article_id IS NOT NULL AND e.is_outcome = 0
            GROUP BY q.id
            HAVING unique_sources <= ?
            ORDER BY unique_sources, q.id
            """,
            (threshold,),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


async def rerun_evidence(
    db_path: str = "combined.db",
    threshold: int = 2,
    ids: Optional[List[str]] = None,
    dry_run: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """Re-run evidence and graph-builder pipelines for selected questions.

    Args:
        db_path: Path to the database.
        threshold: Re-run questions with <= this many unique source articles.
            Ignored when ``ids`` is provided.
        ids: Explicit question IDs to re-run (overrides the threshold scan).
        dry_run: Print the questions that would be re-run without running them.
        log: Optional progress callback (defaults to ``print``).

    Returns:
        True if the run completed (or dry-run), False if the database was missing.
    """
    emit = log or print
    path = Path(db_path)
    if not path.exists():
        emit(f"Database not found: {path}")
        return False

    if ids:
        question_ids = list(ids)
        emit(f"Using {len(question_ids)} explicitly provided question ID(s).")
    else:
        question_ids = find_low_source_questions(str(path), threshold)
        emit(
            f"Found {len(question_ids)} question(s) with "
            f"<={threshold} unique sources."
        )

    if not question_ids:
        emit("Nothing to do.")
        return True

    for qid in question_ids:
        emit(f"  {qid}")

    if dry_run:
        emit("\nDry run - not running pipeline.")
        return True

    def on_progress(p: PipelineProgress) -> None:
        emit(f"  [{p.current}/{p.total}] {p.stage} - {p.question_id}: {p.message}")

    executor = PipelineExecutor(db_path=str(path))

    emit(f"\n[1/2] Evidence pipeline ({len(question_ids)} questions) ...")
    result = await executor.execute(
        pipeline_type=PipelineType.EVIDENCE,
        question_ids=question_ids,
        on_progress=on_progress,
        force_reprocess=True,
    )
    emit(
        f"  Completed: {result.success_count}  "
        f"Failed: {result.failure_count}  Skipped: {result.skip_count}"
    )

    succeeded = [r["id"] for r in result.processed if "id" in r] or question_ids

    emit(f"\n[2/2] Graph builder pipeline ({len(succeeded)} questions) ...")
    gb_result = await executor.execute(
        pipeline_type=PipelineType.GRAPH_BUILDER,
        question_ids=succeeded,
        on_progress=on_progress,
        force_reprocess=True,
    )
    emit(
        f"  Completed: {gb_result.success_count}  "
        f"Failed: {gb_result.failure_count}  Skipped: {gb_result.skip_count}"
    )

    if gb_result.failed:
        emit("\nFailed questions (graph builder):")
        for f in gb_result.failed:
            emit(f"  {f}")

    return True
