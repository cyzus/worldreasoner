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


def assign_partition(question_id: str, all_annotators: list) -> str:
    """Deterministically assign a question to one annotator by hash."""
    digest = int(hashlib.sha256(question_id.encode()).hexdigest(), 16)
    return all_annotators[digest % len(all_annotators)]


async def export_for_annotation(
    db_path: str = "combined.db",
    output_file: str = None,
    annotator: Optional[str] = None,
    total_annotators: int = 1,
    annotator_names: Optional[list] = None,
    overlap_ids: Optional[set] = None,
    fetch_prices: bool = True,
):
    if output_file is None:
        suffix = f"_{annotator}" if annotator else ""
        output_file = os.path.join(SCRIPT_DIR, f"annotation_data{suffix}.js")

    db = GenericDatabase(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # All questions that have at least one annotatable (non-outcome, non-rejected) event
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

    # Sort deterministically by id so partitioning is stable across runs
    questions.sort(key=lambda q: q.id)

    # Build annotator list for partitioning
    if annotator_names:
        all_annotators = annotator_names
    elif annotator and total_annotators > 1:
        # Synthetic names: annotator itself + positional slots
        all_annotators = [f"annotator_{i}" for i in range(total_annotators)]
        # Replace slot 0 with the actual annotator name so the hash is predictable
        # In practice, always pass --annotator-names when using named annotators
        all_annotators[0] = annotator
    else:
        all_annotators = [annotator or "default"]

    if overlap_ids is None:
        overlap_ids = set()

    # Fetch / load price cache
    if fetch_prices:
        price_cache = await _refresh_price_cache(questions)
    else:
        price_cache = load_cache()

    export_data = []
    event_count = 0

    for q in questions:
        # Partitioning: include if this is the annotator's slice OR an overlap question
        is_overlap = q.id in overlap_ids
        if annotator and len(all_annotators) > 1 and not is_overlap:
            assigned = assign_partition(q.id, all_annotators)
            if assigned != annotator:
                continue

        events = db.get_many(Event, filters={"extracted_for_question_id": q.id})
        if not events:
            continue

        # Chronological sort
        try:
            events = sorted(events, key=lambda e: str(getattr(e, "occurred_date", "") or ""))
        except Exception:
            pass

        open_dt, close_dt, open_estimated = get_market_window(q)
        is_polymarket = getattr(q, "source", "") == "polymarket"
        meta = getattr(q, "metadata", None) or {}
        market_slug = meta.get("market_slug")
        polymarket_url = f"https://polymarket.com/event/{market_slug}" if market_slug else None

        # Build valid event list with priority tags
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

            # Check impact analysis
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
                    mag_str = f" ({int(row[2] * 100)}%)" if row[2] is not None else ""
                    conf_str = f"**Confidence:** {int(row[3] * 100)}%" if row[3] is not None else ""
                    outcome_title = "Unknown Outcome"
                    if row[4]:
                        cursor.execute("SELECT title FROM events WHERE id = ?", (row[4],))
                        r2 = cursor.fetchone()
                        if r2 and r2[0]:
                            outcome_title = r2[0]
                    impact_text = (
                        f"**Affects:** {outcome_title}  \n"
                        f"**Direction:** {dir_label}{mag_str}\n{conf_str}\n\n"
                        f"**Reasoning:**\n{row[1]}"
                    )
            except Exception:
                pass

            # Source URL
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

            # Priority tier for sorting (lower = higher priority)
            if has_impact and in_window:
                priority = 0
            elif has_impact:
                priority = 1
            elif in_window:
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

        # Sort by priority tier (stable — preserves chronological order within tier)
        valid_events.sort(key=lambda x: x["_priority"])

        # Cap at MAX_EVENTS_PER_QUESTION; within a tier use uniform stride if over-represented
        if len(valid_events) > MAX_EVENTS_PER_QUESTION:
            # Keep all tier-0, fill remaining slots with strides from lower tiers
            tier0 = [e for e in valid_events if e["_priority"] == 0]
            rest = [e for e in valid_events if e["_priority"] > 0]
            slots = MAX_EVENTS_PER_QUESTION - min(len(tier0), MAX_EVENTS_PER_QUESTION)
            if len(tier0) >= MAX_EVENTS_PER_QUESTION:
                valid_events = tier0[:MAX_EVENTS_PER_QUESTION]
            elif rest:
                step = len(rest) / slots
                sampled_rest = [rest[int(i * step)] for i in range(slots)]
                valid_events = tier0 + sampled_rest
            else:
                valid_events = tier0

        # Remove internal sort key
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

        # Synthesize options when DB has none
        if not raw_options:
            if q_type == "binary":
                raw_options = ["Yes", "No"]
            else:
                # For MCQ/quantity/timeframe: show ground_truth as the only known option
                raw_options = [ground_truth] if ground_truth not in ("Unknown", "None", "") else []

        q_data = {
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
        }

        export_data.append(q_data)
        event_count += len(valid_events)

    conn.close()

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"const annotationData = {json.dumps(export_data, indent=2, ensure_ascii=False)};")

    print(f"Exported {len(export_data)} questions, {event_count} events -> {output_file}")
    if annotator:
        overlap_count = sum(1 for q in export_data if q["is_overlap"])
        print(f"   Annotator: {annotator} | Unique: {len(export_data) - overlap_count} | Overlap: {overlap_count}")
    if not os.path.exists(PRICE_CACHE_FILE):
        print("price_cache.json not found -- run fetch_price_history.py first for market charts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export data for UI annotation.")
    parser.add_argument("--db", default="combined.db", help="Path to SQLite DB")
    parser.add_argument("--out", default=None, help="Output JS file (auto-named if omitted)")
    parser.add_argument("--annotator", default=None, help="Annotator name (omit for full export)")
    parser.add_argument("--total-annotators", type=int, default=1, help="Total number of annotators")
    parser.add_argument("--annotator-names", nargs="+", default=None,
                        help="Ordered list of annotator names (must match --total-annotators)")
    parser.add_argument("--overlap-ids", default=None,
                        help="Path to file with one question ID per line for overlap set")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip price history fetch and use existing cache only")
    args = parser.parse_args()

    overlap_ids = set()
    if args.overlap_ids and os.path.exists(args.overlap_ids):
        with open(args.overlap_ids) as f:
            overlap_ids = set(line.strip() for line in f if line.strip())

    asyncio.run(export_for_annotation(
        db_path=args.db,
        output_file=args.out,
        annotator=args.annotator,
        total_annotators=args.total_annotators,
        annotator_names=args.annotator_names,
        overlap_ids=overlap_ids,
        fetch_prices=not args.no_fetch,
    ))
