"""
Export annotation data from combined.db to annotation_data.js for the UI.
Automatically fetches and caches Polymarket price history before exporting.

Usage:
    # Full export (fetches price data, then exports):
    python scripts/annotation_ui/export_data.py --db combined.db

    # Skip price fetch (use existing cache):
    python scripts/annotation_ui/export_data.py --db combined.db --no-fetch

    # Per-annotator export:
    python scripts/annotation_ui/export_data.py --db combined.db --annotator alice --total-annotators 3
    python scripts/annotation_ui/export_data.py --db combined.db --annotator bob   --total-annotators 3
    python scripts/annotation_ui/export_data.py --db combined.db --annotator carol --total-annotators 3

    # Custom overlap set:
    python scripts/annotation_ui/export_data.py --db combined.db --annotator alice --total-annotators 3 --overlap-ids overlap.txt

    # Prolific mode (generates per-session files for GitHub Pages deployment):
    python scripts/annotation_ui/export_data.py --db combined.db --mode prolific --output-dir prolific_sessions --overlap-ids overlap.txt
    python scripts/annotation_ui/export_data.py --db combined.db --mode prolific --output-dir prolific_sessions --overlap-ids overlap.txt --no-fetch
"""

import asyncio
import json
import os
import sys
import hashlib
import argparse
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.database import GenericDatabase
from src.domain.models import Question, Event
from scripts.annotation_ui.fetch_price_history import fetch_for_question, load_cache, save_cache
from src.integrations.polymarket import analyze_price_curve

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_CACHE_FILE = os.path.join(SCRIPT_DIR, "price_cache.json")
MAX_EVENTS_PER_QUESTION = 10
MARKET_OPEN_FALLBACK_DAYS = 90


async def _refresh_price_cache(questions: list) -> dict:
    """Fetch missing price history for polymarket questions and return updated cache."""
    cache = load_cache()
    polymarket_qs = [
        q for q in questions
        if getattr(q, "source", "") == "polymarket"
        and (getattr(q, "metadata", None) or {}).get("clob_token_ids")
    ]
    missing = [q for q in polymarket_qs if q.id not in cache]
    if not missing:
        return cache
    print(f"Fetching price history for {len(missing)} questions (already cached: {len(polymarket_qs) - len(missing)})...")
    for i, q in enumerate(missing, 1):
        print(f"  [{i}/{len(missing)}] {q.id[:55]}", end="", flush=True)
        ok = await fetch_for_question(q, cache)
        if ok:
            save_cache(cache)
            print(f" -> {len(cache[q.id]['history'])} pts")
        else:
            print(" -> no data")
        await asyncio.sleep(0.3)
    return cache


def get_market_window(q: Question):
    """Return (open_dt, close_dt, open_is_estimated) for a question."""
    close_dt = getattr(q, "resolution_date", None)
    open_dt = getattr(q, "estimated_start_time", None)
    estimated = False

    if open_dt is None and close_dt is not None:
        if hasattr(close_dt, "timestamp"):
            open_dt = close_dt - timedelta(days=MARKET_OPEN_FALLBACK_DAYS)
        estimated = True

    return open_dt, close_dt, estimated


def to_iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def in_market_window(event_date_str: str, open_dt, close_dt) -> bool:
    if not event_date_str or event_date_str == "Unknown Date":
        return False
    try:
        ed = datetime.fromisoformat(str(event_date_str).replace(" ", "T"))
        if ed.tzinfo is None:
            ed = ed.replace(tzinfo=timezone.utc)
    except Exception:
        return False

    def to_aware(dt):
        if dt is None:
            return None
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    lo = to_aware(open_dt)
    hi = to_aware(close_dt)
    if lo and ed < lo:
        return False
    if hi and ed > hi:
        return False
    return True


CHANGE_POINT_TOLERANCE_DAYS = 5


def get_change_point_timestamps(price_data: dict) -> list:
    """Return unix-second timestamps of all turning points, sharp movements, and lead changes."""
    history = (price_data or {}).get("history", [])
    if not history:
        return []
    try:
        analysis = analyze_price_curve(history)
    except Exception:
        return []
    timestamps = []
    for pt in analysis.get("turning_points", []):
        if "timestamp" in pt:
            timestamps.append(pt["timestamp"])
    for mv in analysis.get("sharp_movements", []):
        if "start_timestamp" in mv:
            timestamps.append(mv["start_timestamp"])
    for lc in analysis.get("lead_changes", []):
        if "timestamp" in lc:
            timestamps.append(lc["timestamp"])
    return timestamps


def is_near_change_point(event_date_str: str, change_point_timestamps: list) -> bool:
    if not event_date_str or event_date_str == "Unknown Date" or not change_point_timestamps:
        return False
    try:
        ed = datetime.fromisoformat(str(event_date_str).replace(" ", "T"))
        if ed.tzinfo is None:
            ed = ed.replace(tzinfo=timezone.utc)
        event_ts = ed.timestamp()
    except Exception:
        return False
    tolerance = CHANGE_POINT_TOLERANCE_DAYS * 86400
    return any(abs(event_ts - cp_ts) <= tolerance for cp_ts in change_point_timestamps)


def assign_partition(question_id: str, all_annotators: list) -> str:
    """Deterministically assign a question to one annotator by hash."""
    digest = int(hashlib.sha256(question_id.encode()).hexdigest(), 16)
    return all_annotators[digest % len(all_annotators)]


async def _build_all_question_data(
    db_path: str,
    overlap_ids: set,
    fetch_prices: bool = True,
    include_ids: Optional[set] = None,
) -> list:
    """Load all questions from DB and build export-ready dicts.

    Returns a deterministically sorted list of q_data dicts (all questions).
    Each dict includes is_overlap based on overlap_ids.
    If include_ids is provided, only those question IDs are exported.
    """
    db = GenericDatabase(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT e.extracted_for_question_id
        FROM events e
        WHERE e.is_outcome = 0
          AND (e.review_note IS NULL OR e.review_note != 'Auto-approved (outcome event)')
          AND (e.review_status IS NULL OR e.review_status != 'rejected')
          AND e.extracted_for_question_id IS NOT NULL
    """)
    valid_q_ids = set(r[0] for r in cursor.fetchall())

    all_questions = db.get_many(Question)
    questions = [q for q in all_questions if q.id in valid_q_ids]
    if include_ids:
        questions = [q for q in questions if q.id in include_ids]
    questions.sort(key=lambda q: q.id)

    if fetch_prices:
        price_cache = await _refresh_price_cache(questions)
    else:
        price_cache = load_cache()

    export_data = []

    for q in questions:
        is_overlap = q.id in (overlap_ids or set())
        events = db.get_many(Event, filters={"extracted_for_question_id": q.id})
        if not events:
            continue

        try:
            events = sorted(events, key=lambda e: str(getattr(e, "occurred_date", "") or ""))
        except Exception:
            pass

        open_dt, close_dt, open_estimated = get_market_window(q)
        is_polymarket = getattr(q, "source", "") == "polymarket"
        meta = getattr(q, "metadata", None) or {}
        market_slug = meta.get("market_slug")
        polymarket_url = f"https://polymarket.com/event/{market_slug}" if market_slug else None

        change_point_timestamps = get_change_point_timestamps(price_cache.get(q.id)) if is_polymarket else []

        valid_events = []
        for e in events:
            if getattr(e, "is_outcome", False):
                continue
            if getattr(e, "review_note", "") == "Auto-approved (outcome event)":
                continue
            status = getattr(e, "review_status", "pending")
            if hasattr(status, "value"):
                status = status.value
            if status == "rejected":
                continue

            date_val = getattr(e, "occurred_date", None) or "Unknown Date"
            if hasattr(date_val, "strftime"):
                date_val = date_val.strftime("%Y-%m-%d %H:%M")

            if close_dt is not None and date_val != "Unknown Date":
                try:
                    ed = datetime.fromisoformat(str(date_val).replace(" ", "T"))
                    if ed.tzinfo is None:
                        ed = ed.replace(tzinfo=timezone.utc)
                    cd = close_dt if close_dt.tzinfo else close_dt.replace(tzinfo=timezone.utc)
                    if ed > cd:
                        continue
                except Exception:
                    pass

            impact_text = None
            has_impact = False
            try:
                cursor.execute(
                    "SELECT impact_direction, reasoning, impact_magnitude, confidence, outcome_event_id "
                    "FROM event_outcome_impacts WHERE event_id = ?",
                    (e.id,),
                )
                row = cursor.fetchone()
                if row:
                    has_impact = True
                    raw_dir = str(row[0]).replace("ImpactDirection.", "").lower()
                    dir_label = {
                        "positive": "Towards outcome",
                        "negative": "Against outcome",
                        "neutral":  "Neutral",
                        "mixed":    "Mixed",
                    }.get(raw_dir, raw_dir.capitalize())
                    outcome_title = "Unknown Outcome"
                    if row[4]:
                        cursor.execute("SELECT title FROM events WHERE id = ?", (row[4],))
                        r2 = cursor.fetchone()
                        if r2 and r2[0]:
                            outcome_title = r2[0]
                    impact_text = (
                        f"**Affects:** {outcome_title}  \n\n"
                        f"**Direction:** {dir_label}    \n\n"
                        f"**Reasoning:**\n{row[1]}"
                    )
            except Exception:
                pass

            article_url = None
            try:
                article_id = None
                if hasattr(e, "source_article_id") and e.source_article_id:
                    article_id = e.source_article_id
                elif hasattr(e, "article_ids") and e.article_ids:
                    ids = json.loads(e.article_ids) if isinstance(e.article_ids, str) else e.article_ids
                    if ids:
                        article_id = ids[0]
                if article_id:
                    cursor.execute("SELECT url FROM articles WHERE id = ?", (article_id,))
                    r = cursor.fetchone()
                    if r:
                        article_url = r[0]
            except Exception:
                pass

            in_window = in_market_window(str(date_val), open_dt, close_dt) if is_polymarket else False
            at_change_point = is_near_change_point(str(date_val), change_point_timestamps)

            if at_change_point:
                priority = 0
            elif in_window:
                priority = 1
            elif has_impact:
                priority = 2
            else:
                priority = 3

            valid_events.append({
                "_priority": priority,
                "id": e.id,
                "date": str(date_val),
                "title": getattr(e, "title", "Untitled Event"),
                "description": getattr(e, "description", "") or "",
                "impact": impact_text or "No impact assessment provided.",
                "has_impact": has_impact,
                "in_market_window": in_window,
                "source_url": article_url,
                "current_status": status if status != "pending" else "pending",
                "reasoning_status": None,
                "reject_reason": None,
            })

        valid_events.sort(key=lambda x: x["_priority"])

        if len(valid_events) > MAX_EVENTS_PER_QUESTION:
            kept = []
            remaining = MAX_EVENTS_PER_QUESTION
            for tier in range(4):
                tier_events = [e for e in valid_events if e["_priority"] == tier]
                if not tier_events:
                    continue
                if len(tier_events) <= remaining:
                    kept.extend(tier_events)
                    remaining -= len(tier_events)
                else:
                    step = len(tier_events) / remaining
                    kept.extend(tier_events[int(i * step)] for i in range(remaining))
                    remaining = 0
                if remaining == 0:
                    break
            valid_events = kept

        for ev in valid_events:
            del ev["_priority"]

        if not valid_events:
            continue

        raw_options = getattr(q, "options", None)
        if isinstance(raw_options, str):
            try:
                raw_options = json.loads(raw_options)
            except Exception:
                raw_options = None
        if not raw_options:
            raw_options = []

        _qt = getattr(q, "question_type", "binary")
        q_type = _qt.value if hasattr(_qt, "value") else str(_qt)
        ground_truth = str(getattr(q, "ground_truth", "Unknown"))

        if not raw_options:
            raw_options = meta.get("options") or []
        if not raw_options:
            if q_type == "binary":
                raw_options = ["Yes", "No"]
            else:
                raw_options = [ground_truth] if ground_truth not in ("Unknown", "None", "") else []

        export_data.append({
            "id": q.id,
            "title": q.question_text,
            "question_type": q_type,
            "options": raw_options,
            "background": getattr(q, "context", None) or "No background available.",
            "resolution_criteria": getattr(q, "resolution_criteria", None) or "No criteria available.",
            "outcome": str(getattr(q, "ground_truth", "Unknown")),
            "explanation": getattr(q, "causal_explanation", None) or "No causal explanation available.",
            "is_polymarket": is_polymarket,
            "is_overlap": is_overlap,
            "market_open": to_iso(open_dt),
            "market_open_estimated": open_estimated,
            "market_close": to_iso(close_dt),
            "polymarket_url": polymarket_url,
            "price_data": price_cache.get(q.id),
            "events": valid_events,
        })

    conn.close()
    return export_data


async def export_for_annotation(
    db_path: str = "combined.db",
    output_file: str = None,
    annotator: Optional[str] = None,
    total_annotators: int = 1,
    annotator_names: Optional[list] = None,
    overlap_ids: Optional[set] = None,
    include_ids: Optional[set] = None,
    fetch_prices: bool = True,
):
    if output_file is None:
        suffix = f"_{annotator}" if annotator else ""
        output_file = os.path.join(SCRIPT_DIR, f"annotation_data{suffix}.js")

    if overlap_ids is None:
        overlap_ids = set()

    if annotator_names:
        all_annotators = annotator_names
    elif annotator and total_annotators > 1:
        all_annotators = [f"annotator_{i}" for i in range(total_annotators)]
        all_annotators[0] = annotator
    else:
        all_annotators = [annotator or "default"]

    all_data = await _build_all_question_data(db_path, overlap_ids, fetch_prices, include_ids)

    if annotator and len(all_annotators) > 1:
        export_data = [
            q for q in all_data
            if q["is_overlap"] or assign_partition(q["id"], all_annotators) == annotator
        ]
    else:
        export_data = all_data

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"var annotationData = {json.dumps(export_data, indent=2, ensure_ascii=False)};")

    event_count = sum(len(q["events"]) for q in export_data)
    print(f"Exported {len(export_data)} questions, {event_count} events -> {output_file}")
    if annotator:
        overlap_count = sum(1 for q in export_data if q["is_overlap"])
        print(f"   Annotator: {annotator} | Unique: {len(export_data) - overlap_count} | Overlap: {overlap_count}")
    if not os.path.exists(PRICE_CACHE_FILE):
        print("price_cache.json not found -- run fetch_price_history.py first for market charts.")


def _pair_into_sessions(questions: list, questions_per_session: int) -> list:
    """Interleave polymarket/news questions then chunk into fixed-size sessions."""
    poly = [q for q in questions if q["is_polymarket"]]
    news = [q for q in questions if not q["is_polymarket"]]
    interleaved = []
    p, n = 0, 0
    while p < len(poly) or n < len(news):
        if p < len(poly):
            interleaved.append(poly[p]); p += 1
        if n < len(news):
            interleaved.append(news[n]); n += 1
    return [interleaved[i:i + questions_per_session]
            for i in range(0, len(interleaved), questions_per_session)]


async def export_for_prolific(
    db_path: str,
    output_dir: str,
    overlap_ids: set = None,
    include_ids: Optional[set] = None,
    questions_per_session: int = 2,
    fetch_prices: bool = True,
):
    """Generate per-session JS files for Prolific deployment.

    Output directory contains:
      annotation_data_s01.js … sNN.js   — unique question sessions (1 participant each)
      annotation_data_ov01.js … ovMM.js — overlap sessions (3 participants each)
      manifest.json                      — lists all sessions for Prolific setup
    """
    if overlap_ids is None:
        overlap_ids = set()

    os.makedirs(output_dir, exist_ok=True)

    all_data = await _build_all_question_data(db_path, overlap_ids, fetch_prices, include_ids)
    overlap_qs = [q for q in all_data if q["is_overlap"]]
    unique_qs  = [q for q in all_data if not q["is_overlap"]]

    unique_sessions  = _pair_into_sessions(unique_qs,  questions_per_session)
    overlap_sessions = _pair_into_sessions(overlap_qs, questions_per_session)

    manifest = {
        "unique_sessions": [],
        "overlap_sessions": [],
        "questions_per_session": questions_per_session,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    def write_session(session_id: str, questions: list) -> None:
        out_path = os.path.join(output_dir, f"annotation_data_{session_id}.js")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"var annotationData = {json.dumps(questions, indent=2, ensure_ascii=False)};")

    for i, session in enumerate(unique_sessions, 1):
        sid = f"s{i:02d}"
        write_session(sid, session)
        manifest["unique_sessions"].append({
            "id": sid,
            "questions": len(session),
            "question_ids": [q["id"] for q in session],
        })
        print(f"  [{sid}] {len(session)} questions")

    for i, session in enumerate(overlap_sessions, 1):
        sid = f"ov{i:02d}"
        write_session(sid, session)
        manifest["overlap_sessions"].append({
            "id": sid,
            "questions": len(session),
            "question_ids": [q["id"] for q in session],
            "annotators_needed": 3,
        })
        print(f"  [{sid}] {len(session)} overlap questions")

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    n_unique  = len(unique_sessions)
    n_overlap = len(overlap_sessions)
    print(f"\nExported {len(unique_qs)} unique + {len(overlap_qs)} overlap questions")
    print(f"→ {n_unique} unique sessions + {n_overlap} overlap sessions → {output_dir}/")
    print(f"→ Manifest: {manifest_path}")
    print(f"\n── Prolific setup ──────────────────────────────────────────────────")
    print(f"  Unique batch  : {n_unique} participant slots  (s01 – s{n_unique:02d})")
    print(f"  Overlap batch : {n_overlap} sessions × 3 participants = {n_overlap * 3} slots  (ov01 – ov{n_overlap:02d})")
    print(f"  URL template  : https://<your-site>/?session=s01&PROLIFIC_PID={{%PROLIFIC_PID%}}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export data for UI annotation.")
    parser.add_argument("--db", default="combined.db", help="Path to SQLite DB")
    parser.add_argument("--mode", choices=["annotator", "prolific"], default="annotator",
                        help="'annotator' (default) or 'prolific' (per-session files for GitHub Pages)")
    # annotator mode
    parser.add_argument("--out", default=None, help="Output JS file (auto-named if omitted)")
    parser.add_argument("--annotator", default=None, help="Annotator name (omit for full export)")
    parser.add_argument("--total-annotators", type=int, default=1)
    parser.add_argument("--annotator-names", nargs="+", default=None)
    # prolific mode
    parser.add_argument("--output-dir", default=None,
                        help="[prolific] Directory to write session files (default: prolific_sessions/)")
    parser.add_argument("--questions-per-session", type=int, default=2,
                        help="[prolific] Questions per session (default: 2)")
    # shared
    parser.add_argument("--overlap-ids", default=None,
                        help="Path to file with one question ID per line for the overlap set")
    parser.add_argument("--include-ids", default=None,
                        help="Path to file with one question ID per line; only these questions are exported (all polymarket + selected news)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip price history fetch; use existing cache only")
    args = parser.parse_args()

    def _read_ids(path):
        if path and os.path.exists(path):
            with open(path) as f:
                return set(line.strip() for line in f if line.strip())
        return set()

    overlap_ids = _read_ids(args.overlap_ids)
    include_ids = _read_ids(args.include_ids) or None

    if args.mode == "prolific":
        output_dir = args.output_dir or os.path.join(SCRIPT_DIR, "prolific_sessions")
        asyncio.run(export_for_prolific(
            db_path=args.db,
            output_dir=output_dir,
            overlap_ids=overlap_ids,
            include_ids=include_ids,
            questions_per_session=args.questions_per_session,
            fetch_prices=not args.no_fetch,
        ))
    else:
        asyncio.run(export_for_annotation(
            db_path=args.db,
            output_file=args.out,
            annotator=args.annotator,
            total_annotators=args.total_annotators,
            annotator_names=args.annotator_names,
            overlap_ids=overlap_ids,
            include_ids=include_ids,
            fetch_prices=not args.no_fetch,
        ))
