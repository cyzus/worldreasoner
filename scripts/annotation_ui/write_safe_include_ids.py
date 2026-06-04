"""Write an annotation include-id file excluding questions flagged for regen."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="combined.db")
    parser.add_argument("--input", default="include_ids.txt")
    parser.add_argument("--output", default="include_ids_annotation_safe.txt")
    args = parser.parse_args()

    include_path = Path(args.input)
    ids = [line.strip() for line in include_path.read_text().splitlines() if line.strip()]

    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            select distinct question_id
            from audit_question_flags
            where flag='requires_annotation_regeneration'
            """
        ).fetchall()
    finally:
        conn.close()

    excluded = {row[0] for row in rows}
    kept = [qid for qid in ids if qid not in excluded]
    dropped = [qid for qid in ids if qid in excluded]

    Path(args.output).write_text("\n".join(kept) + "\n")
    print(f"original={len(ids)}")
    print(f"excluded={len(dropped)}")
    print(f"kept={len(kept)}")
    for qid in dropped:
        print(f"excluded_id={qid}")


if __name__ == "__main__":
    main()
