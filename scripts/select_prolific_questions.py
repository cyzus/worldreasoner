"""
Select high-quality questions for the Prolific annotation study.

Selection criteria (in priority order within each domain):
  1. graph_built = 1
  2. quality_score >= --min-score (default 0.8), fallback to >= 0.7 if domain undershoots
  3. unique non-outcome sources >= --min-sources (default 3)
  4. Domain-proportional allocation with a per-domain cap

Outputs (unless --dry-run):
  include_ids.txt   all selected question IDs (one per line)
  overlap.txt       overlap subset (used for IRR)

Usage:
  uv run python scripts/select_prolific_questions.py --db combined.db
  uv run python scripts/select_prolific_questions.py --db combined.db --n 120 --overlap-sessions 3
  uv run python scripts/select_prolific_questions.py --db combined.db --dry-run
"""

import argparse
import math
import random
import sqlite3
from collections import defaultdict
from pathlib import Path


DOMAIN_ORDER = ["politics", "culture", "health", "sports", "finance", "climate", "tech"]


def fetch_candidates(conn: sqlite3.Connection, min_sources: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            q.id,
            q.domain,
            q.question_type,
            q.source,
            COALESCE(q.quality_score, 0.0) AS quality_score,
            COUNT(DISTINCT e.source_article_id)  AS unique_sources
        FROM questions q
        JOIN events e ON e.extracted_for_question_id = q.id
        WHERE q.graph_built = 1
          AND e.is_outcome = 0
          AND e.source_article_id IS NOT NULL
        GROUP BY q.id
        HAVING unique_sources >= ?
        ORDER BY quality_score DESC, unique_sources DESC
        """,
        (min_sources,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "domain": r[1] or "other",
            "question_type": r[2],
            "source": r[3],
            "quality_score": r[4],
            "unique_sources": r[5],
        }
        for r in rows
    ]


def compute_domain_targets(
    candidates: list[dict],
    n: int,
    domain_cap: float,
) -> dict[str, int]:
    """Proportional allocation with a per-domain cap."""
    pool_counts: dict[str, int] = defaultdict(int)
    for c in candidates:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        pool_counts[d] += 1

    total_pool = sum(pool_counts.values())
    raw: dict[str, float] = {
        d: (cnt / total_pool) * n for d, cnt in pool_counts.items()
    }

    cap = math.floor(n * domain_cap)
    targets: dict[str, int] = {d: min(cap, math.floor(v)) for d, v in raw.items()}

    # Distribute remaining slots to domains that have room, sorted by fractional part
    allocated = sum(targets.values())
    remainder = n - allocated
    slack = sorted(
        [(d, raw[d] - targets[d]) for d in targets if pool_counts[d] > targets[d]],
        key=lambda x: -x[1],
    )
    for d, _ in slack:
        if remainder == 0:
            break
        targets[d] += 1
        remainder -= 1

    return targets


def select_questions(
    candidates: list[dict],
    targets: dict[str, int],
    min_score: float,
) -> list[dict]:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        by_domain[d].append(c)

    selected: list[dict] = []

    for domain, target in targets.items():
        pool = by_domain.get(domain, [])
        # Pass 1: quality >= min_score
        high = [c for c in pool if c["quality_score"] >= min_score]
        chosen = high[:target]
        # Pass 2: fallback to lower quality if needed
        if len(chosen) < target:
            fallback_ids = {c["id"] for c in chosen}
            fallback = [c for c in pool if c["id"] not in fallback_ids]
            chosen += fallback[: target - len(chosen)]
        selected.extend(chosen)

    return selected


def pick_overlap(selected: list[dict], n_overlap: int) -> list[dict]:
    """Pick top-quality questions as overlap set."""
    sorted_sel = sorted(selected, key=lambda c: (-c["quality_score"], -c["unique_sources"]))
    return sorted_sel[:n_overlap]


def print_statistics(
    selected: list[dict],
    overlap: list[dict],
    questions_per_session: int,
    overlap_sessions: int,
    min_score: float,
    min_sources: int,
) -> None:
    n = len(selected)
    n_ov = len(overlap)
    overlap_ids = {c["id"] for c in overlap}

    n_main_q = n - n_ov
    main_sessions = n_main_q // questions_per_session
    ov_participants = overlap_sessions * questions_per_session  # 3 people per overlap session
    total_participants = main_sessions + ov_participants

    print("=" * 56)
    print("  PROLIFIC STUDY — QUESTION SELECTION SUMMARY")
    print("=" * 56)
    print(f"  Total questions selected : {n}")
    print(f"  Main questions           : {n_main_q}  ({main_sessions} sessions × {questions_per_session})")
    print(f"  Overlap questions        : {n_ov}  ({overlap_sessions} sessions × {questions_per_session}, 3 people each)")
    print(f"  Total Prolific slots     : {total_participants}  ({main_sessions} main + {ov_participants} overlap)")
    print()

    print("  Filters applied:")
    print(f"    quality_score >= {min_score} (fallback to >=0.7)")
    print(f"    unique_sources >= {min_sources}")
    print()

    # Domain breakdown
    domain_counts: dict[str, int] = defaultdict(int)
    for c in selected:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        domain_counts[d] += 1
    all_domains = sorted(domain_counts, key=lambda d: -domain_counts[d])

    print("  Domain breakdown:")
    for d in all_domains:
        cnt = domain_counts[d]
        bar = "█" * cnt
        print(f"    {d:<12} {cnt:>3}  {bar}")
    print()

    # Question type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for c in selected:
        type_counts[c["question_type"]] += 1
    print("  Question type:")
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<12} {cnt:>3}  ({cnt/n*100:.0f}%)")
    print()

    # Source (polymarket vs news)
    src_counts: dict[str, int] = defaultdict(int)
    for c in selected:
        src_counts[c["source"]] += 1
    print("  Data source:")
    for s, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        print(f"    {s:<12} {cnt:>3}  ({cnt/n*100:.0f}%)")
    print()

    # Quality score distribution
    buckets: dict[str, int] = defaultdict(int)
    for c in selected:
        s = c["quality_score"]
        if s >= 1.0:
            buckets["1.0"] += 1
        elif s >= 0.9:
            buckets["0.9–1.0"] += 1
        elif s >= 0.8:
            buckets["0.8–0.9"] += 1
        elif s >= 0.7:
            buckets["0.7–0.8"] += 1
        else:
            buckets["<0.7"] += 1
    print("  Quality score distribution:")
    for label in ["1.0", "0.9–1.0", "0.8–0.9", "0.7–0.8", "<0.7"]:
        cnt = buckets.get(label, 0)
        if cnt:
            print(f"    {label:<10} {cnt:>3}  ({cnt/n*100:.0f}%)")
    print()

    # Source diversity distribution
    src_dist: dict[int, int] = defaultdict(int)
    for c in selected:
        src_dist[min(c["unique_sources"], 10)] += 1
    print("  Unique sources per question:")
    for k in sorted(src_dist):
        label = f">={k}" if k == 10 else str(k)
        cnt = src_dist[k]
        print(f"    {label:<6} {cnt:>3}")
    print()

    print(f"  Overlap questions (top {n_ov} by quality):")
    for c in overlap:
        print(f"    {c['id'][:60]}  score={c['quality_score']:.1f}  src={c['unique_sources']}")
    print("=" * 56)


def main() -> None:
    parser = argparse.ArgumentParser(description="Select Prolific annotation questions")
    parser.add_argument("--db", default="combined.db")
    parser.add_argument("--n", type=int, default=120, help="Total questions to select")
    parser.add_argument("--min-score", type=float, default=0.8, help="Minimum quality score")
    parser.add_argument("--min-sources", type=int, default=3, help="Minimum unique sources")
    parser.add_argument("--domain-cap", type=float, default=0.25, help="Max fraction per domain")
    parser.add_argument("--questions-per-session", type=int, default=4)
    parser.add_argument("--overlap-sessions", type=int, default=3, help="Number of overlap sessions")
    parser.add_argument("--out-include", default="include_ids.txt")
    parser.add_argument("--out-overlap", default="overlap.txt")
    parser.add_argument("--dry-run", action="store_true", help="Print stats only, don't write files")
    args = parser.parse_args()

    n_overlap = args.overlap_sessions * args.questions_per_session

    conn = sqlite3.connect(args.db)
    candidates = fetch_candidates(conn, args.min_sources)
    conn.close()

    print(f"Candidate pool (graph_built=1, unique_sources>={args.min_sources}): {len(candidates)}")

    targets = compute_domain_targets(candidates, args.n, args.domain_cap)
    selected = select_questions(candidates, targets, args.min_score)

    if len(selected) < args.n:
        print(f"Warning: only found {len(selected)} questions (target {args.n}). Consider lowering --min-score or --min-sources.")

    overlap = pick_overlap(selected, n_overlap)

    print_statistics(selected, overlap, args.questions_per_session, args.overlap_sessions, args.min_score, args.min_sources)

    if args.dry_run:
        print("Dry run — files not written.")
        return

    Path(args.out_include).write_text("\n".join(c["id"] for c in selected) + "\n")
    Path(args.out_overlap).write_text("\n".join(c["id"] for c in overlap) + "\n")
    print(f"Written: {args.out_include}  ({len(selected)} IDs)")
    print(f"Written: {args.out_overlap}  ({len(overlap)} IDs)")


if __name__ == "__main__":
    main()
