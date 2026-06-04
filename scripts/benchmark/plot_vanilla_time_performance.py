"""Plot Vanilla LLM performance over question time.

This diagnostic figure is meant for the appendix/contamination discussion. It
uses only the Vanilla LLM condition, where models have no retrieval or tools, so
time-varying performance is easiest to interpret as a possible knowledge-cutoff
or memorization signal.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt


DEFAULT_DB = "combined.db"
DEFAULT_OUTPUT_DIR = Path("experiments/evaluation")
DEFAULT_CUTOFF_CONFIG = Path("config/llm_cutoff_dates.json")
DEFAULT_EXCLUDED_MODELS = {"dashscope/deepseek-v4-flash"}

MODEL_LABELS = {
    "gemini/gemini-3-pro-preview": "Gemini 3 Pro",
    "gemini/gemini-3-flash-preview": "Gemini 3 Flash",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "openai/gpt-5.4": "GPT-5.4",
    "openai/gpt-4o-2024-11-20": "GPT-4o",
    "dashscope/qwen3.5-397b-a17b": "Qwen3.5 397B",
}

MODEL_COLORS = {
    "gemini/gemini-3-pro-preview": "#4C78A8",
    "gemini/gemini-3-flash-preview": "#72B7B2",
    "deepseek/deepseek-v4-pro": "#F58518",
    "deepseek/deepseek-v4-flash": "#FFBF79",
    "openai/gpt-5.4": "#54A24B",
    "openai/gpt-4o-2024-11-20": "#B279A2",
    "dashscope/qwen3.5-397b-a17b": "#E45756",
}

CUTOFF_ALIASES = {
    "gemini/gemini-3-pro-preview": "gemini-3-pro",
    "gemini/gemini-3-flash-preview": "gemini-3-flash",
    "deepseek/deepseek-v4-pro": "deepseek-v4",
    "deepseek/deepseek-v4-flash": "deepseek-v4",
    "openai/gpt-5.4": "gpt-5.4",
    "openai/gpt-4o-2024-11-20": "gpt-4o-2024-11-20",
    "dashscope/qwen3.5-397b-a17b": "qwen3.5",
}

PROXY_CUTOFFS = {
    "gemini/gemini-3-pro-preview": "2025-01-01",
    "gemini/gemini-3-flash-preview": "2025-01-01",
    "deepseek/deepseek-v4-pro": "2025-05-01",
    "deepseek/deepseek-v4-flash": "2025-05-01",
    "openai/gpt-5.4": "2025-08-31",
    "openai/gpt-4o-2024-11-20": "2023-10-01",
}


@dataclass(frozen=True)
class ForecastPoint:
    question_id: str
    model: str
    timestamp: str
    question_date: dt.datetime
    is_correct: bool


def parse_date(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def read_ids(path: str | None) -> set[str] | None:
    if not path:
        return None
    p = Path(path)
    return {
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def load_cutoff_dates(path: Path) -> dict[str, dt.datetime]:
    cutoffs: dict[str, dt.datetime] = {}
    if not path.exists():
        return cutoffs
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    data = raw_data.get("models", raw_data)
    for model_id, alias in CUTOFF_ALIASES.items():
        raw_date = PROXY_CUTOFFS.get(model_id)
        if raw_date is None:
            entry = data.get(alias, {})
            raw_date = entry.get("cutoff_date")
        parsed = parse_date(raw_date)
        if parsed is not None:
            cutoffs[model_id] = parsed
    return cutoffs


def load_vanilla_points(
    conn: sqlite3.Connection,
    include_ids: set[str] | None,
    date_field: str,
) -> list[ForecastPoint]:
    if date_field not in {"estimated_start_time", "resolution_date"}:
        raise ValueError(f"Unsupported date field: {date_field}")

    rows = conn.execute(
        f"""
        select f.id, f.question_id, f.model_name, f.timestamp, f.is_correct,
               f.evaluation_metadata, q.{date_field} as question_date
        from forecasts f
        join questions q on q.id = f.question_id
        where f.evaluation_metadata is not null
          and f.is_correct is not null
        """
    ).fetchall()

    latest: dict[tuple[str, str], ForecastPoint] = {}
    for row in rows:
        qid = row["question_id"]
        if include_ids is not None and qid not in include_ids:
            continue
        metadata = {}
        try:
            metadata = json.loads(row["evaluation_metadata"] or "{}")
        except json.JSONDecodeError:
            continue
        if metadata.get("benchmark_condition") != "vanilla_llm":
            continue
        model = metadata.get("benchmark_model") or row["model_name"] or ""
        question_date = parse_date(row["question_date"])
        if question_date is None:
            continue
        point = ForecastPoint(
            question_id=qid,
            model=model,
            timestamp=row["timestamp"] or "",
            question_date=question_date,
            is_correct=bool(row["is_correct"]),
        )
        key = (qid, model)
        old = latest.get(key)
        if old is None or point.timestamp >= old.timestamp:
            latest[key] = point

    return list(latest.values())


def rolling_accuracy(points: list[ForecastPoint], window: int) -> list[dict[str, Any]]:
    points = sorted(points, key=lambda p: p.question_date)
    rows: list[dict[str, Any]] = []
    for idx in range(len(points)):
        start = max(0, idx - window + 1)
        batch = points[start: idx + 1]
        rows.append(
            {
                "model": points[idx].model,
                "question_date": points[idx].question_date.date().isoformat(),
                "rolling_n": len(batch),
                "rolling_accuracy": sum(p.is_correct for p in batch) / len(batch),
                "cumulative_n": idx + 1,
                "cumulative_accuracy": sum(p.is_correct for p in points[: idx + 1]) / (idx + 1),
            }
        )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "model",
                "question_date",
                "rolling_n",
                "rolling_accuracy",
                "cumulative_n",
                "cumulative_accuracy",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def plot_curves(
    rows_by_model: dict[str, list[dict[str, Any]]],
    output_pdf: Path,
    date_field: str,
    window: int,
    cutoff_dates: dict[str, dt.datetime],
) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    cutoff_groups: dict[dt.date, list[str]] = defaultdict(list)
    for model in rows_by_model:
        cutoff_date = cutoff_dates.get(model)
        if cutoff_date is not None:
            cutoff_groups[cutoff_date.date()].append(model)
    cutoff_offsets: dict[str, int] = {}
    for models in cutoff_groups.values():
        models = sorted(models)
        center = (len(models) - 1) / 2
        for idx, model in enumerate(models):
            cutoff_offsets[model] = int(round((idx - center) * 8))

    for model, rows in sorted(rows_by_model.items()):
        if not rows:
            continue
        xs = [dt.datetime.fromisoformat(row["question_date"]) for row in rows]
        ys = [100 * float(row["rolling_accuracy"]) for row in rows]
        label = MODEL_LABELS.get(model, model.replace("/", "\n"))
        color = MODEL_COLORS.get(model)
        ax.plot(xs, ys, label=label, linewidth=1.8, alpha=0.86, color=color, zorder=2)

    for model in sorted(rows_by_model):
        cutoff_date = cutoff_dates.get(model)
        if cutoff_date is None:
            continue
        color = MODEL_COLORS.get(model)
        offset_days = cutoff_offsets.get(model, 0)
        display_date = cutoff_date + dt.timedelta(days=offset_days)
        display_date = display_date.replace(tzinfo=None)
        ax.axvline(
            display_date,
            color=color,
            linestyle=(0, (3, 3)),
            linewidth=1.8,
            alpha=0.9,
            zorder=8,
        )
        ax.scatter(
            [display_date],
            [103],
            marker="v",
            s=34,
            color=color,
            edgecolor="white",
            linewidth=0.5,
            zorder=9,
        )

    ax.set_ylim(0, 106)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_ylabel(f"Rolling accuracy, window={window} (%)")
    ax.set_xlabel(
        "Question estimated start date"
        if date_field == "estimated_start_time"
        else "Question resolution date",
        labelpad=10,
    )
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.7)
    ax.grid(True, axis="x", color="#efefef", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(
        FuncFormatter(
            lambda x, _pos: (
                mdates.num2date(x).strftime("%Y")
                if mdates.num2date(x).month == 1
                else mdates.num2date(x).strftime("%b")
            )
        )
    )
    ax.tick_params(axis="x", labelrotation=0, pad=6)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(
        Line2D(
            [0],
            [0],
            color="#555555",
            linestyle=(0, (3, 3)),
            marker="v",
            markersize=5,
            linewidth=1.6,
            label="Knowledge cutoff",
        )
    )
    labels.append("Knowledge cutoff")
    ax.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        ncol=1,
        frameon=False,
        fontsize=8,
    )
    ax.set_title("Vanilla LLM Performance Over Time", fontsize=11, weight="bold")
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    fig.savefig(output_pdf, format="pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--include-ids", default="include_ids.txt")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--date-field",
        choices=["estimated_start_time", "resolution_date"],
        default="estimated_start_time",
    )
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--min-n", type=int, default=30)
    parser.add_argument("--cutoff-config", type=Path, default=DEFAULT_CUTOFF_CONFIG)
    parser.add_argument(
        "--tag",
        default="",
        help="Optional filename tag, e.g. w40, to avoid overwriting default outputs.",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "Model id to include. Repeat for multiple models. Default: all models "
            "with at least --min-n Vanilla rows, excluding DashScope DeepSeek aliases."
        ),
    )
    args = parser.parse_args()

    include_ids = read_ids(args.include_ids)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        points = load_vanilla_points(conn, include_ids, args.date_field)
    finally:
        conn.close()

    grouped: dict[str, list[ForecastPoint]] = defaultdict(list)
    for point in points:
        grouped[point.model].append(point)

    selected_models = set(args.model or [])
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    for model, model_points in grouped.items():
        if model in DEFAULT_EXCLUDED_MODELS:
            continue
        if selected_models and model not in selected_models:
            continue
        if not selected_models and len(model_points) < args.min_n:
            continue
        rows_by_model[model] = rolling_accuracy(model_points, args.window)

    all_rows = [row for rows in rows_by_model.values() for row in rows]
    cutoff_dates = load_cutoff_dates(args.cutoff_config)
    suffix = "start" if args.date_field == "estimated_start_time" else "resolution"
    tag = f"_{args.tag}" if args.tag else ""
    csv_path = args.output_dir / f"vanilla_time_performance_{suffix}{tag}.csv"
    pdf_path = args.output_dir / f"vanilla_time_performance_{suffix}{tag}.pdf"
    write_csv(all_rows, csv_path)
    plot_curves(rows_by_model, pdf_path, args.date_field, args.window, cutoff_dates)

    print(f"Wrote {csv_path}")
    print(f"Wrote {pdf_path}")
    print("Included models:")
    for model in sorted(rows_by_model):
        print(f"  {model}: {len(rows_by_model[model])} points")


if __name__ == "__main__":
    main()
