"""
Apply annotation majority votes to events.review_status in combined.db.

Rules:
  - majority accepted (or tied) -> review_status = 'approved'
  - majority rejected            -> review_status = 'rejected'
  - skipped only / no vote       -> leave as pending

Excluded sessions: s22 (poor market direction intuition)
Failed attention check sessions are already excluded at load time.
"""
import json, sqlite3
from pathlib import Path
from collections import defaultdict

ANNOTATED_DIR = Path("d:/workspace/wr/annotated")
DB_PATH = "combined.db"
ACCEPT_REASONS = {"PredictionNotEvent", "Noise", "Duplicate", "TooBoard"}
FACTUAL_ERROR_REASONS = {"Fabricated", "WrongDate", "SourceMismatch"}
EXCLUDED_SESSIONS = {"s22"}


def load_votes():
    sessions = []
    for path in sorted(ANNOTATED_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if all(c.get("passed", False) for c in d.get("attention_checks", [])):
            sessions.append(d)

    judgments = defaultdict(list)
    for sess in sessions:
        sid = sess.get("session_id", "?")
        if sid in EXCLUDED_SESSIONS:
            continue
        attn_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
        for q in sess.get("data", []):
            if q["id"] in attn_qids:
                continue
            for ev in q.get("events", []):
                st = ev.get("current_status")
                rr = ev.get("reject_reason")
                if st == "skipped":
                    continue
                if st == "approved" or rr in ACCEPT_REASONS:
                    judgments[ev["id"]].append("accepted")
                else:
                    judgments[ev["id"]].append("rejected")
    return judgments


def main():
    judgments = load_votes()

    approved_ids = []
    rejected_ids = []
    for eid, votes in judgments.items():
        n_acc = votes.count("accepted")
        n_rej = votes.count("rejected")
        if n_acc >= n_rej:  # majority accepted OR tied -> approved
            approved_ids.append((eid, f"annotation: {n_acc}acc/{n_rej}rej"))
        else:
            rejected_ids.append((eid, f"annotation: {n_acc}acc/{n_rej}rej"))

    print(f"Votes loaded: {len(judgments)} events")
    print(f"  -> approved (incl. ties): {len(approved_ids)}")
    print(f"  -> rejected:              {len(rejected_ids)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Apply
    approved_count = 0
    rejected_count = 0
    for eid, note in approved_ids:
        conn.execute(
            "UPDATE events SET review_status='approved', review_note=? WHERE id=?",
            (note, eid)
        )
        approved_count += 1
    for eid, note in rejected_ids:
        conn.execute(
            "UPDATE events SET review_status='rejected', review_note=? WHERE id=?",
            (note, eid)
        )
        rejected_count += 1

    conn.commit()

    # Verify
    dist = conn.execute(
        "SELECT review_status, COUNT(*) as n FROM events GROUP BY review_status"
    ).fetchall()
    print("\nUpdated review_status distribution:")
    for r in dist:
        print(f"  {repr(r['review_status'])}: {r['n']}")

    conn.close()
    print(f"\nDone. {approved_count} approved, {rejected_count} rejected.")


if __name__ == "__main__":
    main()
