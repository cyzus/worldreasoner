"""Database maintenance operations: cleanup, merge, and search-index build.

Importable home for the logic that used to live in ``scripts/cleanup.py``,
``scripts/merge_databases.py`` and ``scripts/build_search_index.py``. The
``wr db clean``, ``wr db merge`` and ``wr db build-index`` commands wrap these.
"""

import json
import sqlite3
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def _get_events_for_articles(
    conn: sqlite3.Connection, article_ids: set
) -> set:
    """Return event IDs whose source_article_id is in article_ids."""
    if not article_ids:
        return set()
    placeholders = ",".join("?" * len(article_ids))
    rows = conn.execute(
        f"SELECT id FROM events WHERE source_article_id IN ({placeholders})",
        list(article_ids),
    ).fetchall()
    return {r[0] for r in rows}


def _cascade_delete_events(
    conn: sqlite3.Connection, event_ids: set, dry_run: bool
) -> dict:
    """Delete events and all rows that reference them. Returns counts."""
    if not event_ids:
        return {}
    ph = ",".join("?" * len(event_ids))
    ids = list(event_ids)

    counts: Dict[str, int] = {}
    ref_tables = [
        ("event_outcome_impacts", "event_id"),
        ("event_outcome_impacts", "outcome_event_id"),
        ("causal_hypotheses", "source_event_id"),
        ("causal_hypotheses", "target_event_id"),
    ]
    for table, col in ref_tables:
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({ph})", ids
        ).fetchone()[0]
        key = f"{table}.{col}"
        counts[key] = counts.get(key, 0) + n

    counts["events"] = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE id IN ({ph})", ids
    ).fetchone()[0]

    if not dry_run:
        for table, col in ref_tables:
            conn.execute(f"DELETE FROM {table} WHERE {col} IN ({ph})", ids)
        conn.execute(f"DELETE FROM events WHERE id IN ({ph})", ids)

    return counts


def _cascade_delete_articles(
    conn: sqlite3.Connection, article_ids: set, dry_run: bool
) -> dict:
    """Delete articles + embeddings + FTS. Returns counts."""
    if not article_ids:
        return {}
    ph = ",".join("?" * len(article_ids))
    ids = list(article_ids)

    n_emb = conn.execute(
        f"SELECT COUNT(*) FROM article_embeddings WHERE article_id IN ({ph})", ids
    ).fetchone()[0]

    has_fts = (
        conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='articles_fts'"
        ).fetchone()
        is not None
    )
    n_fts = 0
    if has_fts:
        n_fts = conn.execute(
            f"SELECT COUNT(*) FROM articles_fts WHERE rowid IN ({ph})", ids
        ).fetchone()[0]

    n_art = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE id IN ({ph})", ids
    ).fetchone()[0]

    if not dry_run:
        conn.execute(
            f"DELETE FROM article_embeddings WHERE article_id IN ({ph})", ids
        )
        if has_fts:
            conn.execute(f"DELETE FROM articles_fts WHERE rowid IN ({ph})", ids)
        conn.execute(f"DELETE FROM articles WHERE id IN ({ph})", ids)

    return {"article_embeddings": n_emb, "articles_fts": n_fts, "articles": n_art}


def _clean_example_com(conn, dry_run, emit):
    emit("\n=== Pass 1: example.com articles ===")
    rows = conn.execute(
        "SELECT id FROM articles WHERE url LIKE '%example.com%'"
    ).fetchall()
    art_ids = {r[0] for r in rows}
    emit(f"  Articles matched: {len(art_ids)}")
    evt_ids = _get_events_for_articles(conn, art_ids)
    emit(f"  Linked events:    {len(evt_ids)}")
    counts = {
        **_cascade_delete_events(conn, evt_ids, dry_run),
        **_cascade_delete_articles(conn, art_ids, dry_run),
    }
    for k, v in counts.items():
        if v:
            emit(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def _clean_invalid_content(conn, dry_run, emit):
    emit("\n=== Pass 2: short/invalid content articles (<500 chars) ===")
    rows = conn.execute(
        "SELECT id FROM articles WHERE LENGTH(COALESCE(content, '')) < 500"
    ).fetchall()
    art_ids = {r[0] for r in rows}
    emit(f"  Articles matched: {len(art_ids)}")
    evt_ids = _get_events_for_articles(conn, art_ids)
    emit(f"  Linked events:    {len(evt_ids)}")
    counts = {
        **_cascade_delete_events(conn, evt_ids, dry_run),
        **_cascade_delete_articles(conn, art_ids, dry_run),
    }
    for k, v in counts.items():
        if v:
            emit(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def _clean_duplicate_events(conn, dry_run, emit):
    """Per question, keep the earliest event for each title; delete the rest."""
    emit("\n=== Pass 3: exact-title duplicate events (per question) ===")
    rows = conn.execute(
        """
        SELECT id, title, extracted_for_question_id, created_at
        FROM events
        WHERE extracted_for_question_id IS NOT NULL
        ORDER BY extracted_for_question_id, title, created_at
        """
    ).fetchall()

    seen: Dict[tuple, int] = {}
    to_delete: set = set()
    for eid, title, qid, _created_at in rows:
        key = (qid, (title or "").strip().lower())
        if key not in seen:
            seen[key] = eid
        else:
            to_delete.add(eid)

    emit(f"  Duplicate events to remove: {len(to_delete)}")
    for k, v in _cascade_delete_events(conn, to_delete, dry_run).items():
        if v:
            emit(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def clean_database(
    db_path: str,
    execute: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """Remove bad data from a database (cascading deletes).

    Removes example.com articles, <500-char articles, and exact-title duplicate
    events, cascading to all referencing tables.

    Args:
        db_path: Path to the SQLite database.
        execute: Apply changes. When False (default), runs as a dry-run.
        log: Optional progress callback (defaults to ``print``).

    Returns:
        True if the database was found and processed, False otherwise.
    """
    emit = log or print
    path = Path(db_path)
    if not path.exists():
        emit(f"Database not found: {path}")
        return False

    dry_run = not execute
    emit(f"cleanup — mode: {'DRY RUN' if dry_run else 'EXECUTE'} — db: {path}")

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # cascade handled manually
    try:
        _clean_example_com(conn, dry_run, emit)
        _clean_invalid_content(conn, dry_run, emit)
        _clean_duplicate_events(conn, dry_run, emit)

        if not dry_run:
            conn.commit()
            emit("\nAll changes committed.")
        else:
            conn.rollback()
            emit(
                "\nDry run complete — no changes written. "
                "Re-run with --execute to apply."
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Timeline Of Key Events",
    "Causal Chain Analysis",
    "Countervailing Factors",
    "Event Candidate Inventory",
    "Evidence Mapping Table",
    "Uncertainties And Alternative Paths",
]

CANONICAL_QUESTION_COLS = [
    "id", "question_text", "question_type", "domain", "source", "difficulty",
    "resolution_date", "estimated_start_time", "ground_truth", "ground_truth_hash",
    "target_event_id", "outcome_event_ids", "related_event_ids",
    "related_article_ids", "context", "resolution_criteria", "resolution_reasoning",
    "options", "quantity_unit", "quantity_bounds", "is_synthetic", "quality_score",
    "quality_dimensions", "skip_evidence", "skip_reason", "quality_warning",
    "created_at", "updated_at", "metadata", "causal_explanation", "graph_built",
    "graph_build_error",
]


def _is_compliant(explanation: Optional[str]) -> bool:
    if not explanation:
        return False
    return all(s in explanation for s in REQUIRED_SECTIONS)


def _get_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _create_combined_db(
    schema_source: Path, output_db: Path, emit: Callable[[str], None]
) -> sqlite3.Connection:
    if output_db.exists():
        output_db.unlink()

    src_conn = sqlite3.connect(schema_source)
    schema_rows = src_conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND type IN ('table','index') "
        "AND name NOT LIKE 'articles_fts%'"
    ).fetchall()
    src_conn.close()

    conn = sqlite3.connect(output_db)
    conn.execute("PRAGMA journal_mode=WAL")
    for name, sql in schema_rows:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            emit(f"  Schema note [{name}]: {e}")

    existing_q_cols = _get_columns(conn, "questions")
    for col in CANONICAL_QUESTION_COLS:
        if col not in existing_q_cols:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TEXT")

    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts "
        "USING fts5(article_id UNINDEXED, title, content)"
    )
    conn.commit()
    emit(f"[INIT] Empty combined db created at {output_db}")
    return conn


def _build_question_source_map(
    sources: List[Tuple[str, Path]], emit: Callable[[str], None]
) -> Dict[str, str]:
    """Returns {question_id: db_label}; later sources override earlier ones."""
    source_map: Dict[str, str] = {}
    for label, path in sources:
        conn = sqlite3.connect(path)
        ids = [r[0] for r in conn.execute("SELECT id FROM questions").fetchall()]
        conn.close()
        for qid in ids:
            source_map[qid] = label

    counts: Dict[str, int] = {}
    for label in source_map.values():
        counts[label] = counts.get(label, 0) + 1
    emit("\n[MAP] Authoritative source per question:")
    for label, cnt in counts.items():
        emit(f"  {label}: {cnt}")
    emit(f"  TOTAL unique questions: {len(source_map)}")
    return source_map


def _copy_questions_from_source(
    src_conn, dst_conn, question_ids, emit
) -> Tuple[List[str], List[str]]:
    src_cols = _get_columns(src_conn, "questions")
    placeholders = ",".join("?" * len(question_ids))
    rows = src_conn.execute(
        f"SELECT {', '.join(src_cols)} FROM questions WHERE id IN ({placeholders})",
        question_ids,
    ).fetchall()

    compliant_ids: List[str] = []
    non_compliant_ids: List[str] = []
    normalized = []
    for row in rows:
        row_dict = dict(zip(src_cols, row))
        if _is_compliant(row_dict.get("causal_explanation")):
            compliant_ids.append(row_dict["id"])
        else:
            non_compliant_ids.append(row_dict["id"])
            row_dict["causal_explanation"] = None
            row_dict["related_article_ids"] = None
            row_dict["graph_built"] = 0
            row_dict["graph_build_error"] = None
        normalized.append(tuple(row_dict.get(c) for c in CANONICAL_QUESTION_COLS))

    dst_conn.executemany(
        f"INSERT OR IGNORE INTO questions ({', '.join(CANONICAL_QUESTION_COLS)}) "
        f"VALUES ({', '.join('?' * len(CANONICAL_QUESTION_COLS))})",
        normalized,
    )
    emit(
        f"  Questions inserted: {len(normalized)} "
        f"({len(compliant_ids)} with evidence, "
        f"{len(non_compliant_ids)} evidence-cleared)"
    )
    return compliant_ids, non_compliant_ids


def _copy_table_by_fk(src_conn, dst_conn, table, fk_col, question_ids) -> int:
    if not question_ids:
        return 0
    try:
        src_cols = _get_columns(src_conn, table)
        dst_cols = _get_columns(dst_conn, table)
    except sqlite3.OperationalError:
        return 0
    common = [c for c in src_cols if c in dst_cols]
    if not common:
        return 0
    placeholders = ",".join("?" * len(question_ids))
    rows = src_conn.execute(
        f"SELECT {', '.join(common)} FROM {table} WHERE {fk_col} IN ({placeholders})",
        question_ids,
    ).fetchall()
    if not rows:
        return 0
    dst_conn.executemany(
        f"INSERT OR IGNORE INTO {table} ({', '.join(common)}) "
        f"VALUES ({', '.join('?' * len(common))})",
        rows,
    )
    return len(rows)


def _copy_causal_hypotheses_by_questions(src_conn, dst_conn, question_ids) -> int:
    """Hypotheses store question refs as a JSON array in discovered_by_question_ids."""
    if not question_ids:
        return 0
    try:
        src_cols = _get_columns(src_conn, "causal_hypotheses")
        dst_cols = _get_columns(dst_conn, "causal_hypotheses")
    except sqlite3.OperationalError:
        return 0
    common = [c for c in src_cols if c in dst_cols]
    q_set = set(question_ids)
    dbq_idx = (
        common.index("discovered_by_question_ids")
        if "discovered_by_question_ids" in common
        else None
    )
    all_rows = src_conn.execute(
        f"SELECT {', '.join(common)} FROM causal_hypotheses"
    ).fetchall()

    matching = []
    for row in all_rows:
        if dbq_idx is not None:
            try:
                ids = json.loads(row[dbq_idx] or "[]")
                if any(qid in q_set for qid in ids):
                    matching.append(row)
            except (json.JSONDecodeError, TypeError):
                pass

    if not matching:
        return 0
    dst_conn.executemany(
        f"INSERT OR IGNORE INTO causal_hypotheses ({', '.join(common)}) "
        f"VALUES ({', '.join('?' * len(common))})",
        matching,
    )
    return len(matching)


def _copy_evidence_for_compliant(src_conn, dst_conn, compliant_ids, emit):
    n_arts = _copy_table_by_fk(
        src_conn, dst_conn, "articles", "collected_for_question_id", compliant_ids
    )
    n_evts = _copy_table_by_fk(
        src_conn, dst_conn, "events", "extracted_for_question_id", compliant_ids
    )
    n_hyps = _copy_causal_hypotheses_by_questions(src_conn, dst_conn, compliant_ids)
    n_imps = _copy_table_by_fk(
        src_conn, dst_conn, "event_outcome_impacts", "question_id", compliant_ids
    )
    emit(
        f"  Evidence: {n_arts} articles, {n_evts} events, "
        f"{n_hyps} hypotheses, {n_imps} outcome_impacts"
    )


def _rebuild_fts(conn, emit):
    emit("\n[FTS] Rebuilding articles_fts...")
    conn.execute("DROP TABLE IF EXISTS articles_fts")
    conn.execute(
        "CREATE VIRTUAL TABLE articles_fts "
        "USING fts5(article_id UNINDEXED, title, content)"
    )
    conn.execute(
        "INSERT INTO articles_fts (article_id, title, content) "
        "SELECT id, COALESCE(title, ''), COALESCE(content, '') FROM articles"
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    emit(f"  FTS index: {count} entries")


def merge_databases(
    sources: List[Tuple[str, str]],
    output_db: str,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Merge source databases into a single combined database.

    Deduplicates by question ID (later sources in the list take priority), copies
    evidence only for questions with a compliant causal_explanation, clears
    evidence for non-compliant questions, and rebuilds the FTS index.

    Args:
        sources: Ordered ``[(label, db_path), ...]``. Later entries win on
            duplicate question IDs; the first entry's schema seeds the output.
        output_db: Path to write the combined database (overwritten if exists).
        log: Optional progress callback (defaults to ``print``).
    """
    emit = log or print
    resolved = [(label, Path(p)) for label, p in sources]
    missing = [str(p) for _, p in resolved if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Source database(s) not found: {', '.join(missing)}")

    emit("=" * 60)
    emit("WorldReasoner Database Merger")
    emit("=" * 60)

    source_map = _build_question_source_map(resolved, emit)
    ids_by_source: Dict[str, List[str]] = {label: [] for label, _ in resolved}
    for qid, label in source_map.items():
        ids_by_source[label].append(qid)

    # First source provides the most complete schema for the output.
    dst_conn = _create_combined_db(resolved[0][1], Path(output_db), emit)

    total_compliant = 0
    total_non_compliant = 0
    for label, db_path in resolved:
        q_ids = ids_by_source[label]
        emit(f"\n[COPY] {label} -> {output_db} ({len(q_ids)} questions)")
        if not q_ids:
            emit("  (nothing to copy)")
            continue
        src_conn = sqlite3.connect(db_path)
        src_conn.row_factory = sqlite3.Row
        compliant_ids, non_compliant_ids = _copy_questions_from_source(
            src_conn, dst_conn, q_ids, emit
        )
        _copy_evidence_for_compliant(src_conn, dst_conn, compliant_ids, emit)
        total_compliant += len(compliant_ids)
        total_non_compliant += len(non_compliant_ids)
        src_conn.close()

    dst_conn.commit()
    _rebuild_fts(dst_conn, emit)

    emit("\n[STATS] combined db final counts:")
    for t in [
        "questions",
        "articles",
        "events",
        "causal_hypotheses",
        "event_outcome_impacts",
    ]:
        count = dst_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        emit(f"  {t}: {count}")

    emit(f"\n  Questions with compliant explanation + evidence: {total_compliant}")
    emit(f"  Questions with cleared evidence (need re-collection): {total_non_compliant}")

    dst_conn.close()
    emit(f"\n[DONE] {output_db}")
