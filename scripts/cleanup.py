"""
Database cleanup script.

Removes three categories of bad data:
  1. Articles with example.com URLs (fake/placeholder) + linked events + cascade
  2. Articles with <500-char content (cookie walls, error pages, etc.) + linked events + cascade
  3. Exact-title duplicate events per question (keep earliest, delete rest + cascade)

Run with --dry-run (default) to preview counts, --execute to apply changes.

Usage:
  uv run python scripts/cleanup.py --db combined.db
  uv run python scripts/cleanup.py --db combined.db --execute
"""

import argparse
import json
import sqlite3
from pathlib import Path


def get_events_for_articles(conn: sqlite3.Connection, article_ids: set[int]) -> set[int]:
    """Return event IDs whose source_article_id is in article_ids."""
    if not article_ids:
        return set()
    placeholders = ",".join("?" * len(article_ids))
    rows = conn.execute(
        f"SELECT id FROM events WHERE source_article_id IN ({placeholders})",
        list(article_ids),
    ).fetchall()
    return {r[0] for r in rows}


def cascade_delete_events(conn: sqlite3.Connection, event_ids: set[int], dry_run: bool) -> dict:
    """Delete events and all rows that reference them. Returns counts."""
    if not event_ids:
        return {}
    ph = ",".join("?" * len(event_ids))
    ids = list(event_ids)

    counts = {}
    for table, col in [
        ("event_outcome_impacts", "event_id"),
        ("event_outcome_impacts", "outcome_event_id"),
        ("causal_hypotheses", "source_event_id"),
        ("causal_hypotheses", "target_event_id"),
    ]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({ph})", ids).fetchone()[0]
        key = f"{table}.{col}"
        counts[key] = counts.get(key, 0) + n

    n_events = conn.execute(f"SELECT COUNT(*) FROM events WHERE id IN ({ph})", ids).fetchone()[0]
    counts["events"] = n_events

    if not dry_run:
        for table, col in [
            ("event_outcome_impacts", "event_id"),
            ("event_outcome_impacts", "outcome_event_id"),
            ("causal_hypotheses", "source_event_id"),
            ("causal_hypotheses", "target_event_id"),
        ]:
            conn.execute(f"DELETE FROM {table} WHERE {col} IN ({ph})", ids)
        conn.execute(f"DELETE FROM events WHERE id IN ({ph})", ids)

    return counts


def cascade_delete_articles(conn: sqlite3.Connection, article_ids: set[int], dry_run: bool) -> dict:
    """Delete articles + embeddings + FTS. Returns counts."""
    if not article_ids:
        return {}
    ph = ",".join("?" * len(article_ids))
    ids = list(article_ids)

    n_emb = conn.execute(
        f"SELECT COUNT(*) FROM article_embeddings WHERE article_id IN ({ph})", ids
    ).fetchone()[0]

    # Check if FTS table exists
    has_fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    ).fetchone() is not None
    n_fts = 0
    if has_fts:
        n_fts = conn.execute(
            f"SELECT COUNT(*) FROM articles_fts WHERE rowid IN ({ph})", ids
        ).fetchone()[0]

    n_art = conn.execute(f"SELECT COUNT(*) FROM articles WHERE id IN ({ph})", ids).fetchone()[0]

    if not dry_run:
        conn.execute(f"DELETE FROM article_embeddings WHERE article_id IN ({ph})", ids)
        if has_fts:
            conn.execute(f"DELETE FROM articles_fts WHERE rowid IN ({ph})", ids)
        conn.execute(f"DELETE FROM articles WHERE id IN ({ph})", ids)

    return {"article_embeddings": n_emb, "articles_fts": n_fts, "articles": n_art}


def cleanup_example_com(conn: sqlite3.Connection, dry_run: bool) -> None:
    print("\n=== Pass 1: example.com articles ===")
    rows = conn.execute(
        "SELECT id FROM articles WHERE url LIKE '%example.com%'"
    ).fetchall()
    art_ids = {r[0] for r in rows}
    print(f"  Articles matched: {len(art_ids)}")

    evt_ids = get_events_for_articles(conn, art_ids)
    print(f"  Linked events:    {len(evt_ids)}")

    evt_counts = cascade_delete_events(conn, evt_ids, dry_run)
    art_counts = cascade_delete_articles(conn, art_ids, dry_run)

    for k, v in {**evt_counts, **art_counts}.items():
        if v:
            print(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def cleanup_invalid_content(conn: sqlite3.Connection, dry_run: bool) -> None:
    print("\n=== Pass 2: short/invalid content articles (<500 chars) ===")
    rows = conn.execute(
        "SELECT id FROM articles WHERE LENGTH(COALESCE(content, '')) < 500"
    ).fetchall()
    art_ids = {r[0] for r in rows}
    print(f"  Articles matched: {len(art_ids)}")

    evt_ids = get_events_for_articles(conn, art_ids)
    print(f"  Linked events:    {len(evt_ids)}")

    evt_counts = cascade_delete_events(conn, evt_ids, dry_run)
    art_counts = cascade_delete_articles(conn, art_ids, dry_run)

    for k, v in {**evt_counts, **art_counts}.items():
        if v:
            print(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def cleanup_duplicate_events(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Per question, keep the earliest event for each title; delete the rest."""
    print("\n=== Pass 3: exact-title duplicate events (per question) ===")

    # Events are linked to questions via extracted_for_question_id
    rows = conn.execute(
        """
        SELECT id, title, extracted_for_question_id, created_at
        FROM events
        WHERE extracted_for_question_id IS NOT NULL
        ORDER BY extracted_for_question_id, title, created_at
        """
    ).fetchall()

    seen: dict[tuple, int] = {}  # (question_id, lower_title) -> keeper id
    to_delete: set[int] = set()

    for eid, title, qid, created_at in rows:
        key = (qid, (title or "").strip().lower())
        if key not in seen:
            seen[key] = eid
        else:
            to_delete.add(eid)

    print(f"  Duplicate events to remove: {len(to_delete)}")

    evt_counts = cascade_delete_events(conn, to_delete, dry_run)
    for k, v in evt_counts.items():
        if v:
            print(f"  {'[DRY]' if dry_run else '[DEL]'} {k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up combined.db")
    parser.add_argument("--db", default="combined.db", help="Path to SQLite database")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    dry_run = not args.execute
    mode = "DRY RUN" if dry_run else "EXECUTE"
    print(f"cleanup.py — mode: {mode} — db: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # we handle cascade manually

    try:
        cleanup_example_com(conn, dry_run)
        cleanup_invalid_content(conn, dry_run)
        cleanup_duplicate_events(conn, dry_run)

        if not dry_run:
            conn.commit()
            print("\nAll changes committed.")
        else:
            conn.rollback()
            print("\nDry run complete — no changes written. Re-run with --execute to apply.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
