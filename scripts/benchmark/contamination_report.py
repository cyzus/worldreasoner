"""Contamination diagnostics and figure generation for benchmark evaluation.

This is the paper-figure / diagnostic layer that sits on top of the reusable
benchmark scoring in ``src/domain/evaluation/benchmark_eval.py`` (also exposed as
``wr benchmark evaluate``). It runs the per-condition evaluation, then writes the
all-vs-contamination-filtered comparison tables and SVG charts used in the paper.

Usage:
    uv run python scripts/benchmark/contamination_report.py
    uv run python scripts/benchmark/contamination_report.py --condition vanilla_llm
    uv run python scripts/benchmark/contamination_report.py --db other.db
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.domain.evaluation.benchmark_eval import (
    ALL_CONDITIONS,
    DEFAULT_OUTPUT_DIR,
    _f,
    _pct,
    evaluate_benchmark,
)


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


def _metric_delta(filtered_value, all_value):
    if filtered_value is None or all_value is None:
        return None
    return filtered_value - all_value


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
        "condition", "model", "all_n", "all_accuracy", "all_brier",
        "all_log_score", "filtered_n", "filtered_accuracy", "filtered_brier",
        "filtered_log_score", "excluded_n", "accuracy_delta", "brier_delta",
        "log_score_delta",
    ]
    lines = ["\t".join(columns)]
    for row in rows:
        lines.append(
            "\t".join("" if row.get(c) is None else str(row.get(c)) for c in columns)
        )
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
        "the Temporal Gateway still enforces evidence access by simulated date "
        "during the run.",
        "",
        "## By Condition",
        "",
        "| Condition | All n | All Acc | All Brier | Filtered n | Filtered Acc "
        "| Filtered Brier | Excluded | Acc Delta |",
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
        "| Condition | Model | All n | All Acc | All Brier | Filtered n "
        "| Filtered Acc | Filtered Brier | Excluded | Acc Delta |",
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
        "all_correct": 0.0, "all_total": 0, "filtered_correct": 0.0,
        "filtered_total": 0, "all_brier_sum": 0.0, "all_brier_n": 0,
        "filtered_brier_sum": 0.0, "filtered_brier_n": 0, "excluded_n": 0,
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
        filtered_acc = stats["filtered_correct"] / filtered_n if filtered_n else None
        all_brier = (
            stats["all_brier_sum"] / stats["all_brier_n"]
            if stats["all_brier_n"] else None
        )
        filtered_brier = (
            stats["filtered_brier_sum"] / stats["filtered_brier_n"]
            if stats["filtered_brier_n"] else None
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
        "A high excluded share means more model-question pairs started before the "
        "model's knowledge cutoff. A negative accuracy delta means the model "
        "performs worse after those pairs are removed.",
        "",
        "| Model | Conditions | All n | Filtered n | Excluded | Excluded Share "
        "| All Acc | Filtered Acc | Acc Delta | All Brier | Filtered Brier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in model_rows:
        lines.append(
            f"| {row['model']} | {row['condition_count']} | {row['all_n']} | "
            f"{row['filtered_n']} | {row['excluded_n']} | "
            f"{_pct(row['excluded_share'])} | {_pct(row['all_accuracy'])} | "
            f"{_pct(row['filtered_accuracy'])} | {_pct(row['accuracy_delta'])} | "
            f"{_f(row['all_brier'])} | {_f(row['filtered_brier'])} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


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
        "This table uses only the `Vanilla LLM` condition, where models have no "
        "search or tool access. This is the cleanest diagnostic for whether newer "
        "training cutoffs may inflate performance through parametric knowledge.",
        "",
        "| Model | All n | Filtered n | Excluded | Excluded Share | All Acc "
        "| Filtered Acc | Acc Delta | All Brier | Filtered Brier |",
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
    path.write_text("\n".join(lines), encoding="utf-8")


def write_comparison_svg(rows: list[dict], path: Path) -> None:
    """Dependency-free paired bar chart for overall condition accuracy."""
    overall = [r for r in rows if r["model"] == "__overall__"]
    if not overall:
        return

    width, row_h, top, left, chart_w = 920, 54, 60, 190, 620
    height = top + row_h * len(overall) + 55

    def x_for(v):
        return left + max(0.0, min(1.0, v or 0.0)) * chart_w

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" '
        'font-weight="700">All vs. contamination-filtered accuracy</text>',
        '<text x="24" y="52" font-family="Arial, sans-serif" font-size="12" '
        'fill="#555">Filtered excludes question/model pairs whose start date '
        'predates the model knowledge cutoff.</text>',
    ]
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x_for(tick)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top-10}" x2="{x:.1f}" y2="{height-45}" '
            f'stroke="#dddddd" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{height-25}" font-family="Arial, sans-serif" '
            f'font-size="11" text-anchor="middle" fill="#666">{int(tick*100)}%</text>'
        )
    for i, row in enumerate(overall):
        y = top + i * row_h
        all_x = x_for(row["all_accuracy"])
        filt_x = x_for(row["filtered_accuracy"])
        parts.append(
            f'<text x="24" y="{y+24}" font-family="Arial, sans-serif" '
            f'font-size="13" font-weight="600">{row["condition_label"]}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y+8}" width="{max(all_x-left, 0):.1f}" '
            f'height="14" fill="#b7d7ea" stroke="#6f9db5"/>'
        )
        parts.append(
            f'<rect x="{left}" y="{y+28}" width="{max(filt_x-left, 0):.1f}" '
            f'height="14" fill="#d9efd2" stroke="#8ab37e"/>'
        )
        parts.append(
            f'<text x="{all_x+6:.1f}" y="{y+20}" font-family="Arial, sans-serif" '
            f'font-size="11" fill="#333">{_pct(row["all_accuracy"])}</text>'
        )
        parts.append(
            f'<text x="{filt_x+6:.1f}" y="{y+40}" font-family="Arial, sans-serif" '
            f'font-size="11" fill="#333">{_pct(row["filtered_accuracy"])}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark contamination diagnostics and figures"
    )
    parser.add_argument("--db", default="combined.db", help="Database path")
    parser.add_argument(
        "--include-ids",
        default=None,
        help="Optional file with one question ID per line to restrict evaluation.",
    )
    parser.add_argument(
        "--condition",
        nargs="*",
        default=None,
        metavar="CONDITION",
        help=f"Condition(s) to evaluate (default: all with data). {ALL_CONDITIONS}",
    )
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--exclude-model", action="append", default=None)
    args = parser.parse_args()

    outputs = evaluate_benchmark(
        db_path=args.db,
        conditions=args.condition,
        include_ids_path=args.include_ids,
        models=args.model,
        exclude_models=args.exclude_model,
    )

    rows = _comparison_rows(outputs)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    write_comparison_markdown(rows, out / f"contamination_comparison_{ts}.md")
    write_comparison_tsv(rows, out / f"contamination_comparison_{ts}.tsv")
    write_comparison_svg(rows, out / f"contamination_comparison_{ts}.svg")
    write_model_leakage_markdown(rows, out / f"contamination_by_model_{ts}.md")
    write_vanilla_leakage_markdown(rows, out / f"contamination_vanilla_only_{ts}.md")
    write_vanilla_leakage_markdown(rows, out / "contamination_vanilla_only_latest.md")
    print(f"\nSaved contamination diagnostics to {out}/")


if __name__ == "__main__":
    main()
