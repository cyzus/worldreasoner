"""Evaluate benchmark forecasts from combined.db and write results to experiments/evaluation/.

Usage:
    uv run python scripts/benchmark/evaluate_benchmark.py
    uv run python scripts/benchmark/evaluate_benchmark.py --condition vanilla_llm structured_scenario
    uv run python scripts/benchmark/evaluate_benchmark.py --db other.db
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.core.database import GenericDatabase
from src.core.llm import get_knowledge_cutoff_date
from src.domain.evaluation.conditions import ConditionName, get_conditions
from src.domain.evaluation.metrics import (
    calculate_accuracy,
    calculate_brier_score,
    calculate_log_score,
)
from src.domain.models import Forecast, Question
from src.domain.models.question import QuestionType


DB_PATH = "combined.db"
OUTPUT_DIR = Path("experiments/evaluation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALL_CONDITIONS = [c.value for c in ConditionName]


def score_forecast(f: Forecast, q: Question):
    """Return (is_correct, brier_score, log_score) for a forecast."""
    pred = f.prediction
    gt = q.ground_truth
    qtype = q.question_type

    if qtype in (QuestionType.BINARY, QuestionType.MCQ):
        accuracy = calculate_accuracy(
            pred,
            gt,
            qtype,
            question_text="",
            options=q.options,
        )
        brier = calculate_brier_score(
            pred,
            gt,
            f.confidence,
            qtype,
            options=q.options,
        )
        log_score = calculate_log_score(
            pred,
            gt,
            f.confidence,
            qtype,
            options=q.options,
        )
        return accuracy == 1.0, brier, log_score

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
        return str(pred) == str(gt), None, None

    return None, None, None


def _pct(v):
    return f"{v:.1%}" if v is not None else "—"


def _f(v, decimals=3):
    return f"{v:.{decimals}f}" if v is not None else "—"


def compute_results(forecast_list: list, q_map: dict):
    """Aggregate scores per model × question type. Returns (results_dict, skipped_count)."""
    results = defaultdict(lambda: defaultdict(lambda: {
        "correct": 0, "total": 0, "brier": [], "log_score": [], "details": []
    }))
    skipped = 0
    for f in forecast_list:
        q = q_map.get(f.question_id)
        if q is None or q.ground_truth is None:
            skipped += 1
            continue
        is_correct, brier, log_score = score_forecast(f, q)
        if is_correct is None:
            skipped += 1
            continue
        bucket = results[f.model_name or "unknown"][q.question_type.value]
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
    return results, skipped


def build_output_stats(results_dict: dict, target_dict: dict):
    """Populate target_dict['by_model'] and target_dict['overall'] from results_dict."""
    all_correct, all_total, all_brier, all_log = 0, 0, [], []
    for model, by_type in sorted(results_dict.items()):
        model_correct, model_total, model_brier, model_log = 0, 0, [], []
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
        target_dict["by_model"][model] = {
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
    target_dict["overall"] = {
        "correct": all_correct,
        "total": all_total,
        "accuracy": round(all_correct / all_total, 4) if all_total else 0,
        "avg_brier_score": round(statistics.mean(all_brier), 4) if all_brier else None,
        "avg_log_score": round(statistics.mean(all_log), 4) if all_log else None,
    }


def write_markdown(output: dict, path: Path) -> None:
    condition = output["condition"]
    lines = [
        f"# Benchmark Evaluation — {condition}",
        "",
        f"**Database:** `{output['db']}`  ",
        f"**Generated:** {output['generated_at']}  ",
        f"**Total forecasts:** {output['total_forecasts']}  |  "
        f"**Contamination-excluded:** {output.get('contaminated_excluded', 0)}  |  "
        f"**Skipped:** {output['skipped']}",
        "",
    ]

    def _model_table(out_dict, heading):
        sec = []
        ov = out_dict["overall"]
        sec += [
            f"## {heading}",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Accuracy | {_pct(ov['accuracy'])} ({ov['correct']}/{ov['total']}) |",
            f"| Mean Brier Score | {_f(ov['avg_brier_score'])} |",
            f"| Mean Log Score | {_f(ov['avg_log_score'])} |",
            "",
            "### By Model",
            "",
            "| Model | Accuracy | Brier | Log Score | n |",
            "|---|---|---|---|---|",
        ]
        for model, stats in sorted(out_dict["by_model"].items(), key=lambda x: -x[1]["accuracy"]):
            short = model.split("/")[-1]
            sec.append(
                f"| {short} | {_pct(stats['accuracy'])} | {_f(stats['avg_brier_score'])} "
                f"| {_f(stats['avg_log_score'])} | {stats['total']} |"
            )
        sec.append("")

        qtypes = ["binary", "mcq", "quantity", "timeframe"]
        header = "| Model | " + " | ".join(f"{qt.capitalize()} Acc" for qt in qtypes) + " | Total Acc |"
        sep = "| --- |" + "".join([" --- |"] * (len(qtypes) + 1))
        sec += ["### By Model × Question Type", "", header, sep]
        for model, stats in sorted(out_dict["by_model"].items(), key=lambda x: -x[1]["accuracy"]):
            short = model.split("/")[-1]
            cells = []
            for qt in qtypes:
                ts = stats["by_question_type"].get(qt)
                cells.append(f"{_pct(ts['accuracy'])} ({ts['correct']}/{ts['total']})" if ts else "—")
            cells.append(_pct(stats["accuracy"]))
            sec.append(f"| {short} | " + " | ".join(cells) + " |")
        sec.append("")

        brier_qtypes = ["binary", "mcq"]
        header = "| Model | " + " | ".join(f"{qt.capitalize()} Brier" for qt in brier_qtypes) + " | Overall Brier |"
        sep = "| --- |" + "".join([" --- |"] * (len(brier_qtypes) + 1))
        sec += ["### Brier Score by Model × Question Type", "", header, sep]
        for model, stats in sorted(out_dict["by_model"].items(), key=lambda x: x[1].get("avg_brier_score") or 1):
            short = model.split("/")[-1]
            cells = []
            for qt in brier_qtypes:
                ts = stats["by_question_type"].get(qt)
                cells.append(_f(ts["avg_brier_score"]) if ts and ts["avg_brier_score"] is not None else "—")
            cells.append(_f(stats["avg_brier_score"]))
            sec.append(f"| {short} | " + " | ".join(cells) + " |")
        sec.append("")
        return sec

    lines += _model_table(output, "All Forecasts")

    clean = output.get("clean", {})
    if clean and clean.get("overall"):
        lines += _model_table(clean, "Contamination-Filtered")

        ov_all = output["overall"]
        ov_clean = clean["overall"]
        lines += [
            "## Contamination Filter Summary",
            "",
            "Questions where `estimated_start_time < model knowledge cutoff` are excluded from the filtered set.",
            "",
            "| | All | Filtered |",
            "| --- | --- | --- |",
            f"| n | {ov_all['total']} | {ov_clean['total']} |",
            f"| Accuracy | {_pct(ov_all['accuracy'])} | {_pct(ov_clean['accuracy'])} |",
            f"| Brier | {_f(ov_all['avg_brier_score'])} | {_f(ov_clean['avg_brier_score'])} |",
            f"| Log Score | {_f(ov_all['avg_log_score'])} | {_f(ov_clean['avg_log_score'])} |",
            "",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")


def print_summary(label: str, out_dict: dict):
    ov = out_dict["overall"]
    print(f"\n{'='*60}")
    print(label)
    print(f"{'='*60}")
    print(f"Total scored: {ov['total']}  |  Skipped: {out_dict['skipped']}")
    if ov["total"]:
        print(f"Overall accuracy: {ov['correct']}/{ov['total']} = {ov['accuracy']:.1%}")
    if ov["avg_brier_score"] is not None:
        print(f"Mean Brier (binary+mcq): {ov['avg_brier_score']:.3f}")
    if ov["avg_log_score"] is not None:
        print(f"Mean Log Score:          {ov['avg_log_score']:.3f}")
    print()
    for model, stats in out_dict["by_model"].items():
        print(f"  {model}")
        print(f"    accuracy={stats['accuracy']:.1%}  brier={stats['avg_brier_score']}  log={stats['avg_log_score']}  n={stats['total']}")
        for qtype, ts_stats in stats["by_question_type"].items():
            line = f"      {qtype:12s}: {ts_stats['correct']}/{ts_stats['total']} = {ts_stats['accuracy']:.1%}"
            if ts_stats["avg_brier_score"] is not None:
                line += f"  brier={ts_stats['avg_brier_score']}"
            print(line)
        print()


def evaluate_condition(condition: str, all_forecasts: list, q_map: dict, db_path: str) -> dict:
    """Evaluate all forecasts for a single benchmark condition. Returns the output dict."""
    raw = [f for f in all_forecasts if (f.evaluation_metadata or {}).get("benchmark_condition") == condition]
    print(f"\n[{condition}] raw forecasts: {len(raw)}")

    # Deduplicate: keep latest per (model, question)
    latest: dict = {}
    for f in raw:
        key = (f.model_name, f.question_id)
        if key not in latest or f.timestamp > latest[key].timestamp:
            latest[key] = f
    deduped = list(latest.values())
    dropped = len(raw) - len(deduped)
    if dropped:
        print(f"[{condition}] Deduplicated: dropped {dropped} older duplicates")
    print(f"[{condition}] deduplicated: {len(deduped)}")

    # Contamination filter
    contaminated: set = set()
    for f in deduped:
        q = q_map.get(f.question_id)
        if not q or not q.estimated_start_time:
            continue
        cutoff_str = get_knowledge_cutoff_date(f.model_name)
        if not cutoff_str or cutoff_str == "Unknown":
            continue
        try:
            cutoff_dt = datetime.fromisoformat(cutoff_str).replace(tzinfo=timezone.utc)
            if q.estimated_start_time < cutoff_dt:
                contaminated.add((f.model_name, f.question_id))
        except ValueError:
            continue

    clean = [f for f in deduped if (f.model_name, f.question_id) not in contaminated]
    n_contaminated = len(deduped) - len(clean)
    print(f"[{condition}] contamination-excluded: {n_contaminated}  |  clean: {len(clean)}")

    results, skipped = compute_results(deduped, q_map)
    results_clean, skipped_clean = compute_results(clean, q_map)
    print(f"[{condition}] skipped (no ground truth): {skipped}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": db_path,
        "condition": condition,
        "total_forecasts": len(deduped),
        "contaminated_excluded": n_contaminated,
        "skipped": skipped,
        "by_model": {},
        "overall": {},
        "clean": {
            "total_forecasts": len(clean),
            "skipped": skipped_clean,
            "by_model": {},
            "overall": {},
        },
    }
    build_output_stats(results, output)
    build_output_stats(results_clean, output["clean"])
    return output


def main():
    parser = argparse.ArgumentParser(description="Evaluate benchmark forecasts")
    parser.add_argument("--db", default=DB_PATH, help="Database path")
    parser.add_argument(
        "--condition", nargs="*", default=None,
        metavar="CONDITION",
        help=f"Condition(s) to evaluate (default: all with data). Choices: {ALL_CONDITIONS}",
    )
    args = parser.parse_args()

    db = GenericDatabase(args.db)
    all_forecasts = db.get_many(Forecast, filters={})
    all_questions = db.get_many(Question, filters={})
    q_map = {q.id: q for q in all_questions}

    # Determine which conditions to evaluate
    if args.condition:
        conditions = args.condition
    else:
        # Auto-detect: any condition that has at least one labeled forecast
        present = {(f.evaluation_metadata or {}).get("benchmark_condition") for f in all_forecasts}
        conditions = [c for c in ALL_CONDITIONS if c in present]
        print(f"Auto-detected conditions with data: {conditions}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for condition in conditions:
        output = evaluate_condition(condition, all_forecasts, q_map, args.db)

        json_path = OUTPUT_DIR / f"{condition}_eval_{ts}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False)
        print(f"Saved to {json_path}")

        md_path = OUTPUT_DIR / f"{condition}_eval_{ts}.md"
        write_markdown(output, md_path)
        print(f"Saved to {md_path}")

        print_summary(f"{condition.upper()} (all) — {args.db}", output)
        if output["clean"]["overall"].get("total"):
            print_summary(f"{condition.upper()} (contamination-filtered) — {args.db}", output["clean"])


if __name__ == "__main__":
    main()
