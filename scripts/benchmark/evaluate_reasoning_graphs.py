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
import shutil
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

from src.core.llm import get_knowledge_cutoff_date
from src.domain.evaluation.metrics import (
    calculate_accuracy,
    calculate_brier_score,
    calculate_log_score,
)
from src.integrations.polymarket import analyze_price_curve


DEFAULT_DB = "combined.db"
DEFAULT_OUTPUT_DIR = Path("experiments/evaluation")
DEFAULT_PRICE_CACHE = Path("scripts/annotation_ui/price_cache.json")

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
    simulated_date: dt.datetime | None
    prediction: Any
    confidence: float
    is_correct: bool | None
    brier_score: float | None
    log_score: float | None
    articles_accessed: tuple[str, ...]
    estimated_start_time: dt.datetime | None


@dataclass(frozen=True)
class QuestionInfo:
    id: str
    source: str
    question_type: str
    options: tuple[str, ...]


@dataclass(frozen=True)
class ImpactScores:
    key_scores: dict[str, float]
    primary_signed_scores: dict[str, float]


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


def events_available_by(
    events: list[EventNode],
    simulated_date: dt.datetime | None,
) -> list[EventNode]:
    """Return reference events that could have occurred by the simulated date."""
    if simulated_date is None:
        return []
    return [
        event for event in events
        if event.occurred_date is not None and event.occurred_date <= simulated_date
    ]


def relation_polarity(relation: str | None) -> str | None:
    if relation is None:
        return None
    relation = relation.lower()
    if relation in POSITIVE_RELATIONS:
        return "positive"
    if relation in NEGATIVE_RELATIONS:
        return "negative"
    return None


def impact_sign(direction: str | None) -> int:
    if direction is None:
        return 0
    direction = direction.lower().replace("impactdirection.", "")
    if direction == "positive":
        return 1
    if direction == "negative":
        return -1
    return 0


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


def load_price_cache(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def latest_forecasts(
    conn: sqlite3.Connection,
    include_ids: set[str] | None,
    include_forecast_ids: set[str] | None = None,
) -> list[ForecastRecord]:
    rows = conn.execute(
        """
        select f.id, f.question_id, f.model_name, f.timestamp, f.prediction,
               f.confidence, f.is_correct, f.brier_score, f.log_score,
               f.articles_accessed, f.evaluation_metadata, f.simulated_date,
               q.ground_truth, q.question_type, q.options, q.estimated_start_time
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
        if include_forecast_ids is not None and row["id"] not in include_forecast_ids:
            continue
        meta = load_json(row["evaluation_metadata"], {}) or {}
        condition = meta.get("benchmark_condition")
        model = meta.get("benchmark_model") or row["model_name"] or "unknown"
        if not condition:
            continue
        ts = row["timestamp"] or ""
        key = (qid, condition, model)
        # When pinned to specific forecast IDs, skip the latest-per-key logic
        if include_forecast_ids is None and key in latest and ts <= latest_ts[key]:
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
            simulated_date=parse_date(row["simulated_date"]),
            prediction=load_json(row["prediction"], row["prediction"]),
            confidence=row["confidence"],
            is_correct=accuracy == 1.0,
            brier_score=brier_score,
            log_score=log_score,
            articles_accessed=tuple(load_json(row["articles_accessed"], []) or []),
            estimated_start_time=parse_date(row["estimated_start_time"]),
        )
        latest_ts[key] = ts
    return list(latest.values())


def is_knowledge_leakage_pair(forecast: ForecastRecord) -> bool:
    cutoff_str = get_knowledge_cutoff_date(forecast.model)
    if not cutoff_str or cutoff_str == "Unknown" or forecast.estimated_start_time is None:
        return False
    cutoff_dt = parse_date(cutoff_str)
    if cutoff_dt is None:
        return False
    return forecast.estimated_start_time < cutoff_dt


def load_question_info(conn: sqlite3.Connection, include_ids: set[str] | None) -> dict[str, QuestionInfo]:
    rows = conn.execute(
        "select id, source, question_type, options from questions"
    ).fetchall()
    info: dict[str, QuestionInfo] = {}
    for row in rows:
        qid = row["id"]
        if include_ids is not None and qid not in include_ids:
            continue
        info[qid] = QuestionInfo(
            id=qid,
            source=row["source"] or "",
            question_type=row["question_type"] or "",
            options=tuple(load_json(row["options"], []) or []),
        )
    return info


def load_hindsight_events(
    conn: sqlite3.Connection,
    include_ids: set[str] | None,
    exclude_annotation_rejected: bool = False,
) -> dict[str, list[EventNode]]:
    query = """
        select id, title, description, occurred_date, article_ids,
               extracted_for_question_id, is_outcome
        from events
        where extracted_for_question_id is not null
    """
    if exclude_annotation_rejected:
        query += " AND (review_status IS NULL OR review_status != 'rejected')"
    rows = conn.execute(query).fetchall()
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


def load_primary_outcome_ids(
    conn: sqlite3.Connection,
    question_info: dict[str, QuestionInfo],
) -> dict[str, str]:
    rows = conn.execute(
        """
        select id, extracted_for_question_id, outcome_scenario, outcome_option_index
        from events
        where is_outcome=1 and extracted_for_question_id is not null
        """
    ).fetchall()
    by_qid: dict[str, str] = {}
    fallback: dict[str, str] = {}
    for row in rows:
        qid = row["extracted_for_question_id"]
        if qid not in question_info:
            continue
        fallback.setdefault(qid, row["id"])
        if row["outcome_option_index"] == 0:
            by_qid[qid] = row["id"]
            continue
        scenario = (row["outcome_scenario"] or "").strip().lower()
        options = [opt.strip().lower() for opt in question_info[qid].options]
        if options and scenario == options[0]:
            by_qid.setdefault(qid, row["id"])
        elif scenario in {"yes", "true"}:
            by_qid.setdefault(qid, row["id"])
    return fallback | by_qid


def load_impact_scores(
    conn: sqlite3.Connection,
    primary_outcome_ids: dict[str, str],
    include_ids: set[str] | None,
) -> dict[str, ImpactScores]:
    rows = conn.execute(
        """
        select event_id, outcome_event_id, question_id, impact_direction,
               impact_magnitude, confidence
        from event_outcome_impacts
        """
    ).fetchall()
    key_scores: dict[str, dict[str, float]] = defaultdict(dict)
    primary_scores: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        qid = row["question_id"]
        if include_ids is not None and qid not in include_ids:
            continue
        sign = impact_sign(row["impact_direction"])
        magnitude = float(row["impact_magnitude"] or 0.0)
        confidence = float(row["confidence"] or 0.0)
        score = magnitude * confidence
        event_id = row["event_id"]
        key_scores[qid][event_id] = max(key_scores[qid].get(event_id, 0.0), score)
        if sign and row["outcome_event_id"] == primary_outcome_ids.get(qid):
            signed_score = sign * score
            prev = primary_scores[qid].get(event_id)
            if prev is None or abs(signed_score) > abs(prev):
                primary_scores[qid][event_id] = signed_score

    qids = set(key_scores) | set(primary_scores)
    return {
        qid: ImpactScores(
            key_scores=key_scores.get(qid, {}),
            primary_signed_scores=primary_scores.get(qid, {}),
        )
        for qid in qids
    }


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


def price_delta_around_event(
    price_data: dict[str, Any],
    event_date: dt.datetime | None,
    window_days: float,
) -> float | None:
    if event_date is None:
        return None
    history = price_data.get("history") if price_data else None
    if not history:
        return None
    event_ts = event_date.timestamp()
    window_seconds = window_days * 86400.0
    before = [
        point for point in history
        if 0 <= event_ts - float(point.get("t", 0)) <= window_seconds
    ]
    after = [
        point for point in history
        if 0 <= float(point.get("t", 0)) - event_ts <= window_seconds
    ]
    if not before or not after:
        return None
    before_point = max(before, key=lambda point: float(point.get("t", 0)))
    after_point = min(after, key=lambda point: float(point.get("t", 0)))
    return float(after_point.get("p", 0.0)) - float(before_point.get("p", 0.0))


def market_turning_point_datetimes(
    price_data: dict[str, Any],
    min_change_pct: float,
) -> list[dt.datetime]:
    history = price_data.get("history") if price_data else None
    if not history:
        return []
    analysis = analyze_price_curve(
        history,
        min_turning_point_change=min_change_pct * 100.0,
        min_sharp_movement_change=min_change_pct * 200.0,
    )
    points = []
    for point in analysis.get("turning_points", []):
        timestamp = point.get("timestamp")
        if timestamp is None:
            continue
        points.append(dt.datetime.fromtimestamp(float(timestamp), tz=dt.timezone.utc))
    return points


def is_near_turning_point(
    event_date: dt.datetime | None,
    turning_points: list[dt.datetime],
    window_days: float,
) -> bool:
    if event_date is None or not turning_points:
        return False
    if event_date.tzinfo is None:
        event_date = event_date.replace(tzinfo=dt.timezone.utc)
    window_seconds = window_days * 86400.0
    return any(abs((event_date - point).total_seconds()) <= window_seconds for point in turning_points)


def market_event_metrics(
    hindsight_events: list[EventNode],
    forecast_events: list[EventNode],
    matched_h: set[int],
    impact_scores: ImpactScores | None,
    price_data: dict[str, Any],
    question_info: QuestionInfo | None,
    window_days: float,
    min_price_delta: float,
    turning_points: list[dt.datetime] | None = None,
) -> dict[str, Any]:
    if question_info is None or question_info.source != "polymarket":
        return {
            "market_signal_events": None,
            "market_signal_matched_events": None,
            "market_signal_recall": None,
            "market_signal_precision": None,
            "turning_point_signal_events": None,
            "turning_point_signal_matched_events": None,
            "turning_point_signal_recall": None,
            "turning_point_signal_precision": None,
            "hindsight_market_direction_alignment": None,
            "market_direction_checks": 0,
        }
    if not forecast_events:
        return {
            "market_signal_events": None,
            "market_signal_matched_events": None,
            "market_signal_recall": None,
            "market_signal_precision": None,
            "turning_point_signal_events": None,
            "turning_point_signal_matched_events": None,
            "turning_point_signal_recall": None,
            "turning_point_signal_precision": None,
            "hindsight_market_direction_alignment": None,
            "market_direction_checks": 0,
        }
    if not price_data or not impact_scores:
        return {
            "market_signal_events": 0,
            "market_signal_matched_events": 0,
            "market_signal_recall": None,
            "market_signal_precision": None,
            "turning_point_signal_events": 0,
            "turning_point_signal_matched_events": 0,
            "turning_point_signal_recall": None,
            "turning_point_signal_precision": None,
            "hindsight_market_direction_alignment": None,
            "market_direction_checks": 0,
        }

    signal_indices: set[int] = set()
    turning_signal_indices: set[int] = set()
    direction_checks: list[bool] = []
    turning_points = turning_points or []
    for idx, event in enumerate(hindsight_events):
        if event.is_outcome:
            continue
        signed_impact = impact_scores.primary_signed_scores.get(event.id)
        if signed_impact is None or signed_impact == 0:
            continue
        delta = price_delta_around_event(price_data, event.occurred_date, window_days)
        if delta is None or abs(delta) < min_price_delta:
            continue
        aligned = (signed_impact > 0 and delta > 0) or (signed_impact < 0 and delta < 0)
        direction_checks.append(aligned)
        if aligned:
            signal_indices.add(idx)
            if is_near_turning_point(event.occurred_date, turning_points, window_days):
                turning_signal_indices.add(idx)

    matched_signals = len(signal_indices & matched_h)
    signal_recall = matched_signals / len(signal_indices) if signal_indices else None
    signal_precision = matched_signals / len(forecast_events) if forecast_events else None
    matched_turning_signals = len(turning_signal_indices & matched_h)
    turning_signal_recall = (
        matched_turning_signals / len(turning_signal_indices)
        if turning_signal_indices
        else None
    )
    turning_signal_precision = (
        matched_turning_signals / len(forecast_events)
        if forecast_events
        else None
    )
    return {
        "market_signal_events": len(signal_indices),
        "market_signal_matched_events": matched_signals,
        "market_signal_recall": signal_recall,
        "market_signal_precision": signal_precision,
        "turning_point_signal_events": len(turning_signal_indices),
        "turning_point_signal_matched_events": matched_turning_signals,
        "turning_point_signal_recall": turning_signal_recall,
        "turning_point_signal_precision": turning_signal_precision,
        "hindsight_market_direction_alignment": mean(direction_checks) if direction_checks else None,
        "market_direction_checks": len(direction_checks),
    }


def key_event_metrics(
    hindsight_events: list[EventNode],
    forecast_events: list[EventNode],
    matched_h: set[int],
    matched_f: set[int],
    impact_scores: ImpactScores | None,
    key_event_top_k: int,
    key_event_min_score: float,
) -> dict[str, Any]:
    if not forecast_events:
        return {
            "key_events": None,
            "matched_key_events": None,
            "key_event_recall": None,
            "key_event_precision": None,
        }
    if not impact_scores:
        return {
            "key_events": 0,
            "matched_key_events": 0,
            "key_event_recall": None,
            "key_event_precision": None,
        }

    ranked: list[tuple[float, int]] = []
    for idx, event in enumerate(hindsight_events):
        if event.is_outcome:
            continue
        score = impact_scores.key_scores.get(event.id, 0.0)
        if score >= key_event_min_score:
            ranked.append((score, idx))
    ranked.sort(reverse=True)
    key_indices = {idx for _, idx in ranked[:key_event_top_k]}
    matched_keys = len(key_indices & matched_h)
    key_recall = matched_keys / len(key_indices) if key_indices else None
    key_precision = matched_keys / len(forecast_events) if forecast_events else None
    return {
        "key_events": len(key_indices),
        "matched_key_events": matched_keys,
        "key_event_recall": key_recall,
        "key_event_precision": key_precision,
    }


_semantic_model = None

def _get_semantic_model(model_name: str = "all-MiniLM-L6-v2"):
    global _semantic_model
    if _semantic_model is None:
        from sentence_transformers import SentenceTransformer
        print(f"Loading sentence transformer: {model_name}", flush=True)
        _semantic_model = SentenceTransformer(model_name)
    return _semantic_model


def semantic_similarity_matrix(
    h_texts: list[str],
    f_texts: list[str],
) -> list[list[float]]:
    """Return cosine similarity matrix[hi][fi] using sentence transformers."""
    if not h_texts or not f_texts:
        return [[0.0] * len(f_texts) for _ in h_texts]
    model = _get_semantic_model()
    import numpy as np
    h_emb = model.encode(h_texts, convert_to_numpy=True, show_progress_bar=False)
    f_emb = model.encode(f_texts, convert_to_numpy=True, show_progress_bar=False)
    h_norm = h_emb / (np.linalg.norm(h_emb, axis=1, keepdims=True) + 1e-9)
    f_norm = f_emb / (np.linalg.norm(f_emb, axis=1, keepdims=True) + 1e-9)
    sim = h_norm @ f_norm.T  # shape (n_h, n_f)
    return sim.tolist()


def greedy_event_matches(
    hindsight: list[EventNode],
    forecast: list[EventNode],
    threshold: float,
    method: str = "hybrid",
    top_k: int = 5,
    date_window_days: float | None = None,
) -> list[tuple[int, int, float]]:
    """Match forecast events to hindsight events greedily by text similarity.

    date_window_days: if set, a text match is only accepted when both events
    have a date AND |h_date - f_date| <= date_window_days. If either date is
    missing the date gate is skipped (text match alone is sufficient).
    """
    pairs: list[tuple[float, int, int]] = []
    h_texts = [event_text(event) for event in hindsight]
    f_texts = [event_text(event) for event in forecast]

    # Pre-compute similarity matrices depending on method
    h_to_f_bm25: list[list[float]] = []
    f_to_h_bm25: list[list[float]] = []
    sem_matrix:  list[list[float]] = []

    if method in {"bm25", "hybrid"}:
        h_to_f_bm25 = [normalize_scores(bm25_scores(h_text, f_texts)) for h_text in h_texts]
        f_to_h_bm25 = [normalize_scores(bm25_scores(f_text, h_texts)) for f_text in f_texts]
    if method == "semantic":
        sem_matrix = semantic_similarity_matrix(h_texts, f_texts)

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
            elif method == "semantic":
                score = sem_matrix[hi][fi]
            else:
                score = token_f1(event_text(he), event_text(fe))
            if score < threshold:
                continue
            # Date gate: reject if both dates present and error exceeds window
            if date_window_days is not None:
                de = date_error_days(he.occurred_date, fe.occurred_date)
                if de is not None and de > date_window_days:
                    continue
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
    question_info: QuestionInfo | None,
    impact_scores: ImpactScores | None,
    price_data: dict[str, Any],
    threshold: float,
    match_method: str,
    top_k: int,
    key_event_top_k: int,
    key_event_min_score: float,
    market_window_days: float,
    market_min_price_delta: float,
    market_turning_points: list[dt.datetime] | None = None,
    date_window_days: float | None = None,
) -> dict[str, Any]:
    hindsight_events = [event for event in hindsight_events_all if not event.is_outcome]
    matches = greedy_event_matches(
        hindsight_events_all,
        forecast_events,
        threshold,
        method=match_method,
        top_k=top_k,
        date_window_days=date_window_days,
    )
    matched_h = {hi for hi, _, _ in matches}
    matched_f = {fi for _, fi, _ in matches}

    event_recall = len(matched_h) / len(hindsight_events) if hindsight_events else None
    event_precision = len(matched_f) / len(forecast_events) if forecast_events else None
    if event_recall is not None and event_precision is not None and event_recall + event_precision:
        event_f1 = 2 * event_recall * event_precision / (event_recall + event_precision)
    else:
        event_f1 = None

    accessible_hindsight_events_all = events_available_by(
        hindsight_events_all,
        forecast.simulated_date,
    )
    accessible_hindsight_events = [
        event for event in accessible_hindsight_events_all if not event.is_outcome
    ]
    accessible_matches = greedy_event_matches(
        accessible_hindsight_events_all,
        forecast_events,
        threshold,
        method=match_method,
        top_k=top_k,
        date_window_days=date_window_days,
    )
    accessible_matched_h = {hi for hi, _, _ in accessible_matches}
    accessible_matched_f = {fi for _, fi, _ in accessible_matches}
    accessible_event_recall = (
        len(accessible_matched_h) / len(accessible_hindsight_events)
        if accessible_hindsight_events
        else None
    )
    accessible_event_precision = (
        len(accessible_matched_f) / len(forecast_events)
        if forecast_events
        else None
    )
    if (
        accessible_event_recall is not None
        and accessible_event_precision is not None
        and accessible_event_recall + accessible_event_precision
    ):
        accessible_event_f1 = (
            2
            * accessible_event_recall
            * accessible_event_precision
            / (accessible_event_recall + accessible_event_precision)
        )
    else:
        accessible_event_f1 = None

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
    key_events = key_event_metrics(
        hindsight_events=hindsight_events_all,
        forecast_events=forecast_events,
        matched_h=matched_h,
        matched_f=matched_f,
        impact_scores=impact_scores,
        key_event_top_k=key_event_top_k,
        key_event_min_score=key_event_min_score,
    )
    market_events = market_event_metrics(
        hindsight_events=hindsight_events_all,
        forecast_events=forecast_events,
        matched_h=matched_h,
        impact_scores=impact_scores,
        price_data=price_data,
        question_info=question_info,
        window_days=market_window_days,
        min_price_delta=market_min_price_delta,
        turning_points=market_turning_points,
    )

    forecast_node_ids = {event.id for event in forecast_events}
    matched_pairs = [
        {
            "hindsight_event_id": hindsight_events_all[hi].id,
            "forecast_event_id": forecast_events[fi].id,
            "similarity": round(sim, 4),
            "date_error_days": round(de, 1) if (de := date_error_days(
                hindsight_events_all[hi].occurred_date, forecast_events[fi].occurred_date
            )) is not None else None,
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
        "accessible_hindsight_events": len(accessible_hindsight_events),
        "forecast_events": len(forecast_events),
        "matched_events": len(matches),
        "accessible_matched_events": len(accessible_matches),
        "event_recall": event_recall,
        "event_precision": event_precision,
        "event_f1": event_f1,
        "accessible_event_recall": accessible_event_recall,
        "accessible_event_precision": accessible_event_precision,
        "accessible_event_f1": accessible_event_f1,
        "mean_match_similarity": mean([m[2] for m in matches]) if matches else None,
        "temporal_mae_days": mean(date_errors) if date_errors else None,
        "event_pair_source_overlap_rate": mean(source_hits) if source_hits else None,
        "forecast_max_depth": max_depth(forecast_edges, forecast_node_ids),
        "has_forecast_graph": bool(forecast_events and forecast_edges),
        "matched_pairs": matched_pairs,
        **question_source_metrics(forecast.articles_accessed, question_source_articles),
        **key_events,
        **market_events,
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
        "accessible_event_recall": avg("accessible_event_recall"),
        "accessible_event_precision": avg("accessible_event_precision"),
        "accessible_event_f1": avg("accessible_event_f1"),
        "mean_match_similarity": avg("mean_match_similarity"),
        "temporal_mae_days": avg("temporal_mae_days"),
        "exact_source_recall": avg("exact_source_recall"),
        "exact_source_precision": avg("exact_source_precision"),
        "event_pair_source_overlap_rate": avg("event_pair_source_overlap_rate"),
        "key_event_recall": avg("key_event_recall"),
        "key_event_precision": avg("key_event_precision"),
        "market_signal_recall": avg("market_signal_recall"),
        "market_signal_precision": avg("market_signal_precision"),
        "turning_point_signal_recall": avg("turning_point_signal_recall"),
        "turning_point_signal_precision": avg("turning_point_signal_precision"),
        "hindsight_market_direction_alignment": avg("hindsight_market_direction_alignment"),
        "edge_recall": avg("edge_recall"),
        "edge_precision": avg("edge_precision"),
        "direction_accuracy": avg("direction_accuracy"),
        "forecast_max_depth": avg("forecast_max_depth"),
        "market_direction_checks": sum(row.get("market_direction_checks") or 0 for row in rows),
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
        "accessible_hindsight_events",
        "forecast_events",
        "matched_events",
        "accessible_matched_events",
        "event_recall",
        "event_precision",
        "event_f1",
        "accessible_event_recall",
        "accessible_event_precision",
        "accessible_event_f1",
        "mean_match_similarity",
        "temporal_mae_days",
        "forecast_articles_accessed",
        "hindsight_source_articles",
        "exact_source_overlap_count",
        "exact_source_recall",
        "exact_source_precision",
        "event_pair_source_overlap_rate",
        "key_events",
        "matched_key_events",
        "key_event_recall",
        "key_event_precision",
        "market_signal_events",
        "market_signal_matched_events",
        "market_signal_recall",
        "market_signal_precision",
        "turning_point_signal_events",
        "turning_point_signal_matched_events",
        "turning_point_signal_recall",
        "turning_point_signal_precision",
        "hindsight_market_direction_alignment",
        "market_direction_checks",
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

    def model_label(model: str) -> str:
        return model

    def add_metric_row(lines: list[str], label: str, value: Any, kind: str = "pct") -> None:
        if kind == "raw":
            rendered = str(value) if value is not None else "--"
        elif kind == "num":
            rendered = num(value)
        else:
            rendered = pct(value)
        lines.append(f"| {label} | {rendered} |")

    lines = [
        "# Forecast Reasoning Graph Evaluation",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Run Settings",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| DB | `{summary['db']}` |",
        f"| Include IDs | `{summary['include_ids']}` |",
        f"| Match method | `{summary['match_method']}` |",
        f"| Match threshold | {summary['match_threshold']} |",
        f"| Knowledge leakage filter | {'enabled' if summary['filter_knowledge_leakage'] else 'disabled'} |",
        f"| Leakage-excluded rows | {summary['knowledge_leakage_excluded']} |",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    overall = summary["overall"]
    add_metric_row(lines, "Forecast rows", overall.get("n"), "raw")
    add_metric_row(lines, "Rows with graph artifacts", overall.get("n_with_graph"), "raw")
    add_metric_row(lines, "Accuracy", overall.get("accuracy"))
    add_metric_row(lines, "Event recall", overall.get("event_recall"))
    add_metric_row(lines, "Event precision", overall.get("event_precision"))
    add_metric_row(lines, "Event F1", overall.get("event_f1"))
    add_metric_row(lines, "Accessible event recall", overall.get("accessible_event_recall"))
    add_metric_row(lines, "Accessible event precision", overall.get("accessible_event_precision"))
    add_metric_row(lines, "Accessible event F1", overall.get("accessible_event_f1"))
    add_metric_row(lines, "Key-event recall", overall.get("key_event_recall"))
    add_metric_row(lines, "Market-signal recall", overall.get("market_signal_recall"))
    add_metric_row(lines, "Market-signal precision", overall.get("market_signal_precision"))
    add_metric_row(lines, "Turning-point market-signal recall", overall.get("turning_point_signal_recall"))
    add_metric_row(lines, "Turning-point market-signal precision", overall.get("turning_point_signal_precision"))
    add_metric_row(lines, "Market-direction alignment", overall.get("hindsight_market_direction_alignment"))
    add_metric_row(lines, "Source precision", overall.get("exact_source_precision"))
    add_metric_row(lines, "Temporal MAE days", overall.get("temporal_mae_days"), "num")
    add_metric_row(lines, "Edge recall", overall.get("edge_recall"))
    add_metric_row(lines, "Edge precision", overall.get("edge_precision"))
    add_metric_row(lines, "Direction accuracy", overall.get("direction_accuracy"))

    lines += [
        "",
        "Exact source recall is omitted from the main table because it is a strict coverage diagnostic over the full hindsight evidence corpus. Source quality is reported primarily as precision: among the sources the agent chose to access, how many exactly match question/hindsight provenance.",
        "",
        "Event F1 compares forecast events against the full post-resolution hindsight graph. Accessible Event F1 repeats the same matching after filtering hindsight events to those whose occurred date is on or before the forecast's simulated date.",
        "",
        "Key events are the highest-scoring hindsight events by impact magnitude times confidence. Market-signal recall is computed only for Polymarket questions with cached price history and primary-outcome impact links. Turning-point market-signal recall is the stricter subset where the market-aligned hindsight event is also within the market window of a detected turning point.",
        "",
        "A trailing `*` after `n` marks model-condition cells with fewer than 100 forecast rows.",
        "",
        "## By Condition",
        "",
        "| Condition | n | Graph n | Event F1 | Accessible F1 | Key-event Recall | Market R | Market P | TP R | TP P | Source Precision | Temporal MAE | Accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, stats in sorted(summary["by_condition"].items()):
        low_n = " *" if stats["n"] < 100 else ""
        lines.append(
            f"| {condition} | {stats['n']}{low_n} | {stats['n_with_graph']} | "
            f"{pct(stats['event_f1'])} | {pct(stats['accessible_event_f1'])} | "
            f"{pct(stats['key_event_recall'])} | "
            f"{pct(stats['market_signal_recall'])} | {pct(stats['market_signal_precision'])} | "
            f"{pct(stats['turning_point_signal_recall'])} | {pct(stats['turning_point_signal_precision'])} | "
            f"{pct(stats['exact_source_precision'])} | "
            f"{num(stats['temporal_mae_days'])} | {pct(stats['accuracy'])} |"
        )

    lines += [
        "",
        "## By Condition and Model",
        "",
        "### Full Table",
        "",
        "| Condition | Model | n | Graph n | Event F1 | Accessible F1 | Key-event Recall | Market R | Market P | TP R | TP P | Source Precision | Temporal MAE | Accuracy |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, stats in sorted(summary["by_condition_model"].items()):
        condition = stats["condition"]
        model = stats["model"]
        low_n = " *" if stats["n"] < 100 else ""
        lines.append(
            f"| {condition} | {model} | {stats['n']}{low_n} | {stats['n_with_graph']} | "
            f"{pct(stats['event_f1'])} | {pct(stats['accessible_event_f1'])} | "
            f"{pct(stats['key_event_recall'])} | "
            f"{pct(stats['market_signal_recall'])} | {pct(stats['market_signal_precision'])} | "
            f"{pct(stats['turning_point_signal_recall'])} | {pct(stats['turning_point_signal_precision'])} | "
            f"{pct(stats['exact_source_precision'])} | "
            f"{num(stats['temporal_mae_days'])} | {pct(stats['accuracy'])} |"
        )

    lines += ["", "### Split by Condition", ""]
    by_condition_models: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stats in summary["by_condition_model"].values():
        by_condition_models[stats["condition"]].append(stats)
    for condition, rows in sorted(by_condition_models.items()):
        lines += [
            f"#### {condition}",
            "",
            "| Model | n | Graph n | Event F1 | Accessible F1 | Key-event Recall | Market R | Market P | TP R | TP P | Source Precision | Temporal MAE | Accuracy |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for stats in sorted(rows, key=lambda item: (-1 if item.get("event_f1") is None else item["event_f1"]), reverse=True):
            low_n = " *" if stats["n"] < 100 else ""
            lines.append(
                f"| {stats['model']} | {stats['n']}{low_n} | {stats['n_with_graph']} | "
                f"{pct(stats['event_f1'])} | {pct(stats['accessible_event_f1'])} | "
                f"{pct(stats['key_event_recall'])} | "
                f"{pct(stats['market_signal_recall'])} | {pct(stats['market_signal_precision'])} | "
                f"{pct(stats['turning_point_signal_recall'])} | {pct(stats['turning_point_signal_precision'])} | "
                f"{pct(stats['exact_source_precision'])} | "
                f"{num(stats['temporal_mae_days'])} | {pct(stats['accuracy'])} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--include-ids", default=None)
    parser.add_argument(
        "--include-forecast-ids",
        default=None,
        help=(
            "Path to a file of forecast IDs (one per line) to pin evaluation to specific runs. "
            "When provided, bypasses latest-per-key selection and evaluates exactly these forecasts."
        ),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--match-threshold", type=float, default=0.45)
    parser.add_argument(
        "--date-window-days",
        type=float,
        default=None,
        help=(
            "Maximum allowed date error (days) between a matched hindsight and forecast event. "
            "If both events have a date and |h_date - f_date| > this value the match is rejected. "
            "If either event has no date the gate is skipped. Default: disabled (no date gate)."
        ),
    )
    parser.add_argument(
        "--match-method",
        choices=["lexical", "bm25", "hybrid", "semantic"],
        default="hybrid",
        help="Event matching method. 'hybrid' uses BM25 candidates + lexical overlap. 'semantic' uses sentence-transformers cosine similarity (all-MiniLM-L6-v2).",
    )
    parser.add_argument(
        "--semantic-model",
        default="all-MiniLM-L6-v2",
        help="Sentence transformer model name (used when --match-method semantic).",
    )
    parser.add_argument("--top-k", type=int, default=5, help="BM25 candidate count per hindsight event")
    parser.add_argument("--key-event-top-k", type=int, default=5)
    parser.add_argument("--key-event-min-score", type=float, default=0.20)
    parser.add_argument("--price-cache", default=str(DEFAULT_PRICE_CACHE))
    parser.add_argument("--market-window-days", type=float, default=3.0)
    parser.add_argument(
        "--market-min-price-delta",
        type=float,
        default=0.03,
        help="Minimum local market move, in probability points, for market-signal checks.",
    )
    parser.add_argument(
        "--market-turning-point-min-change",
        type=float,
        default=0.05,
        help="Minimum reversal size, in probability points, for turning-point market-signal checks.",
    )
    parser.add_argument(
        "--filter-knowledge-leakage",
        action="store_true",
        help="Exclude model-question pairs where question start predates the model knowledge cutoff.",
    )
    parser.add_argument(
        "--exclude-annotation-rejected",
        action="store_true",
        help="Exclude hindsight events with review_status='rejected' (annotation-filtered graph).",
    )
    parser.add_argument("--condition", nargs="*", default=None)
    parser.add_argument(
        "--model",
        nargs="*",
        default=None,
        help="Optional model whitelist. Use full model names as stored in forecast metadata.",
    )
    args = parser.parse_args()

    include_ids = read_ids(args.include_ids)
    include_forecast_ids = read_ids(args.include_forecast_ids)
    price_cache = load_price_cache(args.price_cache)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        forecasts = latest_forecasts(conn, include_ids, include_forecast_ids=include_forecast_ids)
        if args.condition:
            allowed = set(args.condition)
            forecasts = [f for f in forecasts if f.condition in allowed]
        if args.model:
            allowed_models = set(args.model)
            forecasts = [f for f in forecasts if f.model in allowed_models]
        before_leakage_filter = len(forecasts)
        if args.filter_knowledge_leakage:
            forecasts = [f for f in forecasts if not is_knowledge_leakage_pair(f)]
        knowledge_leakage_excluded = before_leakage_filter - len(forecasts)

        hindsight_events = load_hindsight_events(conn, include_ids, exclude_annotation_rejected=args.exclude_annotation_rejected)
        forecast_events = load_forecast_events(conn)
        hindsight_edges = load_hindsight_edges(conn, hindsight_events)
        forecast_edges = load_forecast_edges(conn)
        question_source_articles = load_question_source_articles(conn, include_ids)
        question_info = load_question_info(conn, include_ids)
        primary_outcome_ids = load_primary_outcome_ids(conn, question_info)
        impact_scores = load_impact_scores(conn, primary_outcome_ids, include_ids)
    finally:
        conn.close()

    market_turning_points = {
        qid: market_turning_point_datetimes(data, args.market_turning_point_min_change)
        for qid, data in price_cache.items()
        if data
    }

    if args.match_method == "semantic":
        # Pre-load model once before the per-forecast loop
        _get_semantic_model(args.semantic_model)

    rows: list[dict[str, Any]] = []
    for forecast in forecasts:
        row = score_forecast(
            forecast=forecast,
            hindsight_events_all=hindsight_events.get(forecast.question_id, []),
            forecast_events=forecast_events.get(forecast.id, []),
            hindsight_edges=hindsight_edges.get(forecast.question_id, []),
            forecast_edges=forecast_edges.get(forecast.id, []),
            question_source_articles=question_source_articles.get(forecast.question_id, set()),
            question_info=question_info.get(forecast.question_id),
            impact_scores=impact_scores.get(forecast.question_id),
            price_data=price_cache.get(forecast.question_id, {}),
            threshold=args.match_threshold,
            match_method=args.match_method,
            top_k=args.top_k,
            key_event_top_k=args.key_event_top_k,
            key_event_min_score=args.key_event_min_score,
            market_window_days=args.market_window_days,
            market_min_price_delta=args.market_min_price_delta,
            market_turning_points=market_turning_points.get(forecast.question_id, []),
            date_window_days=args.date_window_days,
        )
        rows.append(row)

    # Write pinned forecast IDs so future runs can reproduce exactly this evaluation
    forecast_ids_path = output_dir / "forecast_ids.txt"
    if not forecast_ids_path.exists() or include_forecast_ids is None:
        forecast_ids_path.write_text(
            "\n".join(sorted(r["forecast_id"] for r in rows)) + "\n", encoding="utf-8"
        )

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = (
        f"reasoning_graph_eval_filtered_{timestamp}"
        if args.filter_knowledge_leakage
        else f"reasoning_graph_eval_{timestamp}"
    )

    summary: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "db": args.db,
        "include_ids": args.include_ids,
        "include_forecast_ids": args.include_forecast_ids or str(forecast_ids_path),
        "match_threshold": args.match_threshold,
        "match_method": args.match_method,
        "date_window_days": args.date_window_days,
        "top_k": args.top_k,
        "key_event_top_k": args.key_event_top_k,
        "key_event_min_score": args.key_event_min_score,
        "price_cache": args.price_cache,
        "market_window_days": args.market_window_days,
        "market_min_price_delta": args.market_min_price_delta,
        "market_turning_point_min_change": args.market_turning_point_min_change,
        "models": args.model,
        "filter_knowledge_leakage": args.filter_knowledge_leakage,
        "exclude_annotation_rejected": args.exclude_annotation_rejected,
        "knowledge_leakage_excluded": knowledge_leakage_excluded,
        "overall": aggregate(rows),
        "by_condition": {},
        "by_condition_model": {},
    }
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    grouped_by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["condition"], row["model"])].append(row)
        grouped_by_condition[row["condition"]].append(row)
    summary["by_condition"] = {
        condition: {
            "condition": condition,
            **aggregate(value),
        }
        for condition, value in grouped_by_condition.items()
    }
    summary["by_condition_model"] = {
        f"{condition}::{model}": {
            "condition": condition,
            "model": model,
            **aggregate(value),
        }
        for (condition, model), value in grouped.items()
    }

    json_path = output_dir / f"{stem}.json"
    tsv_path = output_dir / f"{stem}.tsv"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(summary | {"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    write_tsv(rows, tsv_path)
    write_markdown(summary, md_path)
    latest_stem = (
        "reasoning_graph_eval_filtered_latest"
        if args.filter_knowledge_leakage
        else "reasoning_graph_eval_latest"
    )
    shutil.copyfile(json_path, output_dir / f"{latest_stem}.json")
    shutil.copyfile(tsv_path, output_dir / f"{latest_stem}.tsv")
    shutil.copyfile(md_path, output_dir / f"{latest_stem}.md")

    print(f"rows={len(rows)}")
    print(f"wrote={json_path}")
    print(f"latest={output_dir / f'{latest_stem}.md'}")
    print(f"overall_event_f1={summary['overall']['event_f1']}")
    print(f"overall_edge_recall={summary['overall']['edge_recall']}")

    # Write reasoning metrics back into forecasts.evaluation_metadata so the
    # REST API (/api/questions/{id}/forecasts, /api/evaluation/report) can
    # expose all paper metrics alongside is_correct / brier_score / log_score.
    REASONING_METRIC_KEYS = [
        "event_recall", "event_precision", "event_f1",
        "accessible_event_recall", "accessible_event_precision", "accessible_event_f1",
        "exact_source_recall", "exact_source_precision",
        "key_event_recall", "key_event_precision",
        "temporal_mae_days", "forecast_max_depth",
        "market_signal_recall", "hindsight_market_direction_alignment",
        "edge_recall", "edge_precision", "direction_accuracy",
        "matched_events", "hindsight_events", "forecast_events",
    ]
    updated = 0
    conn_wb = sqlite3.connect(args.db)
    try:
        for row in rows:
            fid = row.get("forecast_id")
            if not fid:
                continue
            existing = conn_wb.execute(
                "SELECT evaluation_metadata FROM forecasts WHERE id = ?", (fid,)
            ).fetchone()
            if existing is None:
                continue
            try:
                meta = json.loads(existing[0]) if existing[0] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta["reasoning_eval"] = {k: row.get(k) for k in REASONING_METRIC_KEYS}
            conn_wb.execute(
                "UPDATE forecasts SET evaluation_metadata = ? WHERE id = ?",
                (json.dumps(meta), fid),
            )
            updated += 1
        conn_wb.commit()
    finally:
        conn_wb.close()
    print(f"wrote reasoning metrics back to {updated} forecast rows in {args.db}")


if __name__ == "__main__":
    main()
