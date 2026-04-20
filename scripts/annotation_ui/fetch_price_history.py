"""
Pre-fetch Polymarket price history for all annotatable questions and cache to JSON.

Run this once before export_data.py to populate price_cache.json.
The export script reads from the cache so the UI can show in-window price context
without making live API calls.

Usage:
    python scripts/annotation_ui/fetch_price_history.py --db combined.db
    python scripts/annotation_ui/fetch_price_history.py --db combined.db --force
"""

import asyncio
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.database import GenericDatabase
from src.domain.models import Question
from src.integrations.polymarket import get_price_history_for_market
from src.utils.logging import logger

CACHE_FILE = os.path.join(os.path.dirname(__file__), "price_cache.json")


def load_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def summarize_price_history(
    history: List[Dict[str, Any]],
    market_open_ts: Optional[int],
    market_close_ts: Optional[int],
) -> Dict[str, Any]:
    """
    Condense full price history into a compact summary for the UI.

    Returns a dict with:
    - history: downsampled to ~100 points for chart rendering
    - turning_points: significant price changes (>5pp) for event card overlay
    - price_at_open / price_at_close: boundary prices
    - min_price / max_price / final_price
    """
    if not history:
        return {}

    sorted_h = sorted(history, key=lambda x: x["t"])

    # Downsample to at most 120 points for UI rendering
    max_points = 120
    if len(sorted_h) > max_points:
        step = len(sorted_h) / max_points
        downsampled = [sorted_h[int(i * step)] for i in range(max_points)]
    else:
        downsampled = sorted_h

    prices = [p["p"] for p in sorted_h]

    # Price at market open/close boundaries
    price_at_open = None
    price_at_close = None
    if market_open_ts:
        candidates = [p for p in sorted_h if p["t"] >= market_open_ts]
        if candidates:
            price_at_open = round(candidates[0]["p"], 4)
    if market_close_ts:
        candidates = [p for p in sorted_h if p["t"] <= market_close_ts]
        if candidates:
            price_at_close = round(candidates[-1]["p"], 4)

    # Simple turning points: points where price moves >5pp from previous
    turning_points = []
    THRESHOLD = 0.05  # 5 percentage points
    prev_price = sorted_h[0]["p"]
    for point in sorted_h[1:]:
        delta = point["p"] - prev_price
        if abs(delta) >= THRESHOLD:
            turning_points.append({
                "t": point["t"],
                "p": round(point["p"], 4),
                "delta": round(delta, 4),
            })
            prev_price = point["p"]

    return {
        "history": [{"t": p["t"], "p": round(p["p"], 4)} for p in downsampled],
        "turning_points": turning_points,
        "price_at_open": price_at_open,
        "price_at_close": price_at_close,
        "min_price": round(min(prices), 4),
        "max_price": round(max(prices), 4),
        "final_price": round(sorted_h[-1]["p"], 4),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_for_question(
    question: Question,
    cache: Dict[str, Any],
    force: bool = False,
) -> bool:
    """Fetch and cache price history for one question. Returns True if fetched."""
    qid = question.id
    meta = question.metadata or {}
    clob_token_ids = meta.get("clob_token_ids", [])

    if not clob_token_ids:
        return False

    if qid in cache and not force:
        return False  # already cached

    # Determine market window
    market_open_ts = None
    market_close_ts = None

    if question.estimated_start_time:
        dt = question.estimated_start_time
        if hasattr(dt, "timestamp"):
            market_open_ts = int(dt.timestamp())

    if question.resolution_date:
        dt = question.resolution_date
        if hasattr(dt, "timestamp"):
            market_close_ts = int(dt.timestamp())

    try:
        price_data = await get_price_history_for_market(
            clob_token_ids,
            interval="max",
            fidelity=720,
        )
    except Exception as e:
        logger.error(f"Failed to fetch price history for {qid}: {e}")
        return False

    if not price_data:
        logger.warning(f"No price data returned for {qid}")
        return False

    # Use first token (primary Yes outcome)
    first_token_id = clob_token_ids[0]
    primary_history = price_data.get(first_token_id, [])

    if not primary_history:
        return False

    cache[qid] = summarize_price_history(primary_history, market_open_ts, market_close_ts)
    logger.info(f"Cached price history for {qid}: {len(primary_history)} raw points → {len(cache[qid]['history'])} downsampled")
    return True


async def main(db_path: str, force: bool = False) -> None:
    db = GenericDatabase(db_path)
    questions = db.get_many(Question)

    # Only process polymarket questions with clob_token_ids and causal_explanation
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT extracted_for_question_id FROM event_outcome_impacts"
    )
    valid_q_ids = set(r[0] for r in cursor.fetchall())
    conn.close()

    polymarket_qs = [
        q for q in questions
        if q.id in valid_q_ids
        and q.metadata
        and q.metadata.get("clob_token_ids")
    ]

    print(f"Found {len(polymarket_qs)} polymarket questions with CLOB token IDs to process")

    cache = load_cache()
    already_cached = sum(1 for q in polymarket_qs if q.id in cache)
    print(f"Already cached: {already_cached}, to fetch: {len(polymarket_qs) - already_cached}")

    if not force and already_cached == len(polymarket_qs):
        print("All questions already cached. Use --force to re-fetch.")
        return

    fetched = 0
    skipped = 0
    failed = 0

    for i, q in enumerate(polymarket_qs, 1):
        status = "CACHED" if (q.id in cache and not force) else "FETCHING"
        print(f"[{i:3}/{len(polymarket_qs)}] {status} {q.id[:55]}", end="", flush=True)

        if q.id in cache and not force:
            print(" (skip)")
            skipped += 1
            continue

        success = await fetch_for_question(q, cache, force=force)
        if success:
            save_cache(cache)  # save incrementally in case of interruption
            fetched += 1
            print(f" → {len(cache[q.id]['history'])} pts")
        else:
            failed += 1
            print(" → FAILED or no data")

        # Rate limiting: small delay between requests
        await asyncio.sleep(0.3)

    print(f"\nDone. Fetched: {fetched}, Skipped: {skipped}, Failed: {failed}")
    print(f"Cache saved to: {CACHE_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-fetch Polymarket price history for annotation UI")
    parser.add_argument("--db", default="combined.db", help="Path to SQLite DB")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already cached")
    args = parser.parse_args()

    asyncio.run(main(db_path=args.db, force=args.force))
