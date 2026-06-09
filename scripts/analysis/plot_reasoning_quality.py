"""
Generate per-model reasoning quality figure for the paper.

Layout: 3 rows (Event F1, Key-event Recall, Source Precision) x 1 column.
X-axis = models, one line per condition. This makes cross-model differences
the primary reading direction.

Source Precision is only defined for Search-Enabled, Search-Enabled Graph,
and Near-Resolution (conditions with article provenance); those three lines
are drawn in the bottom panel.

Produces:
  reasoning_quality.pdf  — line chart, 3-row panel
  reasoning_quality.png  — same for quick preview

Usage:
    cd worldreasoner
    uv run python scripts/analysis/plot_reasoning_quality.py
    uv run python scripts/analysis/plot_reasoning_quality.py --eval-json experiments/evaluation/reasoning_graph_eval_filtered_latest.json
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


# ── Config ────────────────────────────────────────────────────────────────────

PAPER_MODELS = {
    "gemini/gemini-3-flash-preview": "Gemini\nFlash",
    "gemini/gemini-3-pro-preview":   "Gemini\nPro",
    "deepseek/deepseek-v4-flash":    "DeepSeek\nFlash",
    "deepseek/deepseek-v4-pro":      "DeepSeek\nPro",
    "openai/gpt-4o-2024-11-20":      "GPT-4o",
    "openai/gpt-5.4":                "GPT-5.4",
}
MODEL_ORDER = list(PAPER_MODELS.keys())
MODEL_LABELS = list(PAPER_MODELS.values())

# Conditions with graph artifacts
GRAPH_CONDS = ["structured_scenario", "worldreasoner", "oracle", "real_time"]
# Conditions with source provenance
SOURCE_CONDS = ["search_enabled", "worldreasoner", "oracle"]

COND_STYLE = {
    # (label, color, linestyle, marker)
    "structured_scenario": ("Causal Sim.",       "#FFBF79", "-",  "o"),
    "search_enabled":      ("Search-Enabled",    "#72B7B2", "--", "s"),
    "worldreasoner":       ("Search-Enabled Graph", "#4C78A8", "-",  "^"),
    "oracle":              ("Near-Resolution",   "#54A24B", "-",  "D"),
    "real_time":           ("Real-Time",         "#B279A2", ":",  "v"),
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_from_eval_json(json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    rows = data.get("rows", [])
    by_mc: dict = defaultdict(lambda: {"kr": [], "kf1": [], "kp": [], "sp": []})
    for r in rows:
        m = r.get("model", "")
        c = r.get("condition", "")
        if m not in PAPER_MODELS:
            continue
        kr = r.get("key_event_recall")
        kp = r.get("key_event_precision")
        if kr is not None:
            by_mc[(m, c)]["kr"].append(float(kr))
        if kp is not None:
            by_mc[(m, c)]["kp"].append(float(kp))
        if kr is not None and kp is not None and (float(kr) + float(kp)) > 0:
            kf1 = 2 * float(kr) * float(kp) / (float(kr) + float(kp))
            by_mc[(m, c)]["kf1"].append(kf1)
        if r.get("exact_source_precision") is not None:
            by_mc[(m, c)]["sp"].append(float(r["exact_source_precision"]))

    def avg(lst):
        return statistics.mean(lst) * 100 if lst else None

    all_conds = list(dict.fromkeys(GRAPH_CONDS + SOURCE_CONDS))
    results = {}
    for m in MODEL_ORDER:
        results[m] = {}
        for c in all_conds:
            results[m][c] = {
                "kr":  avg(by_mc[(m, c)]["kr"]),
                "kf1": avg(by_mc[(m, c)]["kf1"]),
                "kp":  avg(by_mc[(m, c)]["kp"]),
                "sp":  avg(by_mc[(m, c)]["sp"]),
            }
    return results


# ── Plot ──────────────────────────────────────────────────────────────────────

def make_figure(results: dict, out_dir: Path):
    xs = list(range(len(MODEL_ORDER)))

    fig, axes = plt.subplots(
        3, 1,
        figsize=(8.5, 7.5),
        sharex=True,
    )
    fig.subplots_adjust(hspace=0.32, top=0.93, bottom=0.10, left=0.1, right=0.72)

    panels = [
        ("Key-event Recall (%)",    "kr",  GRAPH_CONDS),
        ("Key-event F1 (%)",        "kf1", GRAPH_CONDS),
        ("Key-event Precision (%)", "kp",  GRAPH_CONDS),
    ]

    all_handles, all_labels = [], []

    for ax, (ylabel, field, conds) in zip(axes, panels):
        for cond in conds:
            label, color, ls, marker = COND_STYLE[cond]
            ys = [results[m][cond][field] for m in MODEL_ORDER]
            # replace None with nan so lines break cleanly
            import math
            ys_plot = [y if y is not None else math.nan for y in ys]
            line, = ax.plot(
                xs, ys_plot,
                color=color, linestyle=ls, marker=marker,
                linewidth=1.8, markersize=6, alpha=0.88, zorder=2,
                label=label,
            )
            if label not in all_labels:
                all_handles.append(line)
                all_labels.append(label)

        ax.set_ylabel(ylabel, fontsize=9, labelpad=6)
        ax.set_ylim(15, 50)
        ax.set_yticks([15, 20, 25, 30, 35, 40, 45, 50])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:.0f}%"))
        ax.tick_params(axis="y", labelsize=8)
        ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.6, zorder=0)
        ax.grid(True, axis="x", color="#efefef", linewidth=0.4, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # x-axis labels only on bottom panel
    axes[-1].set_xticks(xs)
    axes[-1].set_xticklabels(MODEL_LABELS, fontsize=8.5)

    # shared legend to the right
    fig.legend(
        all_handles, all_labels,
        loc="center right",
        bbox_to_anchor=(1.0, 0.5),
        fontsize=8.5,
        frameon=False,
        ncol=1,
        handlelength=2.2,
    )

    fig.suptitle("Reasoning Quality per Model", fontsize=12, weight="bold")

    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = out_dir / f"reasoning_quality.{ext}"
        fig.savefig(path, bbox_inches="tight", dpi=150)
        print(f"Saved: {path}")

    plt.close(fig)


# ── Sanity-check printout ─────────────────────────────────────────────────────

def print_table(results: dict):
    print()
    print(f"{'Model':<18}  {'Cond':<22}  {'KR':>6}  {'KF1':>6}  {'KP':>6}")
    print("-" * 63)
    for m in MODEL_ORDER:
        label = PAPER_MODELS[m].replace("\n", " ")
        for c in GRAPH_CONDS:
            d   = results[m][c]
            kr  = f"{d['kr']:.1f}"  if d["kr"]  is not None else "  --"
            kf1 = f"{d['kf1']:.1f}" if d["kf1"] is not None else "  --"
            kp  = f"{d['kp']:.1f}"  if d["kp"]  is not None else "  --"
            print(f"{label:<18}  {COND_STYLE[c][0]:<22}  {kr:>6}  {kf1:>6}  {kp:>6}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--eval-json",
        default="experiments/evaluation/reasoning_graph_eval_filtered_latest.json",
    )
    parser.add_argument("--out", default="assets/figures")
    args = parser.parse_args()

    results = load_from_eval_json(args.eval_json)
    print_table(results)
    make_figure(results, Path(args.out))


if __name__ == "__main__":
    main()
