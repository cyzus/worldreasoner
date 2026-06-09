#!/usr/bin/env python3
"""Export a sanitized version of combined.db for public release.

What is kept:
  - questions: all columns (public Polymarket questions, no PII)
  - events: all columns (extracted event graph)
  - causal_hypotheses: all columns (causal graph edges)
  - event_outcome_impacts: all columns
  - articles: id, title, url, source, published_date, domain, word_count,
              event_ids, collected_for_question_id, is_synthetic
              (NO content — full article text is copyright-problematic)
  - forecasts: id, question_id, model_name, simulated_date, prediction,
               confidence, is_correct, brier_score, log_score,
               evaluation_metadata
               (NO reasoning, articles_accessed, searches_performed — large LLM outputs)
  - forecast_events / forecast_hypotheses: stripped to key fields
  - articles_fts: rebuilt from sanitized articles (title only)

What is dropped:
  - archived_* tables (internal archive)
  - audit_* tables (internal QC logs)
  - article_embeddings (large binary blobs, rebuild with wr db build-index)
  - articles.content (copyright)
  - forecasts.reasoning (large LLM text, not needed for reproducibility)
"""

import argparse
import sqlite3
from pathlib import Path


def export_public_db(src: str, dst: str) -> None:
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dst)
    src_conn.row_factory = sqlite3.Row

    # Helper to copy a table with column selection
    def copy_table(table: str, cols: list[str] | None = None, where: str = "") -> None:
        col_sql = "*" if cols is None else ", ".join(cols)
        rows = src_conn.execute(
            f"SELECT {col_sql} FROM {table}" + (f" WHERE {where}" if where else "")
        ).fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skipped)")
            return
        # Create table from first row schema
        placeholders = ", ".join("?" * len(rows[0]))
        headers = ", ".join(rows[0].keys())
        dst_conn.execute(f"DROP TABLE IF EXISTS {table}")
        # Recreate schema from source
        src_schema = src_conn.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if src_schema and src_schema[0]:
            if cols is None:
                dst_conn.execute(src_schema[0])
            else:
                # Build minimal CREATE TABLE from selected cols
                src_info = {r[1]: r for r in src_conn.execute(f"PRAGMA table_info({table})")}
                col_defs = []
                for c in cols:
                    info = src_info.get(c)
                    if info:
                        notnull = " NOT NULL" if info[3] else ""
                        default = f" DEFAULT {info[4]}" if info[4] is not None else ""
                        col_defs.append(f"{c} {info[2]}{notnull}{default}")
                dst_conn.execute(f"CREATE TABLE {table} ({', '.join(col_defs)})")
        dst_conn.executemany(
            f"INSERT INTO {table} ({headers}) VALUES ({placeholders})",
            [tuple(r) for r in rows]
        )
        print(f"  {table}: {len(rows)} rows")

    print("Exporting sanitized DB...")

    copy_table("questions")
    copy_table("events")
    copy_table("causal_hypotheses")
    copy_table("event_outcome_impacts")

    # Articles: no content column
    copy_table("articles", [
        "id", "title", "url", "source", "author", "published_date",
        "domain", "tags", "is_synthetic", "word_count", "reading_time_minutes",
        "event_ids", "collected_for_question_id", "created_at", "updated_at",
    ])

    # Forecasts: no reasoning/searches/articles_accessed
    copy_table("forecasts", [
        "id", "question_id", "model_name", "model_version", "mode",
        "simulated_date", "prediction", "confidence",
        "is_correct", "brier_score", "log_score",
        "evaluation_metadata", "enabled_tools",
        "created_at", "updated_at",
    ])

    # Forecast events/hypotheses: key fields only
    copy_table("forecast_events", [
        "id", "forecast_id", "title", "description", "domain",
        "occurred_date", "event_type", "status", "identified_by", "created_at",
    ])
    copy_table("forecast_hypotheses", [
        "id", "forecast_id", "source_event_id", "target_event_id",
        "relation_type", "strength", "confidence", "identified_by", "created_at",
    ])

    dst_conn.commit()

    total = sum(
        dst_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ["questions", "events", "causal_hypotheses", "event_outcome_impacts",
                  "articles", "forecasts", "forecast_events", "forecast_hypotheses"]
    )
    print(f"\nDone → {dst}  ({total} total rows)")
    print("Note: article embeddings and FTS index excluded — rebuild with:")
    print("  wr db build-index --db", dst)

    src_conn.close()
    dst_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default="combined.db", help="Source database")
    parser.add_argument("--dst", default="worldreasoner_public.db", help="Output database")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        raise SystemExit(f"Source DB not found: {src}")
    if dst.exists():
        dst.unlink()
    export_public_db(str(src), str(dst))
