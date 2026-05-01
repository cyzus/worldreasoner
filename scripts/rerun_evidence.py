"""
Re-run the evidence pipeline for questions that have too few unique source articles.

By default targets all questions with <=2 unique source articles (excluding outcome events).
You can also pass explicit question IDs.

Usage:
  uv run python scripts/rerun_evidence.py --db combined.db
  uv run python scripts/rerun_evidence.py --db combined.db --threshold 3
  uv run python scripts/rerun_evidence.py --db combined.db --ids q1 q2 q3
  uv run python scripts/rerun_evidence.py --db combined.db --dry-run
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.executor import PipelineExecutor
from src.pipelines.types import PipelineProgress, PipelineType
from src.utils.logging import logger


def find_low_source_questions(db_path: str, threshold: int) -> list[str]:
    import sqlite3
    conn = sqlite3.connect(db_path)
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
    conn.close()
    return [r[0] for r in rows]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run evidence pipeline for low-source questions")
    parser.add_argument("--db", default="combined.db", help="Path to SQLite database")
    parser.add_argument(
        "--threshold",
        type=int,
        default=2,
        help="Re-run questions with <= this many unique source articles (default: 2)",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        metavar="ID",
        help="Explicit question IDs to re-run (overrides --threshold scan)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the questions that would be re-run without running them",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    if args.ids:
        question_ids = args.ids
        print(f"Using {len(question_ids)} explicitly provided question ID(s).")
    else:
        question_ids = find_low_source_questions(str(db_path), args.threshold)
        print(f"Found {len(question_ids)} question(s) with ≤{args.threshold} unique sources.")

    if not question_ids:
        print("Nothing to do.")
        return

    for qid in question_ids:
        print(f"  {qid}")

    if args.dry_run:
        print("\nDry run — not running pipeline.")
        return

    def on_progress(p: PipelineProgress) -> None:
        print(f"  [{p.current}/{p.total}] {p.stage} — {p.question_id}: {p.message}")

    executor = PipelineExecutor(db_path=str(db_path))

    print(f"\n[1/2] Evidence pipeline ({len(question_ids)} questions) ...")
    result = await executor.execute(
        pipeline_type=PipelineType.EVIDENCE,
        question_ids=question_ids,
        on_progress=on_progress,
        force_reprocess=True,
    )
    print(f"  Completed: {result.success_count}  Failed: {result.failure_count}  Skipped: {result.skip_count}")

    # Only run graph builder for questions that succeeded
    succeeded = [r["id"] for r in result.processed if "id" in r]
    if not succeeded:
        # fall back to all if processed entries lack id field
        succeeded = question_ids

    print(f"\n[2/2] Graph builder pipeline ({len(succeeded)} questions) ...")
    gb_result = await executor.execute(
        pipeline_type=PipelineType.GRAPH_BUILDER,
        question_ids=succeeded,
        on_progress=on_progress,
        force_reprocess=True,
    )
    print(f"  Completed: {gb_result.success_count}  Failed: {gb_result.failure_count}  Skipped: {gb_result.skip_count}")

    if gb_result.failed:
        print("\nFailed questions (graph builder):")
        for f in gb_result.failed:
            print(f"  {f}")


if __name__ == "__main__":
    asyncio.run(main())
