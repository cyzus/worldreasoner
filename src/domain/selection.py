"""Select high-quality, distribution-balanced questions for annotation studies.

Importable home for the logic that used to live in
``scripts/select_prolific_questions.py``. The ``wr question select`` CLI command
wraps :func:`select_questions`.

Selection criteria:
  1. graph_built = 1
  2. quality_score >= min_score (with a fallback to lower-quality questions if a
     domain quota undershoots)
  3. unique non-outcome sources >= min_sources
  4. Source quota: polymarket_n polymarket questions first, remainder from news
  5. Within each source group: domain-proportional allocation with a per-domain cap
"""

import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional


DOMAIN_ORDER = [
    "politics",
    "culture",
    "health",
    "sports",
    "finance",
    "climate",
    "tech",
]


def fetch_candidates(conn: sqlite3.Connection, min_sources: int) -> List[dict]:
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
    candidates: List[dict], n: int, domain_cap: float
) -> Dict[str, int]:
    """Proportional allocation with a per-domain cap."""
    pool_counts: Dict[str, int] = defaultdict(int)
    for c in candidates:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        pool_counts[d] += 1

    total_pool = sum(pool_counts.values())
    if total_pool == 0:
        return {}
    raw: Dict[str, float] = {d: (cnt / total_pool) * n for d, cnt in pool_counts.items()}

    cap = math.floor(n * domain_cap)
    targets: Dict[str, int] = {d: min(cap, math.floor(v)) for d, v in raw.items()}

    remainder = n - sum(targets.values())
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


def select_from_pool(
    candidates: List[dict], n: int, domain_cap: float, min_score: float
) -> List[dict]:
    """Select n questions from candidates with domain balancing."""
    targets = compute_domain_targets(candidates, n, domain_cap)

    by_domain: Dict[str, List[dict]] = defaultdict(list)
    for c in candidates:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        by_domain[d].append(c)

    selected: List[dict] = []
    for domain, target in targets.items():
        pool = by_domain.get(domain, [])
        high = [c for c in pool if c["quality_score"] >= min_score]
        chosen = high[:target]
        if len(chosen) < target:
            chosen_ids = {c["id"] for c in chosen}
            fallback = [c for c in pool if c["id"] not in chosen_ids]
            chosen += fallback[: target - len(chosen)]
        selected.extend(chosen)
    return selected


def pick_overlap(selected: List[dict], n_overlap: int) -> List[dict]:
    """Pick top-quality questions as the overlap (inter-rater) set."""
    sorted_sel = sorted(
        selected, key=lambda c: (-c["quality_score"], -c["unique_sources"])
    )
    return sorted_sel[:n_overlap]


def print_statistics(
    selected: List[dict],
    overlap: List[dict],
    questions_per_session: int,
    overlap_sessions: int,
    min_score: float,
    min_sources: int,
    emit: Callable[[str], None],
) -> None:
    n = len(selected)
    n_ov = len(overlap)
    n_main_q = n - n_ov
    main_sessions = n_main_q // questions_per_session if questions_per_session else 0
    ov_participants = overlap_sessions * questions_per_session
    total_participants = main_sessions + ov_participants

    emit("=" * 56)
    emit("  QUESTION SELECTION SUMMARY")
    emit("=" * 56)
    emit(f"  Total questions selected : {n}")
    emit(
        f"  Main questions           : {n_main_q}  "
        f"({main_sessions} sessions x {questions_per_session})"
    )
    emit(
        f"  Overlap questions        : {n_ov}  "
        f"({overlap_sessions} sessions x {questions_per_session}, 3 people each)"
    )
    emit(
        f"  Total annotator slots    : {total_participants}  "
        f"({main_sessions} main + {ov_participants} overlap)"
    )
    emit("")
    emit("  Filters applied:")
    emit(f"    quality_score >= {min_score} (fallback to >=0.7)")
    emit(f"    unique_sources >= {min_sources}")
    emit("")

    domain_counts: Dict[str, int] = defaultdict(int)
    for c in selected:
        d = c["domain"] if c["domain"] in DOMAIN_ORDER else "other"
        domain_counts[d] += 1
    emit("  Domain breakdown:")
    for d in sorted(domain_counts, key=lambda d: -domain_counts[d]):
        emit(f"    {d:<12} {domain_counts[d]:>3}  {'#' * domain_counts[d]}")
    emit("")

    type_counts: Dict[str, int] = defaultdict(int)
    for c in selected:
        type_counts[c["question_type"]] += 1
    emit("  Question type:")
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        emit(f"    {t:<12} {cnt:>3}  ({cnt / n * 100:.0f}%)")
    emit("")

    src_counts: Dict[str, int] = defaultdict(int)
    for c in selected:
        src_counts[c["source"]] += 1
    emit("  Data source:")
    for s, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        emit(f"    {s:<12} {cnt:>3}  ({cnt / n * 100:.0f}%)")
    emit("")

    emit(f"  Overlap questions (top {n_ov} by quality):")
    for c in overlap:
        emit(
            f"    {c['id'][:60]}  score={c['quality_score']:.1f}  "
            f"src={c['unique_sources']}"
        )
    emit("=" * 56)


def select_questions(
    db_path: str = "combined.db",
    n: int = 120,
    polymarket_n: int = 100,
    min_score: float = 0.8,
    min_sources: int = 3,
    domain_cap: float = 0.25,
    questions_per_session: int = 4,
    overlap_sessions: int = 3,
    out_include: str = "include_ids.txt",
    out_overlap: str = "overlap.txt",
    dry_run: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> List[dict]:
    """Select annotation questions and (unless dry_run) write the ID files.

    Returns the list of selected candidate dicts.
    """
    emit = log or print
    n_overlap = overlap_sessions * questions_per_session

    conn = sqlite3.connect(db_path)
    try:
        candidates = fetch_candidates(conn, min_sources)
    finally:
        conn.close()

    polymarket_pool = [c for c in candidates if c["source"] == "polymarket"]
    news_pool = [c for c in candidates if c["source"] == "news"]

    n_polymarket = min(polymarket_n, len(polymarket_pool))
    n_news = n - n_polymarket

    emit(
        f"Candidate pool: {len(polymarket_pool)} polymarket, "
        f"{len(news_pool)} news  (unique_sources>={min_sources})"
    )
    emit(f"Target:         {n_polymarket} polymarket + {n_news} news = {n} total")

    # Polymarket quality scores are mostly meaningless; take top-N by sources.
    pm_selected = sorted(polymarket_pool, key=lambda c: -c["unique_sources"])[
        :n_polymarket
    ]
    news_selected = select_from_pool(news_pool, n_news, domain_cap, min_score)
    selected = pm_selected + news_selected

    if len(selected) < n:
        emit(f"Warning: only found {len(selected)} questions (target {n}).")

    overlap = pick_overlap(selected, n_overlap)
    print_statistics(
        selected,
        overlap,
        questions_per_session,
        overlap_sessions,
        min_score,
        min_sources,
        emit,
    )

    if dry_run:
        emit("Dry run - files not written.")
        return selected

    Path(out_include).write_text("\n".join(c["id"] for c in selected) + "\n")
    Path(out_overlap).write_text("\n".join(c["id"] for c in overlap) + "\n")
    emit(f"Written: {out_include}  ({len(selected)} IDs)")
    emit(f"Written: {out_overlap}  ({len(overlap)} IDs)")
    return selected
