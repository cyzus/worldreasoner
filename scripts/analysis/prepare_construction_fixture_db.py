"""Materialize a clean, disposable database for construction parity runs.

The output contains frozen questions, their existing collected snapshots and
quality records, and outcome events. Legacy hindsight events, causal edges, and
outcome impacts are deliberately excluded.

Usage:
    uv run --no-sync python scripts/analysis/prepare_construction_fixture_db.py \
      --output tmp/construction_migration_20_run.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.database import GenericDatabase  # noqa: E402
from src.domain import models as _domain_models  # noqa: E402, F401


DEFAULT_SOURCE = ROOT / "data" / "versions" / "v2_0" / "worldreasoner.db"
DEFAULT_FIXTURE = (
    ROOT / "config" / "fixtures" / "construction_migration_20.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_columns(connection: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def copy_rows(
    destination: sqlite3.Connection,
    table: str,
    where_clause: str,
    parameters: Sequence[Any],
) -> int:
    destination_columns = table_columns(destination, table)
    source_columns = [
        row[1]
        for row in destination.execute(f"PRAGMA source.table_info({table})")
    ]
    columns = [column for column in destination_columns if column in source_columns]
    if not columns:
        raise RuntimeError(f"No shared columns for table {table}")
    column_sql = ", ".join(f'"{column}"' for column in columns)
    before = destination.total_changes
    destination.execute(
        f"INSERT INTO {table} ({column_sql}) "
        f"SELECT {column_sql} FROM source.{table} WHERE {where_clause}",
        tuple(parameters),
    )
    return destination.total_changes - before


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _normalized_text(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def infer_actual_outcome_id(
    ground_truth: Any,
    options: Any,
    outcomes: Sequence[Dict[str, Any]],
) -> Optional[str]:
    """Infer a missing actual-outcome flag without overriding source labels."""
    actual = [outcome["id"] for outcome in outcomes if outcome["is_actual_outcome"]]
    if len(actual) == 1:
        return actual[0]
    if actual:
        return None

    decoded_truth = _decode_json_value(ground_truth)
    decoded_options = _decode_json_value(options) or []
    normalized_truth = _normalized_text(decoded_truth)
    if not normalized_truth:
        return None

    if len(decoded_options) == 2:
        try:
            truth_index = [
                _normalized_text(option) for option in decoded_options
            ].index(normalized_truth)
        except ValueError:
            truth_index = -1
        expected_prefix = "yes -" if truth_index == 0 else "no -"
        prefix_matches = [
            outcome["id"]
            for outcome in outcomes
            if truth_index in (0, 1)
            and _normalized_text(outcome["title"]).startswith(expected_prefix)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

    title_matches = [
        outcome["id"]
        for outcome in outcomes
        if normalized_truth in _normalized_text(outcome["title"])
    ]
    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        negative_markers = (" fails ", " fail ", " not ", " no -")
        positive_matches = [
            outcome["id"]
            for outcome in outcomes
            if outcome["id"] in title_matches
            and not any(
                marker in f" {_normalized_text(outcome['title'])} "
                for marker in negative_markers
            )
        ]
        if len(positive_matches) == 1:
            return positive_matches[0]

    indexed_matches = [
        outcome["id"]
        for outcome in outcomes
        if outcome["outcome_option_index"] is not None
        and outcome["outcome_option_index"] < len(decoded_options)
        and _normalized_text(
            decoded_options[outcome["outcome_option_index"]]
        )
        == normalized_truth
    ]
    if len(indexed_matches) == 1:
        return indexed_matches[0]

    return None


def populate_missing_actual_outcomes(
    connection: sqlite3.Connection,
    question_ids: Sequence[str],
) -> Dict[str, str]:
    inferred: Dict[str, str] = {}
    for question_id in question_ids:
        question = connection.execute(
            "SELECT ground_truth, options FROM questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not question:
            continue
        rows = connection.execute(
            "SELECT id, title, outcome_option_index, is_actual_outcome "
            "FROM events WHERE extracted_for_question_id = ? AND is_outcome = 1",
            (question_id,),
        ).fetchall()
        outcomes = [
            {
                "id": row[0],
                "title": row[1],
                "outcome_option_index": row[2],
                "is_actual_outcome": row[3],
            }
            for row in rows
        ]
        outcome_id = infer_actual_outcome_id(question[0], question[1], outcomes)
        if outcome_id is None or any(row[3] for row in rows):
            continue
        connection.execute(
            "UPDATE events SET is_actual_outcome = CASE WHEN id = ? THEN 1 ELSE 0 END "
            "WHERE extracted_for_question_id = ? AND is_outcome = 1",
            (outcome_id, question_id),
        )
        inferred[question_id] = outcome_id
    return inferred


def materialize(
    source_path: Path,
    fixture_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not fixture_path.exists():
        raise FileNotFoundError(fixture_path)
    if output_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite fixture database: {output_path}"
        )

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    question_ids = fixture.get("question_ids", [])
    if len(question_ids) != 20 or len(set(question_ids)) != 20:
        raise ValueError("Expected exactly 20 unique frozen question IDs")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    database = GenericDatabase(str(output_path))
    database.initialize_all_tables()

    connection = sqlite3.connect(str(output_path))
    connection.execute("ATTACH DATABASE ? AS source", (str(source_path.resolve()),))
    placeholders = ",".join("?" for _ in question_ids)
    try:
        connection.execute("BEGIN IMMEDIATE")
        question_count = copy_rows(
            connection,
            "questions",
            f"id IN ({placeholders})",
            question_ids,
        )
        connection.execute(
            f"UPDATE questions SET graph_built = 0, graph_build_error = NULL, "
            f"related_event_ids = '[]', causal_explanation = NULL "
            f"WHERE id IN ({placeholders})",
            tuple(question_ids),
        )
        article_count = copy_rows(
            connection,
            "articles",
            f"collected_for_question_id IN ({placeholders})",
            question_ids,
        )
        article_quality_count = copy_rows(
            connection,
            "article_quality_records",
            "article_id IN (SELECT id FROM articles)",
            [],
        )
        outcome_count = copy_rows(
            connection,
            "events",
            f"extracted_for_question_id IN ({placeholders}) AND is_outcome = 1",
            question_ids,
        )
        inferred_actual_outcomes = populate_missing_actual_outcomes(
            connection,
            question_ids,
        )

        connection.execute(
            "CREATE TABLE fixture_materialization ("
            "id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        provenance = {
            "fixture_version": fixture.get("fixture_version"),
            "fixture_question_ids_sha256": hashlib.sha256(
                "\n".join(sorted(question_ids)).encode("utf-8")
            ).hexdigest(),
            "fixture_manifest_sha256": file_sha256(fixture_path),
            "source_database": str(source_path.relative_to(ROOT)),
            "source_manifest_updated_at": fixture.get(
                "quality_comparison",
                {},
            ).get("manifest_updated_at"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "excluded": [
                "legacy non-outcome events",
                "legacy causal hypotheses",
                "legacy outcome impacts",
                "forecasts and forecast graphs",
            ],
            "inferred_actual_outcomes": inferred_actual_outcomes,
        }
        connection.execute(
            "INSERT INTO fixture_materialization (id, payload) VALUES (?, ?)",
            ("construction_migration_20", json.dumps(provenance, sort_keys=True)),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "output": str(output_path),
        "questions": question_count,
        "articles": article_count,
        "article_quality_records": article_quality_count,
        "outcome_events": outcome_count,
        "inferred_actual_outcomes": inferred_actual_outcomes,
        "fixture_manifest_sha256": file_sha256(fixture_path),
    }


def main() -> None:
    args = parse_args()
    result = materialize(args.source, args.fixture, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
