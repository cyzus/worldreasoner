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
OUTPUT_DIR = Path("experiments/evaluation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
    lines.append(f"**Total forecasts:** {output['total_forecasts']}  |  **Contamination-excluded:** {output.get('contaminated_excluded', 0)}  |  **Skipped:** {output['skipped']}")
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
    sep = "| --- |" + "".join([" --- |"] * (len(qtypes) + 1))
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
    sep = "| --- |" + "".join([" --- |"] * (len(brier_qtypes) + 1))
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

    # Contamination-filtered comparison
    clean = output.get("clean", {})
    if clean and clean.get("overall"):
        ov_all = output["overall"]
        ov_clean = clean["overall"]
        lines.append("## Contamination Filter Comparison")
        lines.append("")
        lines.append(f"Questions where `estimated_start_time < model knowledge cutoff` are excluded from the clean set.")
        lines.append("")
        lines.append("| | All | Clean (filtered) |")
        lines.append("| --- | --- | --- |")
        lines.append(f"| n | {ov_all['total']} | {ov_clean['total']} |")
        lines.append(f"| Accuracy | {_pct(ov_all['accuracy'])} | {_pct(ov_clean['accuracy'])} |")
        lines.append(f"| Brier | {_f(ov_all['avg_brier_score'])} | {_f(ov_clean['avg_brier_score'])} |")
        lines.append(f"| Log Score | {_f(ov_all['avg_log_score'])} | {_f(ov_clean['avg_log_score'])} |")
        lines.append("")

        lines.append("### Clean — By Model")
        lines.append("")
        lines.append("| Model | Accuracy | Brier | Log Score | n |")
        lines.append("|---|---|---|---|---|")
        for model, stats in sorted(clean["by_model"].items(), key=lambda x: -x[1]["accuracy"]):
            short = model.split("/")[-1]
            lines.append(
                f"| {short} | {_pct(stats['accuracy'])} | {_f(stats['avg_brier_score'])} "
                f"| {_f(stats['avg_log_score'])} | {stats['total']} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    db = GenericDatabase(DB_PATH)
    all_forecasts = db.get_many(Forecast, filters={})
    all_questions = db.get_many(Question, filters={})
    q_map = {q.id: q for q in all_questions}

    vanilla_all = [
        f for f in all_forecasts
        if (f.evaluation_metadata or {}).get("benchmark_condition") == "vanilla_llm"
    ]
    print(f"vanilla_llm forecasts (raw): {len(vanilla_all)}")

    # Deduplicate: keep only the latest forecast per (model, question)
    latest: dict = {}
    for f in vanilla_all:
        key = (f.model_name, f.question_id)
        if key not in latest or f.timestamp > latest[key].timestamp:
            latest[key] = f
    vanilla = list(latest.values())
    duplicates = len(vanilla_all) - len(vanilla)
    if duplicates:
        print(f"Deduplicated: dropped {duplicates} older forecasts for same (model, question)")
    print(f"vanilla_llm forecasts (deduplicated): {len(vanilla)}")

    # Contamination filter: exclude questions that started before model's knowledge cutoff
    from src.core.llm import get_knowledge_cutoff_date
    from datetime import datetime, timezone

    contaminated_ids: set = set()
    for f in vanilla:
        q = q_map.get(f.question_id)
        if not q or not q.estimated_start_time:
            continue
        cutoff_str = get_knowledge_cutoff_date(f.model_name)
        if not cutoff_str or cutoff_str == "Unknown":
            continue
        try:
            cutoff_dt = datetime.fromisoformat(cutoff_str).replace(tzinfo=timezone.utc)
            if q.estimated_start_time < cutoff_dt:
                contaminated_ids.add((f.model_name, f.question_id))
        except ValueError:
            continue

    vanilla_clean = [f for f in vanilla if (f.model_name, f.question_id) not in contaminated_ids]
    print(f"Contamination-filtered (question started before model cutoff): {len(vanilla) - len(vanilla_clean)}")
    print(f"vanilla_llm forecasts (clean): {len(vanilla_clean)}")

    def compute_results(forecast_list):
        results = defaultdict(lambda: defaultdict(lambda: {
            "correct": 0, "total": 0, "brier": [], "log_score": [], "details": []
        }))
        skipped = 0
        for f in forecast_list:
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
        return results, skipped

    # Per-model, per-type breakdown
    results, skipped = compute_results(vanilla)
    results_clean, skipped_clean = compute_results(vanilla_clean)

    print(f"Skipped (no ground truth or unscored): {skipped} / clean: {skipped_clean}")

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": DB_PATH,
        "condition": "vanilla_llm",
        "total_forecasts": len(vanilla),
        "contaminated_excluded": len(vanilla) - len(vanilla_clean),
        "skipped": skipped,
        "by_model": {},
        "clean": {
            "total_forecasts": len(vanilla_clean),
            "skipped": skipped_clean,
            "by_model": {},
        },
    }

    def build_output_stats(results_dict, target_dict):
        all_correct, all_total, all_brier, all_log = 0, 0, [], []
        for model, by_type in sorted(results_dict.items()):
            model_correct, model_total, model_brier, model_log = 0, 0, [], {}
            model_by_type = {}
            model_log = []
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
        return all_correct, all_total, all_brier, all_log

    all_correct, all_total, all_brier, all_log = build_output_stats(results, output)
    build_output_stats(results_clean, output["clean"])

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
    def print_summary(label, out_dict):
        ov = out_dict["overall"]
        print(f"\n{'='*60}")
        print(f"{label}")
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
                print(f"      {qtype:12s}: {ts_stats['correct']}/{ts_stats['total']} = {ts_stats['accuracy']:.1%}", end="")
                if ts_stats["avg_brier_score"] is not None:
                    print(f"  brier={ts_stats['avg_brier_score']}", end="")
                print()
            print()

    print_summary(f"VANILLA LLM EVALUATION (all) — {DB_PATH}", output)
    print_summary(f"VANILLA LLM EVALUATION (contamination-filtered) — {DB_PATH}", output["clean"])


if __name__ == "__main__":
    main()
