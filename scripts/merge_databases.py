"""
Merge experiment.db, worldreasoner.db, and mofe_polymarket_curated.db into combined.db.

Strategy:
1. Include ALL questions from all three DBs (deduplicating by question ID;
   worldreasoner version preferred over mofe for overlapping questions since
   it generally has more articles).
2. For questions with a non-compliant causal_explanation: clear the explanation
   AND delete their collected articles / events / causal_hypotheses /
   event_outcome_impacts so the question is clean and ready for re-collection.
3. For questions with a compliant explanation: copy all evidence as-is.
4. Rebuild the FTS index.

Compliance check: a causal_explanation is compliant iff it contains all seven
required section headings from hindsight_causal_analysis.py.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORKSPACE = Path(__file__).parent.parent
SOURCE_DBS = {
    "worldreasoner": WORKSPACE / "worldreasoner.db",
    "mofe": WORKSPACE / "mofe_polymarket_curated.db",
    "experiment": WORKSPACE / "experiment.db",
}
OUTPUT_DB = WORKSPACE / "combined.db"

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Timeline Of Key Events",
    "Causal Chain Analysis",
    "Countervailing Factors",
    "Event Candidate Inventory",
    "Evidence Mapping Table",
    "Uncertainties And Alternative Paths",
]


def is_compliant(explanation: Optional[str]) -> bool:
    if not explanation:
        return False
    return all(s in explanation for s in REQUIRED_SECTIONS)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

CANONICAL_QUESTION_COLS = [
    "id", "question_text", "question_type", "domain", "source", "difficulty",
    "resolution_date", "estimated_start_time", "ground_truth", "ground_truth_hash",
    "target_event_id", "outcome_event_ids", "related_event_ids", "related_article_ids",
    "context", "resolution_criteria", "resolution_reasoning", "options",
    "quantity_unit", "quantity_bounds", "is_synthetic", "quality_score",
    "quality_dimensions", "skip_evidence", "skip_reason", "quality_warning",
    "created_at", "updated_at", "metadata", "causal_explanation",
    "graph_built", "graph_build_error",
]


def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def normalize_question_row(row: sqlite3.Row, src_cols: list[str]) -> tuple:
    row_dict = dict(zip(src_cols, row))
    return tuple(row_dict.get(col) for col in CANONICAL_QUESTION_COLS)


# ---------------------------------------------------------------------------
# Step 1: Build combined.db schema
# ---------------------------------------------------------------------------

def create_combined_db() -> sqlite3.Connection:
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    # Extract DDL from worldreasoner.db (most complete schema)
    src_conn = sqlite3.connect(SOURCE_DBS["worldreasoner"])
    schema_rows = src_conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND type IN ('table','index') "
        "AND name NOT LIKE 'articles_fts%'"
    ).fetchall()
    src_conn.close()

    conn = sqlite3.connect(OUTPUT_DB)
    conn.execute("PRAGMA journal_mode=WAL")

    for name, sql in schema_rows:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            print(f"  Schema note [{name}]: {e}")

    # Ensure all canonical question columns exist
    existing_q_cols = get_columns(conn, "questions")
    for col in CANONICAL_QUESTION_COLS:
        if col not in existing_q_cols:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TEXT")

    # FTS: plain content-less fts5 (fastest, no trigger needed for static data)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts
        USING fts5(article_id UNINDEXED, title, content)
    """)

    conn.commit()
    print(f"[INIT] Empty combined.db created at {OUTPUT_DB}")
    return conn


# ---------------------------------------------------------------------------
# Step 2: Determine which DB is the authoritative source per question
# ---------------------------------------------------------------------------

def build_question_source_map() -> dict[str, str]:
    """
    Returns {question_id: db_label} for every unique question across all sources.
    Priority: worldreasoner > mofe > experiment
    (worldreasoner typically has more articles for overlapping questions)
    """
    source_map: dict[str, str] = {}

    # Lower priority first, higher priority overwrites
    for label in ("experiment", "mofe", "worldreasoner"):
        conn = sqlite3.connect(SOURCE_DBS[label])
        ids = [r[0] for r in conn.execute("SELECT id FROM questions").fetchall()]
        conn.close()
        for qid in ids:
            source_map[qid] = label

    counts = {}
    for label in source_map.values():
        counts[label] = counts.get(label, 0) + 1
    print("\n[MAP] Authoritative source per question:")
    for label, cnt in counts.items():
        print(f"  {label}: {cnt}")
    print(f"  TOTAL unique questions: {len(source_map)}")
    return source_map


# ---------------------------------------------------------------------------
# Step 3: Copy questions + evidence from each source
# ---------------------------------------------------------------------------

def copy_questions_from_source(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    question_ids: list[str],
    label: str,
) -> tuple[list[str], list[str]]:
    """
    Insert questions into combined.db. Returns (compliant_ids, non_compliant_ids).
    Non-compliant questions have causal_explanation set to NULL on insert.
    """
    src_cols = get_columns(src_conn, "questions")
    placeholders = ",".join("?" * len(question_ids))
    rows = src_conn.execute(
        f"SELECT {', '.join(src_cols)} FROM questions WHERE id IN ({placeholders})",
        question_ids,
    ).fetchall()

    compliant_ids: list[str] = []
    non_compliant_ids: list[str] = []

    normalized = []
    for row in rows:
        row_dict = dict(zip(src_cols, row))
        expl = row_dict.get("causal_explanation")
        if is_compliant(expl):
            compliant_ids.append(row_dict["id"])
        else:
            non_compliant_ids.append(row_dict["id"])
            # Wipe explanation and article references for non-compliant
            row_dict["causal_explanation"] = None
            row_dict["related_article_ids"] = None
            row_dict["graph_built"] = 0
            row_dict["graph_build_error"] = None
        normalized.append(tuple(row_dict.get(c) for c in CANONICAL_QUESTION_COLS))

    insert_sql = (
        f"INSERT OR IGNORE INTO questions ({', '.join(CANONICAL_QUESTION_COLS)}) "
        f"VALUES ({', '.join('?' * len(CANONICAL_QUESTION_COLS))})"
    )
    dst_conn.executemany(insert_sql, normalized)
    print(f"  Questions inserted: {len(normalized)} "
          f"({len(compliant_ids)} with evidence, {len(non_compliant_ids)} evidence-cleared)")
    return compliant_ids, non_compliant_ids


def copy_table_by_fk(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    table: str,
    fk_col: str,
    question_ids: list[str],
    label: str,
) -> int:
    if not question_ids:
        return 0
    try:
        src_cols = get_columns(src_conn, table)
        dst_cols = get_columns(dst_conn, table)
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


def copy_causal_hypotheses_by_questions(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    question_ids: list[str],
) -> int:
    """Hypotheses store question refs as a JSON array in discovered_by_question_ids."""
    if not question_ids:
        return 0
    try:
        src_cols = get_columns(src_conn, "causal_hypotheses")
        dst_cols = get_columns(dst_conn, "causal_hypotheses")
    except sqlite3.OperationalError:
        return 0
    common = [c for c in src_cols if c in dst_cols]
    q_set = set(question_ids)
    dbq_idx = common.index("discovered_by_question_ids") if "discovered_by_question_ids" in common else None

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


def copy_evidence_for_compliant(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    compliant_ids: list[str],
    label: str,
) -> None:
    """Copy articles, events, hypotheses, impacts only for compliant questions."""
    n_arts = copy_table_by_fk(src_conn, dst_conn, "articles", "collected_for_question_id", compliant_ids, label)
    n_evts = copy_table_by_fk(src_conn, dst_conn, "events", "extracted_for_question_id", compliant_ids, label)
    n_hyps = copy_causal_hypotheses_by_questions(src_conn, dst_conn, compliant_ids)
    n_imps = copy_table_by_fk(src_conn, dst_conn, "event_outcome_impacts", "question_id", compliant_ids, label)
    print(f"  Evidence: {n_arts} articles, {n_evts} events, "
          f"{n_hyps} hypotheses, {n_imps} outcome_impacts")


# ---------------------------------------------------------------------------
# Step 4: Rebuild FTS
# ---------------------------------------------------------------------------

def rebuild_fts(conn: sqlite3.Connection) -> None:
    print("\n[FTS] Rebuilding articles_fts...")
    conn.execute("DROP TABLE IF EXISTS articles_fts")
    conn.execute("""
        CREATE VIRTUAL TABLE articles_fts
        USING fts5(article_id UNINDEXED, title, content)
    """)
    conn.execute("""
        INSERT INTO articles_fts (article_id, title, content)
        SELECT id, COALESCE(title, ''), COALESCE(content, '') FROM articles
    """)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    print(f"  FTS index: {count} entries")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("WorldReasoner Database Merger")
    print("=" * 60)

    # Determine authoritative source for each question ID
    source_map = build_question_source_map()

    # Group question IDs by their authoritative source
    ids_by_source: dict[str, list[str]] = {label: [] for label in SOURCE_DBS}
    for qid, label in source_map.items():
        ids_by_source[label].append(qid)

    # Create empty combined.db
    dst_conn = create_combined_db()

    # Copy from each source
    total_compliant = 0
    total_non_compliant = 0

    for label, db_path in SOURCE_DBS.items():
        q_ids = ids_by_source[label]
        print(f"\n[COPY] {label} -> combined.db ({len(q_ids)} questions)")
        if not q_ids:
            print("  (nothing to copy)")
            continue

        src_conn = sqlite3.connect(db_path)
        src_conn.row_factory = sqlite3.Row

        compliant_ids, non_compliant_ids = copy_questions_from_source(
            src_conn, dst_conn, q_ids, label
        )
        copy_evidence_for_compliant(src_conn, dst_conn, compliant_ids, label)

        total_compliant += len(compliant_ids)
        total_non_compliant += len(non_compliant_ids)
        src_conn.close()

    dst_conn.commit()

    # Rebuild FTS
    rebuild_fts(dst_conn)

    # Final stats
    print("\n[STATS] combined.db final counts:")
    for t in ["questions", "articles", "events", "causal_hypotheses", "event_outcome_impacts"]:
        count = dst_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count}")

    print(f"\n  Questions with compliant explanation + evidence: {total_compliant}")
    print(f"  Questions with cleared evidence (need re-collection): {total_non_compliant}")

    # Sanity check
    all_q = dst_conn.execute("SELECT id, causal_explanation FROM questions").fetchall()
    dirty = [qid for qid, expl in all_q if expl and not is_compliant(expl)]
    if dirty:
        print(f"\n  WARNING: {len(dirty)} questions still have non-compliant explanations!")
        for qid in dirty:
            print(f"    {qid}")
    else:
        print("  Sanity check passed: no non-compliant explanations in combined.db")

    # Article coverage
    article_counts = dst_conn.execute("""
        SELECT q.id,
               COUNT(a.id) as cnt,
               q.causal_explanation IS NOT NULL as has_expl
        FROM questions q
        LEFT JOIN articles a ON a.collected_for_question_id = q.id
        GROUP BY q.id
    """).fetchall()
    has_expl_no_art = [(qid, cnt) for qid, cnt, has_expl in article_counts if has_expl and cnt == 0]
    no_expl_with_art = [(qid, cnt) for qid, cnt, has_expl in article_counts if not has_expl and cnt > 0]
    print(f"  Questions with explanation but 0 articles: {len(has_expl_no_art)}")
    print(f"  Questions without explanation but with articles: {len(no_expl_with_art)}")

    dst_conn.close()
    print(f"\n[DONE] {OUTPUT_DB}")


if __name__ == "__main__":
    main()
