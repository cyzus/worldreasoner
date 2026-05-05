"""Evaluate forecast agent causal graphs against the hindsight ground-truth graph.

Metrics:
  M1 — Event Recall/Precision  (all conditions with causal tools)
  M2 — Causal Direction Alignment  (conditions with both causal tools + hypotheses)
  M3 — Source Alignment  (search/container conditions only — skipped when 0 source articles)
  M4 — Price Impact Alignment  (Polymarket questions only, uses cached price history)

Reference: experiments/evaluation/GRAPH_EVAL_PLAN.md

Usage:
    uv run python scripts/benchmark/evaluate_graphs.py
    uv run python scripts/benchmark/evaluate_graphs.py --condition structured_scenario
    uv run python scripts/benchmark/evaluate_graphs.py --sim-threshold 0.75
    uv run python scripts/benchmark/evaluate_graphs.py --price-window-days 7
"""

import argparse
import asyncio
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import get_config
from src.core.database import GenericDatabase
from src.core.llm import LiteLLMClient
from src.domain.models import Forecast, Question
from src.domain.models.causal_hypothesis import CausalHypothesis
from src.integrations.polymarket import analyze_price_curve
from src.domain.models.event import Event
from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis


DB_PATH = "combined.db"
OUTPUT_DIR = Path("experiments/evaluation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ANNOTATIONS_DIR = Path("annotations")
PRICE_CACHE_PATH = Path("scripts/annotation_ui/price_cache.json")

# Relation type direction groups
POSITIVE_RELATIONS = {"causes", "enables", "triggers", "amplifies"}
NEGATIVE_RELATIONS = {"prevents", "inhibits"}


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _event_text(title: str, description: str) -> str:
    return f"{title}. {description}" if description else title


def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def embed_texts(client: LiteLLMClient, texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, batching in groups of 50."""
    results = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        vecs = await client.aembedding(batch)
        results.extend(vecs)
    return results


# ---------------------------------------------------------------------------
# Greedy one-to-one matching
# ---------------------------------------------------------------------------

def greedy_match(
    hindsight_embs: list[list[float]],
    forecast_embs: list[list[float]],
    threshold: float,
) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching by descending similarity.

    Returns list of (hindsight_idx, forecast_idx, similarity).
    Each index appears at most once. Only pairs above threshold are returned.
    """
    if not hindsight_embs or not forecast_embs:
        return []

    # Build all pairs sorted by similarity descending
    pairs = []
    for hi, he in enumerate(hindsight_embs):
        for fi, fe in enumerate(forecast_embs):
            sim = cosine_sim(he, fe)
            if sim >= threshold:
                pairs.append((sim, hi, fi))
    pairs.sort(reverse=True)

    matched_h, matched_f = set(), set()
    result = []
    for sim, hi, fi in pairs:
        if hi not in matched_h and fi not in matched_f:
            matched_h.add(hi)
            matched_f.add(fi)
            result.append((hi, fi, sim))
    return result


# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

def relation_group(rel_type: str) -> Optional[str]:
    if rel_type in POSITIVE_RELATIONS:
        return "positive"
    if rel_type in NEGATIVE_RELATIONS:
        return "negative"
    return None  # neutral/correlates — skip direction check


def direction_matches(h_rel: str, f_rel: str) -> Optional[bool]:
    """None if either relation is neutral (can't judge direction)."""
    hg = relation_group(h_rel)
    fg = relation_group(f_rel)
    if hg is None or fg is None:
        return None
    return hg == fg


# ---------------------------------------------------------------------------
# Price impact helpers (M4)
# ---------------------------------------------------------------------------

def load_price_cache() -> dict:
    """Load Polymarket price history cache. Returns {} if file missing."""
    if not PRICE_CACHE_PATH.exists():
        return {}
    with open(PRICE_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_turning_point_timestamps(price_cache: dict, question_id: str) -> list[datetime]:
    """Extract turning point datetimes for a Polymarket question."""
    entry = price_cache.get(question_id)
    if not entry:
        return []
    history = entry.get("history", [])
    if not history:
        return []
    try:
        analysis = analyze_price_curve(
            history,
            min_turning_point_change=5.0,
            min_sharp_movement_change=10.0,
        )
    except Exception:
        return []
    timestamps = []
    for tp in analysis.get("turning_points", []):
        t = tp.get("timestamp") or tp.get("t")
        if t is None:
            continue
        if isinstance(t, (int, float)):
            timestamps.append(datetime.fromtimestamp(t, tz=timezone.utc))
        elif isinstance(t, str):
            try:
                timestamps.append(datetime.fromisoformat(t).replace(tzinfo=timezone.utc))
            except ValueError:
                pass
        elif isinstance(t, datetime):
            timestamps.append(t if t.tzinfo else t.replace(tzinfo=timezone.utc))
    return timestamps


def nearest_changepoint_days(
    event_date: Optional[datetime],
    turning_points: list[datetime],
) -> Optional[float]:
    """Return the number of days between event_date and the nearest turning point."""
    if not event_date or not turning_points:
        return None
    ed = event_date if event_date.tzinfo else event_date.replace(tzinfo=timezone.utc)
    return min(abs((ed - tp).total_seconds()) / 86400.0 for tp in turning_points)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_data(db: GenericDatabase):
    forecasts = db.get_many(Forecast, filters={})
    questions = db.get_many(Question, filters={})
    events = db.get_many(Event, filters={})
    hyps = db.get_many(CausalHypothesis, filters={})
    fevents = db.get_many(ForecastEvent, filters={})
    fhyps = db.get_many(ForecastHypothesis, filters={})

    q_map = {q.id: q for q in questions}

    # Hindsight events per question (exclude outcome nodes — trivially recoverable)
    hindsight_by_qid: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.extracted_for_question_id and not e.is_outcome:
            hindsight_by_qid[e.extracted_for_question_id].append(e)

    # Hindsight hypotheses indexed by (source_event_id, target_event_id)
    hindsight_hyp_index: dict[tuple[str, str], CausalHypothesis] = {}
    for h in hyps:
        hindsight_hyp_index[(h.source_event_id, h.target_event_id)] = h

    # ForecastEvents per forecast_id
    fe_by_fcst: dict[str, list[ForecastEvent]] = defaultdict(list)
    for fe in fevents:
        if fe.forecast_id:
            fe_by_fcst[fe.forecast_id].append(fe)

    # ForecastHypotheses indexed by (forecast_id, source_event_id, target_event_id)
    fh_index: dict[tuple[str, str, str], ForecastHypothesis] = {}
    for fh in fhyps:
        if fh.forecast_id:
            fh_index[(fh.forecast_id, fh.source_event_id, fh.target_event_id)] = fh

    # Deduplicated forecasts per (condition, model, question)
    latest_forecasts: dict[tuple[str, str, str], Forecast] = {}
    for f in forecasts:
        bc = (f.evaluation_metadata or {}).get("benchmark_condition")
        if not bc:
            continue
        key = (bc, f.model_name or "unknown", f.question_id)
        if key not in latest_forecasts or f.timestamp > latest_forecasts[key].timestamp:
            latest_forecasts[key] = f

    price_cache = load_price_cache()
    print(f"Price cache: {len(price_cache)} entries loaded")

    return {
        "q_map": q_map,
        "hindsight_by_qid": hindsight_by_qid,
        "hindsight_hyp_index": hindsight_hyp_index,
        "fe_by_fcst": fe_by_fcst,
        "fh_index": fh_index,
        "latest_forecasts": latest_forecasts,
        "price_cache": price_cache,
    }


def load_annotations() -> dict[str, list[dict]]:
    """Load annotation files. Returns {question_id: [approved_events]}."""
    if not ANNOTATIONS_DIR.exists():
        return {}
    by_qid: dict[str, dict[str, dict]] = defaultdict(dict)
    for fpath in ANNOTATIONS_DIR.glob("*.json"):
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("data", []):
            qid = item.get("id", "")
            if qid.startswith("attention"):
                continue
            for evt in item.get("events", []):
                if evt.get("id", "").startswith("attention"):
                    continue
                eid = evt["id"]
                if evt.get("current_status") == "approved":
                    # Merge across sessions: keep any approved version
                    by_qid[qid][eid] = evt
    return {qid: list(evts.values()) for qid, evts in by_qid.items()}


# ---------------------------------------------------------------------------
# Per-question scoring
# ---------------------------------------------------------------------------

async def score_question(
    question_id: str,
    forecast: Forecast,
    hindsight_events: list[Event],
    fe_list: list[ForecastEvent],
    hindsight_hyp_index: dict,
    fh_index: dict,
    client: LiteLLMClient,
    threshold: float,
    turning_points: list[datetime],
    price_window_days: float,
) -> dict:
    if not hindsight_events or not fe_list:
        return {
            "n_hindsight_events": len(hindsight_events),
            "n_forecast_events": len(fe_list),
            "recall": 0.0,
            "precision": 0.0 if fe_list else None,
            "matched_pairs": [],
            "direction_accuracy": None,
            "source_recall": None,
            "n_price_turning_points": len(turning_points),
            "price_aligned_recall": None,
            "event_impact_rate": None,
            "skipped": True,
        }

    # Embed all texts
    h_texts = [_event_text(e.title, e.description) for e in hindsight_events]
    f_texts = [_event_text(e.title, e.description) for e in fe_list]
    all_texts = h_texts + f_texts
    all_embs = await embed_texts(client, all_texts)
    h_embs = all_embs[:len(h_texts)]
    f_embs = all_embs[len(h_texts):]

    matches = greedy_match(h_embs, f_embs, threshold)
    matched_h = {hi for hi, _, _ in matches}
    matched_f = {fi for _, fi, _ in matches}

    recall = len(matched_h) / len(hindsight_events)
    precision = len(matched_f) / len(fe_list)

    # M2: direction alignment on matched pairs
    direction_checks = []
    # M3: source overlap on matched pairs
    source_checks = []

    matched_pairs = []
    for hi, fi, sim in matches:
        he = hindsight_events[hi]
        fe = fe_list[fi]

        # Direction: find edges in both graphs for this pair
        h_edge = hindsight_hyp_index.get((he.id, he.id))  # placeholder — see below
        # Look for any hypothesis in hindsight graph where source or target == he.id
        # and the matched forecast event is on the other side
        # Simplified: check if a forecast hypothesis exists between any two matched forecast events
        # and whether its direction matches any hindsight hypothesis on the corresponding pair
        dir_match = None
        # Check forecast hypothesis for this forecast event against other matched forecast events
        for hi2, fi2, _ in matches:
            if fi2 == fi:
                continue
            fe2 = fe_list[fi2]
            he2 = hindsight_events[hi2]
            # Check both directions
            for (src_f, tgt_f), (src_h, tgt_h) in [
                ((fe.id, fe2.id), (he.id, he2.id)),
                ((fe2.id, fe.id), (he2.id, he.id)),
            ]:
                fh = fh_index.get((forecast.id, src_f, tgt_f))
                hh = hindsight_hyp_index.get((src_h, tgt_h))
                if fh and hh:
                    dm = direction_matches(
                        hh.relation_type.value, fh.relation_type.value
                    )
                    if dm is not None:
                        direction_checks.append(dm)
                        dir_match = dm
                        break
            if dir_match is not None:
                break

        # Source overlap
        src_match = None
        if fe.source_article_ids and he.article_ids:
            overlap = set(fe.source_article_ids) & set(he.article_ids)
            src_match = len(overlap) > 0
            source_checks.append(src_match)

        # M4: price changepoint proximity (use forecast event date if available, else hindsight)
        near_cp = None
        cp_days = None
        if turning_points:
            event_date = fe.occurred_date or he.occurred_date
            cp_days = nearest_changepoint_days(event_date, turning_points)
            if cp_days is not None:
                near_cp = cp_days <= price_window_days

        matched_pairs.append({
            "hindsight_event_id": he.id,
            "hindsight_event_title": he.title,
            "forecast_event_id": fe.id,
            "forecast_event_title": fe.title,
            "similarity": round(sim, 4),
            "direction_match": dir_match,
            "source_match": src_match,
            "near_price_changepoint": near_cp,
            "nearest_changepoint_days": round(cp_days, 2) if cp_days is not None else None,
        })

    direction_accuracy = (
        sum(direction_checks) / len(direction_checks)
        if direction_checks else None
    )
    source_recall = (
        sum(source_checks) / len(source_checks)
        if source_checks else None
    )

    # M4: price-aligned recall — fraction of turning points covered by a nearby forecast event
    price_aligned_recall = None
    event_impact_rate = None
    if turning_points:
        # For each turning point, is there any forecast event within the window?
        tp_covered = sum(
            1 for tp in turning_points
            if any(
                (d := nearest_changepoint_days(
                    fe_list[fi].occurred_date or hindsight_events[hi].occurred_date, [tp]
                )) is not None and d <= price_window_days
                for hi, fi, _sim in matches
            )
        )
        price_aligned_recall = tp_covered / len(turning_points)
        # Event impact rate — fraction of forecast events near any turning point
        impact_hits = sum(
            1 for fe in fe_list
            if turning_points and
            (nearest_changepoint_days(fe.occurred_date, turning_points) or 999) <= price_window_days
        )
        event_impact_rate = impact_hits / len(fe_list)

    return {
        "n_hindsight_events": len(hindsight_events),
        "n_forecast_events": len(fe_list),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "matched_pairs": matched_pairs,
        "direction_accuracy": round(direction_accuracy, 4) if direction_accuracy is not None else None,
        "source_recall": round(source_recall, 4) if source_recall is not None else None,
        "n_price_turning_points": len(turning_points),
        "price_aligned_recall": round(price_aligned_recall, 4) if price_aligned_recall is not None else None,
        "event_impact_rate": round(event_impact_rate, 4) if event_impact_rate is not None else None,
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# Calibration against annotations
# ---------------------------------------------------------------------------

def calibrate_against_annotations(
    annotations: dict[str, list[dict]],
    hindsight_by_qid: dict[str, list[Event]],
) -> dict:
    """Check what fraction of annotation-approved events appear in hindsight graph by ID."""
    results = {}
    for qid, approved_events in annotations.items():
        hindsight_ids = {e.id for e in hindsight_by_qid.get(qid, [])}
        total = len(approved_events)
        found = sum(1 for e in approved_events if e["id"] in hindsight_ids)
        results[qid] = {
            "n_approved": total,
            "n_in_hindsight": found,
            "recall": round(found / total, 4) if total else 0.0,
        }
    overall_approved = sum(r["n_approved"] for r in results.values())
    overall_found = sum(r["n_in_hindsight"] for r in results.values())
    return {
        "per_question": results,
        "overall_recall": round(overall_found / overall_approved, 4) if overall_approved else 0.0,
        "n_questions": len(results),
        "n_approved_events": overall_approved,
        "n_found_in_hindsight": overall_found,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(question_results: dict[str, dict]) -> dict:
    recalls = [r["recall"] for r in question_results.values() if not r.get("skipped")]
    precisions = [r["precision"] for r in question_results.values() if not r.get("skipped") and r["precision"] is not None]
    dir_accs = [r["direction_accuracy"] for r in question_results.values() if r.get("direction_accuracy") is not None]
    src_recalls = [r["source_recall"] for r in question_results.values() if r.get("source_recall") is not None]
    price_recalls = [r["price_aligned_recall"] for r in question_results.values() if r.get("price_aligned_recall") is not None]
    impact_rates = [r["event_impact_rate"] for r in question_results.values() if r.get("event_impact_rate") is not None]

    return {
        "n_questions": len(question_results),
        "n_scored": len(recalls),
        "recall": round(statistics.mean(recalls), 4) if recalls else None,
        "precision": round(statistics.mean(precisions), 4) if precisions else None,
        "direction_accuracy": round(statistics.mean(dir_accs), 4) if dir_accs else None,
        "source_recall": round(statistics.mean(src_recalls), 4) if src_recalls else None,
        "price_aligned_recall": round(statistics.mean(price_recalls), 4) if price_recalls else None,
        "event_impact_rate": round(statistics.mean(impact_rates), 4) if impact_rates else None,
        "n_price_questions": len(price_recalls),
    }


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _f(v, d=3):
    return f"{v:.{d}f}" if v is not None else "—"

def _pct(v):
    return f"{v:.1%}" if v is not None else "—"


def write_markdown(results: dict, path: Path):
    lines = [
        f"# Graph Evaluation — {results['condition']}",
        "",
        f"**Generated:** {results['generated_at']}  ",
        f"**Database:** `{results['db']}`  ",
        f"**Similarity threshold:** {results['sim_threshold']}  ",
        "",
    ]

    # Calibration section
    cal = results.get("calibration")
    if cal:
        lines += [
            "## Annotation Calibration",
            "",
            f"Fraction of human-approved annotation events found in hindsight graph (by ID): "
            f"**{_pct(cal['overall_recall'])}** "
            f"({cal['n_found_in_hindsight']}/{cal['n_approved_events']} events, {cal['n_questions']} questions)",
            "",
        ]

    # Per-model summary
    lines += ["## Results by Model", ""]
    lines += ["| Model | Recall | Precision | Direction Acc | Source Recall | Price-Aligned Recall | Event Impact Rate | n |"]
    lines += ["| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for model, model_data in sorted(results["by_model"].items(), key=lambda x: -(x[1]["overall"]["recall"] or 0)):
        ov = model_data["overall"]
        short = model.split("/")[-1]
        n_price = ov.get("n_price_questions", 0)
        price_note = f" ({n_price}q)" if n_price else ""
        lines.append(
            f"| {short} | {_pct(ov['recall'])} | {_pct(ov['precision'])} | "
            f"{_pct(ov['direction_accuracy'])} | {_pct(ov['source_recall'])} | "
            f"{_pct(ov.get('price_aligned_recall'))}{price_note} | "
            f"{_pct(ov.get('event_impact_rate'))} | {ov['n_scored']} |"
        )
    lines.append("")

    # Threshold sensitivity
    sens = results.get("threshold_sensitivity")
    if sens:
        lines += ["## Threshold Sensitivity (Recall)", ""]
        lines += ["| Model | " + " | ".join(f"@{t}" for t in sorted(sens[next(iter(sens))].keys())) + " |"]
        lines += ["| --- |" + "".join([" --- |"] * len(next(iter(sens.values()))))]
        for model, thresholds in sorted(sens.items()):
            short = model.split("/")[-1]
            cells = [_pct(thresholds[t]) for t in sorted(thresholds)]
            lines.append(f"| {short} | " + " | ".join(cells) + " |")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(condition: str, data: dict, client: LiteLLMClient, threshold: float, db_path: str, price_window_days: float = 7.0) -> dict:
    hindsight_by_qid = data["hindsight_by_qid"]
    hindsight_hyp_index = data["hindsight_hyp_index"]
    fe_by_fcst = data["fe_by_fcst"]
    fh_index = data["fh_index"]
    latest_forecasts = data["latest_forecasts"]
    price_cache = data["price_cache"]
    q_map = data["q_map"]

    # Collect all (model, question_id) for this condition
    condition_forecasts = {
        (model, qid): f
        for (bc, model, qid), f in latest_forecasts.items()
        if bc == condition
    }
    if not condition_forecasts:
        print(f"[{condition}] No forecasts found.")
        return {}

    models = sorted({m for m, _ in condition_forecasts})
    print(f"[{condition}] Models: {models}")
    print(f"[{condition}] Forecasts: {len(condition_forecasts)}")

    by_model: dict[str, dict] = {}

    for model in models:
        model_qs = {qid: f for (m, qid), f in condition_forecasts.items() if m == model}
        question_results: dict[str, dict] = {}

        for qid, forecast in model_qs.items():
            hindsight_events = hindsight_by_qid.get(qid, [])
            fe_list = fe_by_fcst.get(forecast.id, [])

            # M4: get turning points if this is a Polymarket question
            q = q_map.get(qid)
            is_polymarket = q and getattr(q, "source", "") == "polymarket"
            turning_points = get_turning_point_timestamps(price_cache, qid) if is_polymarket else []

            if not fe_list:
                question_results[qid] = {
                    "n_hindsight_events": len(hindsight_events),
                    "n_forecast_events": 0,
                    "recall": 0.0,
                    "precision": None,
                    "matched_pairs": [],
                    "direction_accuracy": None,
                    "source_recall": None,
                    "n_price_turning_points": len(turning_points),
                    "price_aligned_recall": None,
                    "event_impact_rate": None,
                    "skipped": True,
                    "skip_reason": "no_forecast_events",
                }
                continue

            result = await score_question(
                qid, forecast, hindsight_events, fe_list,
                hindsight_hyp_index, fh_index, client, threshold,
                turning_points, price_window_days,
            )
            question_results[qid] = result
            status = f"recall={result['recall']:.2f} prec={result['precision']:.2f} n_h={result['n_hindsight_events']} n_f={result['n_forecast_events']}"
            print(f"  [{model.split('/')[-1]}] {qid[:45]} {status}")

        by_model[model] = {
            "overall": aggregate(question_results),
            "questions": question_results,
        }
        ov = by_model[model]["overall"]
        print(f"  [{model.split('/')[-1]}] OVERALL recall={_pct(ov['recall'])} precision={_pct(ov['precision'])} dir={_pct(ov['direction_accuracy'])} n={ov['n_scored']}")

    return by_model


async def main_async(args):
    config = get_config()
    client = LiteLLMClient(config.llm)
    db = GenericDatabase(args.db)

    print("Loading data...")
    data = load_all_data(db)
    annotations = load_annotations()

    # Calibration (one-time, independent of condition)
    calibration = None
    if annotations:
        calibration = calibrate_against_annotations(annotations, data["hindsight_by_qid"])
        print(f"Annotation calibration: hindsight recalls {calibration['overall_recall']:.1%} of approved events "
              f"({calibration['n_found_in_hindsight']}/{calibration['n_approved_events']})")

    # Determine conditions
    if args.condition:
        conditions = args.condition
    else:
        present = {
            bc for (bc, _, _) in data["latest_forecasts"]
            if bc not in ("vanilla_llm",)  # vanilla has no graph
        }
        conditions = sorted(present)
        print(f"Auto-detected conditions with graphs: {conditions}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for condition in conditions:
        print(f"\n{'='*60}")
        print(f"Evaluating: {condition}")
        print(f"{'='*60}")

        by_model = await run(condition, data, client, args.sim_threshold, args.db, args.price_window_days)
        if not by_model:
            continue

        # Threshold sensitivity (reuse cached hindsight embeddings is not needed here —
        # run at additional thresholds only for the overall recall summary)
        sensitivity: dict[str, dict[float, Optional[float]]] = {}
        for model, model_data in by_model.items():
            sensitivity[model] = {}
            for t in (0.65, 0.75, 0.85):
                recalls = [
                    r["recall"] for r in model_data["questions"].values()
                    if not r.get("skipped")
                ]
                # NOTE: threshold sensitivity would require re-running matching at each threshold.
                # Here we report a placeholder that the main threshold result satisfies.
                # A full sweep is left as a future extension.
                sensitivity[model][t] = None  # placeholder

        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db": args.db,
            "condition": condition,
            "sim_threshold": args.sim_threshold,
            "calibration": calibration,
            "by_model": by_model,
        }

        json_path = OUTPUT_DIR / f"graph_eval_{condition}_{ts}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False, default=str)
        print(f"Saved to {json_path}")

        md_path = OUTPUT_DIR / f"graph_eval_{condition}_{ts}.md"
        write_markdown(output, md_path)
        print(f"Saved to {md_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate forecast causal graphs against hindsight ground truth")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--condition", nargs="*", metavar="CONDITION")
    parser.add_argument("--sim-threshold", type=float, default=0.75,
                        help="Cosine similarity threshold for event matching (default: 0.75)")
    parser.add_argument("--price-window-days", type=float, default=7.0,
                        help="Days window for price changepoint proximity (default: 7)")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
