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


def _metric_delta(filtered_value, all_value):
    if filtered_value is None or all_value is None:
        return None
    return filtered_value - all_value


def _short_condition(condition: str) -> str:
    labels = {
        "vanilla_llm": "Vanilla LLM",
        "structured_scenario": "Causal Simulation",
        "search_enabled": "Search-Enabled",
        "worldreasoner": "WorldReasoner",
        "oracle": "Near-Resolution",
        "real_time": "Real-Time",
    }
    return labels.get(condition, condition)


def _comparison_rows(outputs: list[dict]) -> list[dict]:
    """Build side-by-side all-vs-filtered rows for condition/model tables."""
    rows = []
    for output in outputs:
        condition = output["condition"]
        clean = output.get("clean", {})

        def add_row(model: str, all_stats: dict, clean_stats: dict):
            all_n = all_stats.get("total", 0)
            clean_n = clean_stats.get("total", 0)
            rows.append({
                "condition": condition,
                "condition_label": _short_condition(condition),
                "model": model,
                "all_n": all_n,
                "all_accuracy": all_stats.get("accuracy"),
                "all_brier": all_stats.get("avg_brier_score"),
                "all_log_score": all_stats.get("avg_log_score"),
                "filtered_n": clean_n,
                "filtered_accuracy": clean_stats.get("accuracy"),
                "filtered_brier": clean_stats.get("avg_brier_score"),
                "filtered_log_score": clean_stats.get("avg_log_score"),
                "excluded_n": max(all_n - clean_n, 0),
                "accuracy_delta": _metric_delta(
                    clean_stats.get("accuracy"), all_stats.get("accuracy")
                ),
                "brier_delta": _metric_delta(
                    clean_stats.get("avg_brier_score"),
                    all_stats.get("avg_brier_score"),
                ),
                "log_score_delta": _metric_delta(
                    clean_stats.get("avg_log_score"),
                    all_stats.get("avg_log_score"),
                ),
            })

        add_row("__overall__", output.get("overall", {}), clean.get("overall", {}))

        all_models = output.get("by_model", {})
        clean_models = clean.get("by_model", {})
        for model in sorted(all_models):
            add_row(model, all_models[model], clean_models.get(model, {}))

    return rows


def write_comparison_tsv(rows: list[dict], path: Path) -> None:
    columns = [
        "condition",
        "model",
        "all_n",
        "all_accuracy",
        "all_brier",
        "all_log_score",
        "filtered_n",
        "filtered_accuracy",
        "filtered_brier",
        "filtered_log_score",
        "excluded_n",
        "accuracy_delta",
        "brier_delta",
        "log_score_delta",
    ]
    lines = ["\t".join(columns)]
    for row in rows:
        vals = []
        for col in columns:
            val = row.get(col)
            vals.append("" if val is None else str(val))
        lines.append("\t".join(vals))
    path.write_text("\n".join(lines), encoding="utf-8")


def write_comparison_markdown(rows: list[dict], path: Path) -> None:
    overall = [r for r in rows if r["model"] == "__overall__"]
    by_model = [r for r in rows if r["model"] != "__overall__"]

    lines = [
        "# Contamination Filter Comparison",
        "",
        "The filtered setting excludes model-question pairs where "
        "`question.estimated_start_time < model knowledge cutoff`. "
        "This is a conservative diagnostic for possible training-data leakage; "
        "the Temporal Gateway still enforces evidence access by simulated date during the run.",
        "",
        "## By Condition",
        "",
        "| Condition | All n | All Acc | All Brier | Filtered n | Filtered Acc | Filtered Brier | Excluded | Acc Delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in overall:
        lines.append(
            f"| {row['condition_label']} | {row['all_n']} | {_pct(row['all_accuracy'])} "
            f"| {_f(row['all_brier'])} | {row['filtered_n']} | "
            f"{_pct(row['filtered_accuracy'])} | {_f(row['filtered_brier'])} "
            f"| {row['excluded_n']} | {_pct(row['accuracy_delta'])} |"
        )

    lines += [
        "",
        "## By Condition and Model",
        "",
        "| Condition | Model | All n | All Acc | All Brier | Filtered n | Filtered Acc | Filtered Brier | Excluded | Acc Delta |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(by_model, key=lambda r: (r["condition"], r["model"])):
        model = row["model"].split("/")[-1]
        lines.append(
            f"| {row['condition_label']} | {model} | {row['all_n']} | "
            f"{_pct(row['all_accuracy'])} | {_f(row['all_brier'])} | "
            f"{row['filtered_n']} | {_pct(row['filtered_accuracy'])} | "
            f"{_f(row['filtered_brier'])} | {row['excluded_n']} | "
            f"{_pct(row['accuracy_delta'])} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def _combine_weighted(rows: list[dict], group_key: str) -> list[dict]:
    grouped = defaultdict(lambda: {
        "all_correct": 0.0,
        "all_total": 0,
        "filtered_correct": 0.0,
        "filtered_total": 0,
        "all_brier_sum": 0.0,
        "all_brier_n": 0,
        "filtered_brier_sum": 0.0,
        "filtered_brier_n": 0,
        "excluded_n": 0,
        "conditions": set(),
    })
    for row in rows:
        if row["model"] == "__overall__":
            continue
        group = grouped[row[group_key]]
        group["conditions"].add(row["condition"])
        group["all_total"] += row["all_n"]
        group["filtered_total"] += row["filtered_n"]
        group["excluded_n"] += row["excluded_n"]
        if row["all_accuracy"] is not None:
            group["all_correct"] += row["all_accuracy"] * row["all_n"]
        if row["filtered_accuracy"] is not None:
            group["filtered_correct"] += row["filtered_accuracy"] * row["filtered_n"]
        if row["all_brier"] is not None:
            group["all_brier_sum"] += row["all_brier"] * row["all_n"]
            group["all_brier_n"] += row["all_n"]
        if row["filtered_brier"] is not None:
            group["filtered_brier_sum"] += row["filtered_brier"] * row["filtered_n"]
            group["filtered_brier_n"] += row["filtered_n"]

    combined = []
    for key, stats in grouped.items():
        all_n = stats["all_total"]
        filtered_n = stats["filtered_total"]
        all_acc = stats["all_correct"] / all_n if all_n else None
        filtered_acc = (
            stats["filtered_correct"] / filtered_n if filtered_n else None
        )
        all_brier = (
            stats["all_brier_sum"] / stats["all_brier_n"]
            if stats["all_brier_n"]
            else None
        )
        filtered_brier = (
            stats["filtered_brier_sum"] / stats["filtered_brier_n"]
            if stats["filtered_brier_n"]
            else None
        )
        combined.append({
            group_key: key,
            "all_n": all_n,
            "all_accuracy": all_acc,
            "all_brier": all_brier,
            "filtered_n": filtered_n,
            "filtered_accuracy": filtered_acc,
            "filtered_brier": filtered_brier,
            "excluded_n": stats["excluded_n"],
            "excluded_share": stats["excluded_n"] / all_n if all_n else None,
            "accuracy_delta": _metric_delta(filtered_acc, all_acc),
            "brier_delta": _metric_delta(filtered_brier, all_brier),
            "condition_count": len(stats["conditions"]),
        })
    return combined


def write_model_leakage_markdown(rows: list[dict], path: Path) -> None:
    model_rows = _combine_weighted(rows, "model")
    model_rows.sort(
        key=lambda r: (
            -(r["excluded_share"] or 0),
            r["accuracy_delta"] or 0,
            r["model"],
        )
    )

    lines = [
        "# Model-Level Contamination Filter Comparison",
        "",
        "This table aggregates each model across all evaluated conditions. "
        "A high excluded share means more model-question pairs started before the model's knowledge cutoff. "
        "A negative accuracy delta means the model performs worse after those pairs are removed.",
        "",
        "| Model | Conditions | All n | Filtered n | Excluded | Excluded Share | All Acc | Filtered Acc | Acc Delta | All Brier | Filtered Brier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in model_rows:
        model = row["model"]
        lines.append(
            f"| {model} | {row['condition_count']} | {row['all_n']} | "
            f"{row['filtered_n']} | {row['excluded_n']} | "
            f"{_pct(row['excluded_share'])} | {_pct(row['all_accuracy'])} | "
            f"{_pct(row['filtered_accuracy'])} | {_pct(row['accuracy_delta'])} | "
            f"{_f(row['all_brier'])} | {_f(row['filtered_brier'])} |"
        )
    lines += [
        "",
        "## Reading Guide",
        "",
        "- `Excluded Share` is the fraction of model-question pairs removed by the knowledge-cutoff filter.",
        "- `Acc Delta` is `Filtered Acc - All Acc`; negative values indicate that the unfiltered score was higher.",
        "- For models with proxy or unknown cutoffs, interpret the filtered result as diagnostic rather than definitive.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_model_leakage_svg(rows: list[dict], path: Path) -> None:
    model_rows = _combine_weighted(rows, "model")
    if not model_rows:
        return
    model_rows.sort(key=lambda r: r["all_accuracy"] or 0, reverse=True)

    width = 1060
    row_h = 52
    top = 64
    left = 260
    chart_w = 570
    height = top + row_h * len(model_rows) + 70

    def x_for(v):
        return left + max(0.0, min(1.0, v or 0.0)) * chart_w

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="700">Model-level all vs. contamination-filtered accuracy</text>',
        '<text x="24" y="52" font-family="Arial, sans-serif" font-size="12" fill="#555">Dot size reflects the share of model-question pairs excluded by the knowledge-cutoff filter.</text>',
    ]

    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x_for(tick)
        parts.append(f'<line x1="{x:.1f}" y1="{top-10}" x2="{x:.1f}" y2="{height-52}" stroke="#dddddd" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-30}" font-family="Arial, sans-serif" font-size="11" text-anchor="middle" fill="#666">{int(tick*100)}%</text>')

    for i, row in enumerate(model_rows):
        y = top + i * row_h
        all_x = x_for(row["all_accuracy"])
        filt_x = x_for(row["filtered_accuracy"])
        radius = 4 + 13 * (row["excluded_share"] or 0)
        model = row["model"]
        parts.append(f'<text x="24" y="{y+25}" font-family="Arial, sans-serif" font-size="13" font-weight="600">{model}</text>')
        parts.append(f'<line x1="{all_x:.1f}" y1="{y+18}" x2="{filt_x:.1f}" y2="{y+18}" stroke="#777" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{all_x:.1f}" cy="{y+18}" r="5" fill="#b7d7ea" stroke="#6f9db5"/>')
        parts.append(f'<circle cx="{filt_x:.1f}" cy="{y+18}" r="{radius:.1f}" fill="#d9efd2" fill-opacity="0.85" stroke="#7aa66f"/>')
        parts.append(f'<text x="{max(all_x, filt_x)+18:.1f}" y="{y+22}" font-family="Arial, sans-serif" font-size="11" fill="#333">{_pct(row["all_accuracy"])} -> {_pct(row["filtered_accuracy"])} ({_pct(row["accuracy_delta"])})</text>')
        parts.append(f'<text x="{width-130}" y="{y+22}" font-family="Arial, sans-serif" font-size="11" fill="#666">excluded {_pct(row["excluded_share"])}</text>')

    legend_y = height - 12
    parts.append(f'<circle cx="{left}" cy="{legend_y-4}" r="5" fill="#b7d7ea" stroke="#6f9db5"/>')
    parts.append(f'<text x="{left+14}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">All</text>')
    parts.append(f'<circle cx="{left+70}" cy="{legend_y-4}" r="8" fill="#d9efd2" stroke="#7aa66f"/>')
    parts.append(f'<text x="{left+84}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">Filtered; larger circle = more excluded pairs</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_vanilla_leakage_markdown(rows: list[dict], path: Path) -> None:
    vanilla_rows = [
        r for r in rows
        if r["condition"] == "vanilla_llm" and r["model"] != "__overall__"
    ]
    vanilla_rows.sort(
        key=lambda r: (
            -(r["excluded_n"] / r["all_n"] if r["all_n"] else 0),
            r["accuracy_delta"] or 0,
            r["model"],
        )
    )

    lines = [
        "# Vanilla-Only Contamination Diagnostic",
        "",
        "This table uses only the `Vanilla LLM` condition, where models have no search or tool access. "
        "This is the cleanest diagnostic for whether newer training cutoffs may inflate performance through parametric knowledge.",
        "",
        "| Model | All n | Filtered n | Excluded | Excluded Share | All Acc | Filtered Acc | Acc Delta | All Brier | Filtered Brier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in vanilla_rows:
        excluded_share = row["excluded_n"] / row["all_n"] if row["all_n"] else None
        lines.append(
            f"| {row['model']} | {row['all_n']} | {row['filtered_n']} | "
            f"{row['excluded_n']} | {_pct(excluded_share)} | "
            f"{_pct(row['all_accuracy'])} | {_pct(row['filtered_accuracy'])} | "
            f"{_pct(row['accuracy_delta'])} | {_f(row['all_brier'])} | "
            f"{_f(row['filtered_brier'])} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "- Prefer this table over the all-condition contamination table when discussing knowledge leakage.",
        "- A large negative `Acc Delta` means the model's unfiltered Vanilla score is substantially higher than its leakage-filtered score.",
        "- Models with unknown or proxy cutoffs should be treated as diagnostic rather than definitive.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_vanilla_leakage_svg(rows: list[dict], path: Path) -> None:
    vanilla_rows = [
        r for r in rows
        if r["condition"] == "vanilla_llm" and r["model"] != "__overall__"
    ]
    if not vanilla_rows:
        return
    vanilla_rows.sort(key=lambda r: r["all_accuracy"] or 0, reverse=True)

    width = 1100
    row_h = 52
    top = 64
    left = 300
    chart_w = 560
    height = top + row_h * len(vanilla_rows) + 70

    def x_for(v):
        return left + max(0.0, min(1.0, v or 0.0)) * chart_w

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="700">Vanilla-only contamination diagnostic</text>',
        '<text x="24" y="52" font-family="Arial, sans-serif" font-size="12" fill="#555">No search/tools: all vs. knowledge-cutoff-filtered accuracy by model.</text>',
    ]
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x_for(tick)
        parts.append(f'<line x1="{x:.1f}" y1="{top-10}" x2="{x:.1f}" y2="{height-52}" stroke="#dddddd" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-30}" font-family="Arial, sans-serif" font-size="11" text-anchor="middle" fill="#666">{int(tick*100)}%</text>')

    for i, row in enumerate(vanilla_rows):
        y = top + i * row_h
        all_x = x_for(row["all_accuracy"])
        filt_x = x_for(row["filtered_accuracy"])
        excluded_share = row["excluded_n"] / row["all_n"] if row["all_n"] else 0
        radius = 4 + 13 * excluded_share
        parts.append(f'<text x="24" y="{y+25}" font-family="Arial, sans-serif" font-size="12" font-weight="600">{row["model"]}</text>')
        parts.append(f'<line x1="{all_x:.1f}" y1="{y+18}" x2="{filt_x:.1f}" y2="{y+18}" stroke="#777" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{all_x:.1f}" cy="{y+18}" r="5" fill="#b7d7ea" stroke="#6f9db5"/>')
        parts.append(f'<circle cx="{filt_x:.1f}" cy="{y+18}" r="{radius:.1f}" fill="#d9efd2" fill-opacity="0.85" stroke="#7aa66f"/>')
        parts.append(f'<text x="{max(all_x, filt_x)+18:.1f}" y="{y+22}" font-family="Arial, sans-serif" font-size="11" fill="#333">{_pct(row["all_accuracy"])} -> {_pct(row["filtered_accuracy"])} ({_pct(row["accuracy_delta"])})</text>')
        parts.append(f'<text x="{width-135}" y="{y+22}" font-family="Arial, sans-serif" font-size="11" fill="#666">excluded {_pct(excluded_share)}</text>')

    legend_y = height - 12
    parts.append(f'<circle cx="{left}" cy="{legend_y-4}" r="5" fill="#b7d7ea" stroke="#6f9db5"/>')
    parts.append(f'<text x="{left+14}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">All</text>')
    parts.append(f'<circle cx="{left+70}" cy="{legend_y-4}" r="8" fill="#d9efd2" stroke="#7aa66f"/>')
    parts.append(f'<text x="{left+84}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">Filtered; larger circle = more excluded pairs</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _latest_condition_rows(outputs: list[dict]) -> list[dict]:
    rows = []
    for output in outputs:
        ov = output["overall"]
        clean = output.get("clean", {}).get("overall", {})
        rows.append({
            "condition": output["condition"],
            "condition_label": _short_condition(output["condition"]),
            "all_n": ov.get("total", 0),
            "all_accuracy": ov.get("accuracy"),
            "all_brier": ov.get("avg_brier_score"),
            "all_log_score": ov.get("avg_log_score"),
            "filtered_n": clean.get("total", 0),
            "filtered_accuracy": clean.get("accuracy"),
            "filtered_brier": clean.get("avg_brier_score"),
            "filtered_log_score": clean.get("avg_log_score"),
            "excluded_n": max(ov.get("total", 0) - clean.get("total", 0), 0),
        })
    return rows


def write_latest_summary(outputs: list[dict], rows: list[dict], path: Path) -> None:
    condition_rows = _latest_condition_rows(outputs)
    vanilla_rows = [
        r for r in rows
        if r["condition"] == "vanilla_llm" and r["model"] != "__overall__"
    ]
    vanilla_rows.sort(key=lambda r: r["accuracy_delta"] or 0)

    lines = [
        "# Latest Evaluation Summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## What To Use",
        "",
        "- Main result table: use `All Acc`, `Brier`, and `Log Score` by condition/model from the condition eval files.",
        "- Knowledge leakage diagnostic: use the Vanilla-only contamination table, not the all-condition aggregate.",
        "- Filtered numbers are diagnostic; the benchmark's hard access control is still the simulated-date Temporal Gateway.",
        "",
        "## Condition-Level Forecast Results",
        "",
        "| Condition | All n | All Acc | Brier | Log Score | Filtered n | Filtered Acc | Filtered Brier | Excluded |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in condition_rows:
        lines.append(
            f"| {row['condition_label']} | {row['all_n']} | "
            f"{_pct(row['all_accuracy'])} | {_f(row['all_brier'])} | "
            f"{_f(row['all_log_score'])} | {row['filtered_n']} | "
            f"{_pct(row['filtered_accuracy'])} | {_f(row['filtered_brier'])} | "
            f"{row['excluded_n']} |"
        )

    lines += [
        "",
        "## Vanilla-Only Knowledge Leakage Diagnostic",
        "",
        "| Model | All n | Filtered n | Excluded Share | All Acc | Filtered Acc | Acc Delta |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in vanilla_rows:
        excluded_share = row["excluded_n"] / row["all_n"] if row["all_n"] else None
        lines.append(
            f"| {row['model']} | {row['all_n']} | {row['filtered_n']} | "
            f"{_pct(excluded_share)} | {_pct(row['all_accuracy'])} | "
            f"{_pct(row['filtered_accuracy'])} | {_pct(row['accuracy_delta'])} |"
        )

    incomplete = []
    for output in outputs:
        for model, stats in output.get("by_model", {}).items():
            n = stats.get("total", 0)
            if n < 100:
                incomplete.append((output["condition"], model, n))

    lines += [
        "",
        "## Still Missing Or Needs Caution",
        "",
        "- Final reasoning/graph evaluation still needs to be refreshed after the final forecast rows are frozen.",
        "- Qwen3-235B-A22B-Instruct-2507 uses a conservative release-date proxy cutoff; interpret filtered scores as diagnostic.",
        "- Qwen3.5 currently has no cutoff entry, so it excludes 0 pairs under the contamination filter.",
    ]
    if incomplete:
        lines += [
            "- Some model-condition cells have fewer than 100 forecasts and should not be treated as final:",
            "",
            "| Condition | Model | n |",
            "|---|---|---:|",
        ]
        for condition, model, n in sorted(incomplete):
            lines.append(f"| {_short_condition(condition)} | {model} | {n} |")

    lines += [
        "",
        "## Generated Files",
        "",
        "- `contamination_vanilla_only_<timestamp>.md/svg`: clean leakage diagnostic.",
        "- `contamination_comparison_<timestamp>.md/tsv/svg`: all-condition diagnostic.",
        "- `<condition>_eval_<timestamp>.md/json`: condition-level detailed reports.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_comparison_svg(rows: list[dict], path: Path) -> None:
    """Write a dependency-free paired bar chart for overall condition accuracy."""
    overall = [r for r in rows if r["model"] == "__overall__"]
    if not overall:
        return

    width = 920
    row_h = 54
    top = 60
    left = 190
    chart_w = 620
    height = top + row_h * len(overall) + 55

    def x_for(v):
        return left + max(0.0, min(1.0, v or 0.0)) * chart_w

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="700">All vs. contamination-filtered accuracy</text>',
        '<text x="24" y="52" font-family="Arial, sans-serif" font-size="12" fill="#555">Filtered excludes question/model pairs whose start date predates the model knowledge cutoff.</text>',
    ]

    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x_for(tick)
        parts.append(f'<line x1="{x:.1f}" y1="{top-10}" x2="{x:.1f}" y2="{height-45}" stroke="#dddddd" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-25}" font-family="Arial, sans-serif" font-size="11" text-anchor="middle" fill="#666">{int(tick*100)}%</text>')

    for i, row in enumerate(overall):
        y = top + i * row_h
        all_x = x_for(row["all_accuracy"])
        filt_x = x_for(row["filtered_accuracy"])
        parts.append(f'<text x="24" y="{y+24}" font-family="Arial, sans-serif" font-size="13" font-weight="600">{row["condition_label"]}</text>')
        parts.append(f'<rect x="{left}" y="{y+8}" width="{max(all_x-left, 0):.1f}" height="14" fill="#b7d7ea" stroke="#6f9db5"/>')
        parts.append(f'<rect x="{left}" y="{y+28}" width="{max(filt_x-left, 0):.1f}" height="14" fill="#d9efd2" stroke="#8ab37e"/>')
        parts.append(f'<text x="{all_x+6:.1f}" y="{y+20}" font-family="Arial, sans-serif" font-size="11" fill="#333">{_pct(row["all_accuracy"])}</text>')
        parts.append(f'<text x="{filt_x+6:.1f}" y="{y+40}" font-family="Arial, sans-serif" font-size="11" fill="#333">{_pct(row["filtered_accuracy"])}</text>')
    legend_y = height - 10
    parts.append(f'<rect x="{left}" y="{legend_y-10}" width="14" height="10" fill="#b7d7ea" stroke="#6f9db5"/>')
    parts.append(f'<text x="{left+20}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">All</text>')
    parts.append(f'<rect x="{left+70}" y="{legend_y-10}" width="14" height="10" fill="#d9efd2" stroke="#8ab37e"/>')
    parts.append(f'<text x="{left+90}" y="{legend_y}" font-family="Arial, sans-serif" font-size="12" fill="#444">Filtered</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


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

    outputs = []
    for condition in conditions:
        output = evaluate_condition(condition, all_forecasts, q_map, args.db)
        outputs.append(output)

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

    rows = _comparison_rows(outputs)
    comparison_md = OUTPUT_DIR / f"contamination_comparison_{ts}.md"
    comparison_tsv = OUTPUT_DIR / f"contamination_comparison_{ts}.tsv"
    comparison_svg = OUTPUT_DIR / f"contamination_comparison_{ts}.svg"
    model_md = OUTPUT_DIR / f"contamination_by_model_{ts}.md"
    model_svg = OUTPUT_DIR / f"contamination_by_model_{ts}.svg"
    vanilla_md = OUTPUT_DIR / f"contamination_vanilla_only_{ts}.md"
    vanilla_svg = OUTPUT_DIR / f"contamination_vanilla_only_{ts}.svg"
    vanilla_latest_md = OUTPUT_DIR / "contamination_vanilla_only_latest.md"
    vanilla_latest_svg = OUTPUT_DIR / "contamination_vanilla_only_latest.svg"
    latest_summary = OUTPUT_DIR / "evaluation_summary_latest.md"
    write_comparison_markdown(rows, comparison_md)
    write_comparison_tsv(rows, comparison_tsv)
    write_comparison_svg(rows, comparison_svg)
    write_model_leakage_markdown(rows, model_md)
    write_model_leakage_svg(rows, model_svg)
    write_vanilla_leakage_markdown(rows, vanilla_md)
    write_vanilla_leakage_svg(rows, vanilla_svg)
    write_vanilla_leakage_markdown(rows, vanilla_latest_md)
    write_vanilla_leakage_svg(rows, vanilla_latest_svg)
    write_latest_summary(outputs, rows, latest_summary)
    print(f"\nSaved contamination comparison to {comparison_md}")
    print(f"Saved contamination comparison data to {comparison_tsv}")
    print(f"Saved contamination comparison chart to {comparison_svg}")
    print(f"Saved model-level contamination comparison to {model_md}")
    print(f"Saved model-level contamination chart to {model_svg}")
    print(f"Saved vanilla-only contamination diagnostic to {vanilla_md}")
    print(f"Saved vanilla-only contamination chart to {vanilla_svg}")
    print(f"Updated latest vanilla-only diagnostic at {vanilla_latest_md}")
    print(f"Updated latest vanilla-only chart at {vanilla_latest_svg}")
    print(f"Saved latest evaluation summary to {latest_summary}")


if __name__ == "__main__":
    main()
