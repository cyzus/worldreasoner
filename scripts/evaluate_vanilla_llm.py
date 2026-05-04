"""Evaluate vanilla_llm forecasts from combined.db and write results to experiments/."""

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.core.database import GenericDatabase
from src.domain.models import Forecast, Question
from src.domain.models.question import QuestionType


DB_PATH = "combined.db"
OUTPUT_DIR = Path("experiments")
OUTPUT_DIR.mkdir(exist_ok=True)


def normalize_binary(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
    return val


def score_forecast(f: Forecast, q: Question):
    """Return (is_correct, brier_score) for a forecast."""
    pred = f.prediction
    gt = q.ground_truth
    qtype = q.question_type

    if qtype == QuestionType.BINARY:
        pred_n = normalize_binary(pred)
        gt_n = normalize_binary(gt)
        if pred_n is None or gt_n is None:
            return None, None
        is_correct = pred_n == gt_n
        conf = f.confidence
        forecast_prob = conf if pred_n else (1.0 - conf)
        outcome = 1.0 if gt_n else 0.0
        brier = (forecast_prob - outcome) ** 2
        log_score = None
        import math
        prob_actual = forecast_prob if gt_n else (1.0 - forecast_prob)
        log_score = math.log(max(prob_actual, 1e-10))
        return is_correct, brier, log_score

    elif qtype == QuestionType.MCQ:
        is_correct = pred == gt
        conf = f.confidence
        brier = (1.0 - conf) ** 2 if is_correct else conf ** 2
        import math
        prob_correct = conf if is_correct else (1.0 - conf)
        log_score = math.log(max(prob_correct, 1e-10))
        return is_correct, brier, log_score

    elif qtype == QuestionType.QUANTITY:
        try:
            pred_v = float(pred)
            gt_v = float(gt)
            tol = abs(gt_v) * 0.1
            is_correct = abs(pred_v - gt_v) <= tol
        except (TypeError, ValueError):
            is_correct = False
        return is_correct, None, None

    elif qtype == QuestionType.TIMEFRAME:
        is_correct = str(pred) == str(gt)
        return is_correct, None, None

    return None, None, None


def _pct(v):
    return f"{v:.1%}" if v is not None else "—"

def _f(v, decimals=3):
    return f"{v:.{decimals}f}" if v is not None else "—"


def write_markdown(output: dict, path: Path) -> None:
    lines = []
    lines.append(f"# Vanilla LLM Evaluation")
    lines.append(f"")
    lines.append(f"**Database:** `{output['db']}`  ")
    lines.append(f"**Generated:** {output['generated_at']}  ")
    lines.append(f"**Total forecasts:** {output['total_forecasts']}  |  **Skipped:** {output['skipped']}")
    lines.append("")

    # Overall summary table
    ov = output["overall"]
    lines.append("## Overall")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Accuracy | {_pct(ov['accuracy'])} ({ov['correct']}/{ov['total']}) |")
    lines.append(f"| Mean Brier Score | {_f(ov['avg_brier_score'])} |")
    lines.append(f"| Mean Log Score | {_f(ov['avg_log_score'])} |")
    lines.append("")

    # Per-model summary table
    lines.append("## By Model")
    lines.append("")
    lines.append("| Model | Accuracy | Brier | Log Score | n |")
    lines.append("|---|---|---|---|---|")
    for model, stats in sorted(output["by_model"].items(), key=lambda x: -x[1]["accuracy"]):
        short = model.split("/")[-1]
        lines.append(
            f"| {short} | {_pct(stats['accuracy'])} | {_f(stats['avg_brier_score'])} "
            f"| {_f(stats['avg_log_score'])} | {stats['total']} |"
        )
    lines.append("")

    # Per-model × per-type breakdown table
    lines.append("## By Model × Question Type")
    lines.append("")
    qtypes = ["binary", "mcq", "quantity", "timeframe"]
    header = "| Model | " + " | ".join(f"{qt.capitalize()} Acc" for qt in qtypes) + " | Total Acc |"
    sep = "|---|" + "|".join(["---|"] * (len(qtypes) + 1))
    lines.append(header)
    lines.append(sep)
    for model, stats in sorted(output["by_model"].items(), key=lambda x: -x[1]["accuracy"]):
        short = model.split("/")[-1]
        cells = []
        for qt in qtypes:
            ts = stats["by_question_type"].get(qt)
            if ts:
                cells.append(f"{_pct(ts['accuracy'])} ({ts['correct']}/{ts['total']})")
            else:
                cells.append("—")
        cells.append(_pct(stats["accuracy"]))
        lines.append(f"| {short} | " + " | ".join(cells) + " |")
    lines.append("")

    # Brier score breakdown table (binary + mcq only)
    lines.append("## Brier Score by Model × Question Type")
    lines.append("")
    brier_qtypes = ["binary", "mcq"]
    header = "| Model | " + " | ".join(f"{qt.capitalize()} Brier" for qt in brier_qtypes) + " | Overall Brier |"
    sep = "|---|" + "|".join(["---|"] * (len(brier_qtypes) + 1))
    lines.append(header)
    lines.append(sep)
    for model, stats in sorted(output["by_model"].items(), key=lambda x: x[1].get("avg_brier_score") or 1):
        short = model.split("/")[-1]
        cells = []
        for qt in brier_qtypes:
            ts = stats["by_question_type"].get(qt)
            cells.append(_f(ts["avg_brier_score"]) if ts and ts["avg_brier_score"] is not None else "—")
        cells.append(_f(stats["avg_brier_score"]))
        lines.append(f"| {short} | " + " | ".join(cells) + " |")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    db = GenericDatabase(DB_PATH)
    all_forecasts = db.get_many(Forecast, filters={})
    all_questions = db.get_many(Question, filters={})
    q_map = {q.id: q for q in all_questions}

    vanilla = [
        f for f in all_forecasts
        if (f.evaluation_metadata or {}).get("benchmark_condition") == "vanilla_llm"
    ]
    print(f"vanilla_llm forecasts: {len(vanilla)}")

    # Per-model, per-type breakdown
    # structure: results[model][qtype] = {correct, total, brier, log_score}
    results = defaultdict(lambda: defaultdict(lambda: {
        "correct": 0, "total": 0, "brier": [], "log_score": [], "details": []
    }))
    skipped = 0

    for f in vanilla:
        q = q_map.get(f.question_id)
        if q is None or q.ground_truth is None:
            skipped += 1
            continue

        scored = score_forecast(f, q)
        if len(scored) == 3:
            is_correct, brier, log_score = scored
        else:
            is_correct, brier = scored
            log_score = None

        if is_correct is None:
            skipped += 1
            continue

        model = f.model_name or "unknown"
        qtype = q.question_type.value
        bucket = results[model][qtype]
        bucket["total"] += 1
        if is_correct:
            bucket["correct"] += 1
        if brier is not None:
            bucket["brier"].append(brier)
        if log_score is not None:
            bucket["log_score"].append(log_score)
        bucket["details"].append({
            "forecast_id": f.id,
            "question_id": f.question_id,
            "prediction": str(f.prediction),
            "ground_truth": str(q.ground_truth),
            "confidence": f.confidence,
            "is_correct": is_correct,
            "brier_score": brier,
            "log_score": log_score,
            "simulated_date": f.simulated_date.isoformat() if f.simulated_date else None,
        })

    print(f"Skipped (no ground truth or unscored): {skipped}")

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": DB_PATH,
        "condition": "vanilla_llm",
        "total_forecasts": len(vanilla),
        "skipped": skipped,
        "by_model": {},
    }

    all_correct = 0
    all_total = 0
    all_brier = []
    all_log = []

    for model, by_type in sorted(results.items()):
        model_correct = 0
        model_total = 0
        model_brier = []
        model_log = []
        model_by_type = {}

        for qtype, stats in sorted(by_type.items()):
            acc = stats["correct"] / stats["total"] if stats["total"] else 0
            avg_brier = statistics.mean(stats["brier"]) if stats["brier"] else None
            avg_log = statistics.mean(stats["log_score"]) if stats["log_score"] else None
            model_by_type[qtype] = {
                "correct": stats["correct"],
                "total": stats["total"],
                "accuracy": round(acc, 4),
                "avg_brier_score": round(avg_brier, 4) if avg_brier is not None else None,
                "avg_log_score": round(avg_log, 4) if avg_log is not None else None,
            }
            model_correct += stats["correct"]
            model_total += stats["total"]
            model_brier.extend(stats["brier"])
            model_log.extend(stats["log_score"])

        model_acc = model_correct / model_total if model_total else 0
        output["by_model"][model] = {
            "correct": model_correct,
            "total": model_total,
            "accuracy": round(model_acc, 4),
            "avg_brier_score": round(statistics.mean(model_brier), 4) if model_brier else None,
            "avg_log_score": round(statistics.mean(model_log), 4) if model_log else None,
            "by_question_type": model_by_type,
        }

        all_correct += model_correct
        all_total += model_total
        all_brier.extend(model_brier)
        all_log.extend(model_log)

    output["overall"] = {
        "correct": all_correct,
        "total": all_total,
        "accuracy": round(all_correct / all_total, 4) if all_total else 0,
        "avg_brier_score": round(statistics.mean(all_brier), 4) if all_brier else None,
        "avg_log_score": round(statistics.mean(all_log), 4) if all_log else None,
    }

    # Write JSON
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"vanilla_llm_eval_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path}")

    # Write Markdown report
    md_path = OUTPUT_DIR / f"vanilla_llm_eval_{ts}.md"
    write_markdown(output, md_path)
    print(f"Saved to {md_path}")

    # Print summary to stdout
    print(f"\n{'='*60}")
    print(f"VANILLA LLM EVALUATION — {DB_PATH}")
    print(f"{'='*60}")
    print(f"Total scored: {all_total}  |  Skipped: {skipped}")
    print(f"Overall accuracy: {all_correct}/{all_total} = {all_correct/all_total:.1%}" if all_total else "No results")
    if all_brier:
        print(f"Mean Brier (binary+mcq): {statistics.mean(all_brier):.3f}")
    if all_log:
        print(f"Mean Log Score:          {statistics.mean(all_log):.3f}")
    print()
    for model, stats in output["by_model"].items():
        print(f"  {model}")
        print(f"    accuracy={stats['accuracy']:.1%}  brier={stats['avg_brier_score']}  log={stats['avg_log_score']}  n={stats['total']}")
        for qtype, ts_stats in stats["by_question_type"].items():
            print(f"      {qtype:12s}: {ts_stats['correct']}/{ts_stats['total']} = {ts_stats['accuracy']:.1%}", end="")
            if ts_stats["avg_brier_score"] is not None:
                print(f"  brier={ts_stats['avg_brier_score']}", end="")
            print()
        print()


if __name__ == "__main__":
    main()
