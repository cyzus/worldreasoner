"""Evaluate forecast reasoning graphs against hindsight graphs.

This is the deterministic "second-layer" evaluator. It does not score final
answers; it scores whether a forecast's supporting events, dates, sources, and
causal edges align with the post-resolution hindsight graph.

The script intentionally uses lexical matching by default so it can run without
embedding/API calls. It is meant to be a stable first pass; embedding-based
matching can be layered on later.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.evaluation.metrics import (
    calculate_accuracy,
    calculate_brier_score,
    calculate_log_score,
)


DEFAULT_DB = "combined.db"
DEFAULT_OUTPUT_DIR = Path("experiments/evaluation")

POSITIVE_RELATIONS = {"causes", "enables", "triggers", "amplifies", "positive"}
NEGATIVE_RELATIONS = {"prevents", "inhibits", "negative"}


@dataclass(frozen=True)
class EventNode:
    id: str
    question_id: str
    title: str
    description: str
    occurred_date: dt.datetime | None
    article_ids: tuple[str, ...]
    is_outcome: bool = False


@dataclass(frozen=True)
class Edge:
    source_id: str
    target_id: str
    relation: str
    confidence: float | None = None
    strength: float | None = None


@dataclass(frozen=True)
class ForecastRecord:
    id: str
    question_id: str
    condition: str
    model: str
    timestamp: str
    prediction: Any
    confidence: float
    is_correct: bool | None
    brier_score: float | None
    log_score: float | None
    articles_accessed: tuple[str, ...]


def load_json(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def parse_date(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str):
        return None
    value = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def norm_tokens(text: str) -> set[str]:
    text = text.lower()
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", text)
        if len(tok) > 2 and tok not in {"the", "and", "for", "with", "that", "this"}
    }


def token_f1(a: str, b: str) -> float:
    ta = norm_tokens(a)
    tb = norm_tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    if overlap == 0:
        return 0.0
    precision = overlap / len(tb)
    recall = overlap / len(ta)
    return 2 * precision * recall / (precision + recall)


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Small in-memory BM25 scorer for per-question event matching."""
    query_terms = norm_tokens(query)
    if not query_terms or not docs:
        return [0.0 for _ in docs]

    doc_terms = [list(norm_tokens(doc)) for doc in docs]
    doc_lens = [len(terms) for terms in doc_terms]
    avgdl = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
    if avgdl == 0:
        return [0.0 for _ in docs]

    df: Counter[str] = Counter()
    for terms in doc_terms:
        for term in set(terms):
            df[term] += 1

    n_docs = len(docs)
    scores: list[float] = []
    for terms, dl in zip(doc_terms, doc_lens):
        tf = Counter(terms)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * dl / avgdl)
            score += idf * (tf[term] * (k1 + 1)) / denom
        scores.append(score)
    return scores


def normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    if max_score <= 0:
        return [0.0 for _ in scores]
    return [score / max_score for score in scores]


def event_text(e: EventNode) -> str:
    return f"{e.title}. {e.description}"


def relation_polarity(relation: str | None) -> str | None:
    if relation is None:
        return None
    relation = relation.lower()
    if relation in POSITIVE_RELATIONS:
        return "positive"
    if relation in NEGATIVE_RELATIONS:
        return "negative"
    return None


def date_error_days(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 86400.0


def read_ids(path: str | None) -> set[str] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}


def latest_forecasts(conn: sqlite3.Connection, include_ids: set[str] | None) -> list[ForecastRecord]:
    rows = conn.execute(
        """
        select f.id, f.question_id, f.model_name, f.timestamp, f.prediction,
               f.confidence, f.is_correct, f.brier_score, f.log_score,
               f.articles_accessed, f.evaluation_metadata,
               q.ground_truth, q.question_type, q.options
        from forecasts f
        join questions q on q.id=f.question_id
        where f.evaluation_metadata is not null
        """
    ).fetchall()
    latest: dict[tuple[str, str, str], ForecastRecord] = {}
    latest_ts: dict[tuple[str, str, str], str] = {}
    for row in rows:
        qid = row["question_id"]
        if include_ids is not None and qid not in include_ids:
            continue
        meta = load_json(row["evaluation_metadata"], {}) or {}
        condition = meta.get("benchmark_condition")
        model = meta.get("benchmark_model") or row["model_name"] or "unknown"
        if not condition:
            continue
        ts = row["timestamp"] or ""
        key = (qid, condition, model)
        if key in latest and ts <= latest_ts[key]:
            continue
        options = load_json(row["options"], []) or []
        accuracy = calculate_accuracy(
            row["prediction"],
            row["ground_truth"],
            row["question_type"],
            question_text="",
            options=options,
        )
        brier_score = calculate_brier_score(
            row["prediction"],
            row["ground_truth"],
            row["confidence"],
            row["question_type"],
            options=options,
        )
        log_score = calculate_log_score(
            row["prediction"],
            row["ground_truth"],
            row["confidence"],
            row["question_type"],
            options=options,
        )
        latest[key] = ForecastRecord(
            id=row["id"],
            question_id=qid,
            condition=condition,
            model=model,
            timestamp=ts,
            prediction=load_json(row["prediction"], row["prediction"]),
            confidence=row["confidence"],
            is_correct=accuracy == 1.0,
            brier_score=brier_score,
            log_score=log_score,
            articles_accessed=tuple(load_json(row["articles_accessed"], []) or []),
        )
        latest_ts[key] = ts
    return list(latest.values())


def load_hindsight_events(conn: sqlite3.Connection, include_ids: set[str] | None) -> dict[str, list[EventNode]]:
    rows = conn.execute(
        """
        select id, title, description, occurred_date, article_ids,
               extracted_for_question_id, is_outcome
        from events
        where extracted_for_question_id is not null
        """
    ).fetchall()
    by_qid: dict[str, list[EventNode]] = defaultdict(list)
    for row in rows:
        qid = row["extracted_for_question_id"]
        if include_ids is not None and qid not in include_ids:
            continue
        by_qid[qid].append(
            EventNode(
                id=row["id"],
                question_id=qid,
                title=row["title"] or "",
                description=row["description"] or "",
                occurred_date=parse_date(row["occurred_date"]),
                article_ids=tuple(load_json(row["article_ids"], []) or []),
                is_outcome=bool(row["is_outcome"]),
            )
        )
    return by_qid


def load_forecast_events(conn: sqlite3.Connection) -> dict[str, list[EventNode]]:
    rows = conn.execute(
        """
        select id, forecast_id, title, description, occurred_date, source_article_ids
        from forecast_events
        where forecast_id is not null
        """
    ).fetchall()
    by_forecast: dict[str, list[EventNode]] = defaultdict(list)
    for row in rows:
        by_forecast[row["forecast_id"]].append(
            EventNode(
                id=row["id"],
                question_id="",
                title=row["title"] or "",
                description=row["description"] or "",
                occurred_date=parse_date(row["occurred_date"]),
                article_ids=tuple(load_json(row["source_article_ids"], []) or []),
                is_outcome=False,
            )
        )
    return by_forecast


def load_hindsight_edges(
    conn: sqlite3.Connection,
    events_by_qid: dict[str, list[EventNode]],
) -> dict[str, list[Edge]]:
    event_to_qid = {
        e.id: qid
        for qid, events in events_by_qid.items()
        for e in events
    }
    by_qid: dict[str, list[Edge]] = defaultdict(list)

    for row in conn.execute(
        "select source_event_id, target_event_id, relation_type, confidence, strength from causal_hypotheses"
    ):
        qid = event_to_qid.get(row["source_event_id"]) or event_to_qid.get(row["target_event_id"])
        if not qid:
            continue
        by_qid[qid].append(
            Edge(
                source_id=row["source_event_id"],
                target_id=row["target_event_id"],
                relation=row["relation_type"] or "correlates",
                confidence=row["confidence"],
                strength=row["strength"],
            )
        )

    for row in conn.execute(
        "select event_id, outcome_event_id, impact_direction, confidence, impact_magnitude from event_outcome_impacts"
    ):
        qid = event_to_qid.get(row["event_id"]) or event_to_qid.get(row["outcome_event_id"])
        if not qid:
            continue
        by_qid[qid].append(
            Edge(
                source_id=row["event_id"],
                target_id=row["outcome_event_id"],
                relation=row["impact_direction"] or "neutral",
                confidence=row["confidence"],
                strength=row["impact_magnitude"],
            )
        )

    return by_qid


def load_forecast_edges(conn: sqlite3.Connection) -> dict[str, list[Edge]]:
    rows = conn.execute(
        """
        select forecast_id, source_event_id, target_event_id, relation_type,
               confidence, strength
        from forecast_hypotheses
        where forecast_id is not null
        """
    ).fetchall()
    by_forecast: dict[str, list[Edge]] = defaultdict(list)
    for row in rows:
        by_forecast[row["forecast_id"]].append(
            Edge(
                source_id=row["source_event_id"],
                target_id=row["target_event_id"],
                relation=row["relation_type"] or "correlates",
                confidence=row["confidence"],
                strength=row["strength"],
            )
        )
    return by_forecast


def load_question_source_articles(
    conn: sqlite3.Connection,
    include_ids: set[str] | None,
) -> dict[str, set[str]]:
    rows = conn.execute(
        """
        select id, related_article_ids
        from questions
        """
    ).fetchall()
    by_qid: dict[str, set[str]] = {}
    for row in rows:
        qid = row["id"]
        if include_ids is not None and qid not in include_ids:
            continue
        by_qid[qid] = set(load_json(row["related_article_ids"], []) or [])

    # Hindsight/evidence articles are also part of the question-level source target.
    for row in conn.execute(
        "select id, collected_for_question_id from articles where collected_for_question_id is not null"
    ):
        qid = row["collected_for_question_id"]
        if include_ids is not None and qid not in include_ids:
            continue
        by_qid.setdefault(qid, set()).add(row["id"])
    return by_qid


def question_source_metrics(
    forecast_articles: tuple[str, ...],
    target_articles: set[str],
) -> dict[str, Any]:
    forecast_set = set(forecast_articles)
    overlap = forecast_set & target_articles
    exact_source_recall = len(overlap) / len(target_articles) if target_articles else None
    exact_source_precision = len(overlap) / len(forecast_set) if forecast_set else None
    return {
        "forecast_articles_accessed": len(forecast_set),
        "hindsight_source_articles": len(target_articles),
        "exact_source_overlap_count": len(overlap),
        # Strict coverage diagnostic only: the hindsight corpus is intentionally
        # much larger than the small source set an agent needs to consult.
        "exact_source_recall": exact_source_recall,
        # Main source-quality metric: among the sources the agent chose to use,
        # how many exactly match question/hindsight provenance?
        "exact_source_precision": exact_source_precision,
    }


def greedy_event_matches(
    hindsight: list[EventNode],
    forecast: list[EventNode],
    threshold: float,
    method: str = "hybrid",
    top_k: int = 5,
) -> list[tuple[int, int, float]]:
    pairs: list[tuple[float, int, int]] = []
    h_texts = [event_text(event) for event in hindsight]
    f_texts = [event_text(event) for event in forecast]
    h_to_f_bm25 = [normalize_scores(bm25_scores(h_text, f_texts)) for h_text in h_texts]
    f_to_h_bm25 = [normalize_scores(bm25_scores(f_text, h_texts)) for f_text in f_texts]
    for hi, he in enumerate(hindsight):
        if he.is_outcome:
            continue
        candidate_indices: set[int] | None = None
        if method in {"bm25", "hybrid"} and forecast:
            scores = h_to_f_bm25[hi]
            ranked = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)
            candidate_indices = {idx for idx in ranked[:top_k] if scores[idx] > 0}
            if not candidate_indices:
                candidate_indices = set(ranked[:top_k])
        for fi, fe in enumerate(forecast):
            if candidate_indices is not None and fi not in candidate_indices:
                continue
            if method == "bm25":
                score = f_to_h_bm25[fi][hi]
            elif method == "hybrid":
                bm25_reverse = f_to_h_bm25[fi][hi]
                lexical = token_f1(event_text(he), event_text(fe))
                score = (0.6 * bm25_reverse) + (0.4 * lexical)
            else:
                score = token_f1(event_text(he), event_text(fe))
            if score >= threshold:
                pairs.append((score, hi, fi))
    pairs.sort(reverse=True)
    matched_h: set[int] = set()
    matched_f: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for score, hi, fi in pairs:
        if hi in matched_h or fi in matched_f:
            continue
        matched_h.add(hi)
        matched_f.add(fi)
        matches.append((hi, fi, score))
    return matches


def max_depth(edges: list[Edge], node_ids: set[str]) -> int:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.source_id in node_ids and edge.target_id in node_ids:
            outgoing[edge.source_id].append(edge.target_id)

    def dfs(node: str, seen: set[str]) -> int:
        if node in seen:
            return 0
        children = outgoing.get(node, [])
        if not children:
            return 0
        return 1 + max(dfs(child, seen | {node}) for child in children)

    return max((dfs(node, set()) for node in node_ids), default=0)


def edge_metrics(
    hindsight_edges: list[Edge],
    forecast_edges: list[Edge],
    hindsight_events: list[EventNode],
    forecast_events: list[EventNode],
    matches: list[tuple[int, int, float]],
) -> dict[str, Any]:
    h_to_f = {hindsight_events[hi].id: forecast_events[fi].id for hi, fi, _ in matches}
    f_to_h = {forecast_events[fi].id: hindsight_events[hi].id for hi, fi, _ in matches}
    h_edge_map: dict[tuple[str, str], Edge] = {
        (edge.source_id, edge.target_id): edge for edge in hindsight_edges
    }

    aligned_forecast_edges = 0
    direction_checks: list[bool] = []
    for edge in forecast_edges:
        h_src = f_to_h.get(edge.source_id)
        h_tgt = f_to_h.get(edge.target_id)
        if not h_src or not h_tgt:
            continue
        h_edge = h_edge_map.get((h_src, h_tgt))
        if not h_edge:
            continue
        aligned_forecast_edges += 1
        h_pol = relation_polarity(h_edge.relation)
        f_pol = relation_polarity(edge.relation)
        if h_pol is not None and f_pol is not None:
            direction_checks.append(h_pol == f_pol)

    forecast_edge_count = len(forecast_edges)
    hindsight_edge_count = len(hindsight_edges)
    edge_precision = aligned_forecast_edges / forecast_edge_count if forecast_edge_count else None
    edge_recall = aligned_forecast_edges / hindsight_edge_count if hindsight_edge_count else None
    direction_accuracy = mean(direction_checks) if direction_checks else None

    return {
        "forecast_edges": forecast_edge_count,
        "hindsight_edges": hindsight_edge_count,
        "aligned_edges": aligned_forecast_edges,
        "edge_precision": edge_precision,
        "edge_recall": edge_recall,
        "direction_accuracy": direction_accuracy,
        "direction_checks": len(direction_checks),
    }


def score_forecast(
    forecast: ForecastRecord,
    hindsight_events_all: list[EventNode],
    forecast_events: list[EventNode],
    hindsight_edges: list[Edge],
    forecast_edges: list[Edge],
    question_source_articles: set[str],
    threshold: float,
    match_method: str,
    top_k: int,
) -> dict[str, Any]:
    hindsight_events = [event for event in hindsight_events_all if not event.is_outcome]
    matches = greedy_event_matches(
        hindsight_events_all,
        forecast_events,
        threshold,
        method=match_method,
        top_k=top_k,
    )
    matched_h = {hi for hi, _, _ in matches}
    matched_f = {fi for _, fi, _ in matches}

    event_recall = len(matched_h) / len(hindsight_events) if hindsight_events else None
    event_precision = len(matched_f) / len(forecast_events) if forecast_events else None
    if event_recall is not None and event_precision is not None and event_recall + event_precision:
        event_f1 = 2 * event_recall * event_precision / (event_recall + event_precision)
    else:
        event_f1 = None

    date_errors = [
        date_error_days(hindsight_events_all[hi].occurred_date, forecast_events[fi].occurred_date)
        for hi, fi, _ in matches
    ]
    date_errors = [value for value in date_errors if value is not None]

    source_hits = []
    for hi, fi, _ in matches:
        h_sources = set(hindsight_events_all[hi].article_ids)
        f_sources = set(forecast_events[fi].article_ids)
        if h_sources or f_sources:
            source_hits.append(bool(h_sources & f_sources))

    edges = edge_metrics(
        hindsight_edges=hindsight_edges,
        forecast_edges=forecast_edges,
        hindsight_events=hindsight_events_all,
        forecast_events=forecast_events,
        matches=matches,
    )

    forecast_node_ids = {event.id for event in forecast_events}
    matched_pairs = [
        {
            "hindsight_event_id": hindsight_events_all[hi].id,
            "forecast_event_id": forecast_events[fi].id,
            "similarity": round(sim, 4),
        }
        for hi, fi, sim in matches
    ]

    return {
        "forecast_id": forecast.id,
        "question_id": forecast.question_id,
        "condition": forecast.condition,
        "model": forecast.model,
        "is_correct": forecast.is_correct,
        "brier_score": forecast.brier_score,
        "log_score": forecast.log_score,
        "hindsight_events": len(hindsight_events),
        "forecast_events": len(forecast_events),
        "matched_events": len(matches),
        "event_recall": event_recall,
        "event_precision": event_precision,
        "event_f1": event_f1,
        "mean_match_similarity": mean([m[2] for m in matches]) if matches else None,
        "temporal_mae_days": mean(date_errors) if date_errors else None,
        "event_pair_source_overlap_rate": mean(source_hits) if source_hits else None,
        "forecast_max_depth": max_depth(forecast_edges, forecast_node_ids),
        "has_forecast_graph": bool(forecast_events and forecast_edges),
        "matched_pairs": matched_pairs,
        **question_source_metrics(forecast.articles_accessed, question_source_articles),
        **edges,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def avg(key: str) -> float | None:
        vals = [row[key] for row in rows if row.get(key) is not None]
        return mean(vals) if vals else None

    return {
        "n": len(rows),
        "n_with_graph": sum(1 for row in rows if row["has_forecast_graph"]),
        "accuracy": avg("is_correct"),
        "brier_score": avg("brier_score"),
        "log_score": avg("log_score"),
        "event_recall": avg("event_recall"),
        "event_precision": avg("event_precision"),
        "event_f1": avg("event_f1"),
        "mean_match_similarity": avg("mean_match_similarity"),
        "temporal_mae_days": avg("temporal_mae_days"),
        "exact_source_recall": avg("exact_source_recall"),
        "exact_source_precision": avg("exact_source_precision"),
        "event_pair_source_overlap_rate": avg("event_pair_source_overlap_rate"),
        "edge_recall": avg("edge_recall"),
        "edge_precision": avg("edge_precision"),
        "direction_accuracy": avg("direction_accuracy"),
        "forecast_max_depth": avg("forecast_max_depth"),
    }


def write_tsv(rows: list[dict[str, Any]], path: Path) -> None:
    columns = [
        "question_id",
        "condition",
        "model",
        "forecast_id",
        "is_correct",
        "brier_score",
        "log_score",
        "hindsight_events",
        "forecast_events",
        "matched_events",
        "event_recall",
        "event_precision",
        "event_f1",
        "mean_match_similarity",
        "temporal_mae_days",
        "forecast_articles_accessed",
        "hindsight_source_articles",
        "exact_source_overlap_count",
        "exact_source_recall",
        "exact_source_precision",
        "event_pair_source_overlap_rate",
        "hindsight_edges",
        "forecast_edges",
        "aligned_edges",
        "edge_recall",
        "edge_precision",
        "direction_accuracy",
        "forecast_max_depth",
        "has_forecast_graph",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    def pct(value: float | None) -> str:
        return f"{value:.1%}" if value is not None else "--"

    def num(value: float | None) -> str:
        return f"{value:.3f}" if value is not None else "--"

    lines = [
        "# Forecast Reasoning Graph Evaluation",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    overall = summary["overall"]
    for key in [
        "n",
        "n_with_graph",
        "accuracy",
        "event_recall",
        "event_precision",
        "event_f1",
        "edge_recall",
        "edge_precision",
        "direction_accuracy",
        "temporal_mae_days",
        "exact_source_precision",
        "forecast_max_depth",
    ]:
        value = overall.get(key)
        rendered = pct(value) if key not in {"n", "n_with_graph", "temporal_mae_days", "forecast_max_depth"} else num(value)
        if key in {"n", "n_with_graph"}:
            rendered = str(value)
        lines.append(f"| {key} | {rendered} |")

    lines += [
        "",
        "Exact source recall is omitted from the main table because it is a strict coverage diagnostic over the full hindsight evidence corpus. Source quality is reported primarily as precision: among the sources the agent chose to access, how many exactly match question/hindsight provenance.",
        "",
        "",
        "## By Condition and Model",
        "",
        "| Condition | Model | n | Event F1 | Event Recall | Event Precision | Exact Source Precision | Accuracy |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, stats in sorted(summary["by_condition_model"].items()):
        condition = stats["condition"]
        short_model = stats["model"].split("/")[-1]
        lines.append(
            f"| {condition} | {short_model} | {stats['n']} | "
            f"{pct(stats['event_f1'])} | {pct(stats['event_recall'])} | "
            f"{pct(stats['event_precision'])} | {pct(stats['exact_source_precision'])} | "
            f"{pct(stats['accuracy'])} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--include-ids", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--match-threshold", type=float, default=0.45)
    parser.add_argument(
        "--match-method",
        choices=["lexical", "bm25", "hybrid"],
        default="hybrid",
        help="Event matching method. Hybrid uses BM25 candidates plus lexical overlap.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="BM25 candidate count per hindsight event")
    parser.add_argument("--condition", nargs="*", default=None)
    args = parser.parse_args()

    include_ids = read_ids(args.include_ids)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        forecasts = latest_forecasts(conn, include_ids)
        if args.condition:
            allowed = set(args.condition)
            forecasts = [f for f in forecasts if f.condition in allowed]

        hindsight_events = load_hindsight_events(conn, include_ids)
        forecast_events = load_forecast_events(conn)
        hindsight_edges = load_hindsight_edges(conn, hindsight_events)
        forecast_edges = load_forecast_edges(conn)
        question_source_articles = load_question_source_articles(conn, include_ids)
    finally:
        conn.close()

    rows: list[dict[str, Any]] = []
    for forecast in forecasts:
        row = score_forecast(
            forecast=forecast,
            hindsight_events_all=hindsight_events.get(forecast.question_id, []),
            forecast_events=forecast_events.get(forecast.id, []),
            hindsight_edges=hindsight_edges.get(forecast.question_id, []),
            forecast_edges=forecast_edges.get(forecast.id, []),
            question_source_articles=question_source_articles.get(forecast.question_id, set()),
            threshold=args.match_threshold,
            match_method=args.match_method,
            top_k=args.top_k,
        )
        rows.append(row)

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = f"reasoning_graph_eval_{timestamp}"

    summary: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "db": args.db,
        "include_ids": args.include_ids,
        "match_threshold": args.match_threshold,
        "match_method": args.match_method,
        "top_k": args.top_k,
        "overall": aggregate(rows),
        "by_condition_model": {},
    }
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["condition"], row["model"])].append(row)
    summary["by_condition_model"] = {
        f"{condition}::{model}": {
            "condition": condition,
            "model": model,
            **aggregate(value),
        }
        for (condition, model), value in grouped.items()
    }

    json_path = output_dir / f"{stem}.json"
    json_path.write_text(json.dumps(summary | {"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    write_tsv(rows, output_dir / f"{stem}.tsv")
    write_markdown(summary, output_dir / f"{stem}.md")

    print(f"rows={len(rows)}")
    print(f"wrote={json_path}")
    print(f"overall_event_f1={summary['overall']['event_f1']}")
    print(f"overall_edge_recall={summary['overall']['edge_recall']}")


if __name__ == "__main__":
    main()
