"""
Generate sliding window ablation figure for the paper.

Produces:
  sliding_window.pdf  — accuracy across slots (container mode), line chart per model
  sliding_window.png  — same for quick preview

Usage:
    cd worldreasoner
    uv run python scripts/analysis/plot_sliding_window.py [--db combined.db] [--out assets/]
"""

import argparse
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ── Config ────────────────────────────────────────────────────────────────────

# Each entry: (x_position, display_label, benchmark_condition, slot_in_metadata)
# worldreasoner condition uses early/mid/late slots
# oracle = near-resolution (just before resolution), real_time = resolution date
POINTS = [
    (0,   "Early",     "worldreasoner", "early"),
    (1,   "Mid",       "worldreasoner", "mid"),
    (2,   "Late",      "worldreasoner", "late"),
    (3,   "Near-res", "oracle", "mid"),
    (4.4, "Real-time", "real_time",     "real_time"),
]

MODELS = [
    ("gemini/gemini-3-flash-preview", "Gemini 3 Flash",   "#72B7B2", "o"),
    ("gemini/gemini-3-pro-preview",   "Gemini 3 Pro",     "#4C78A8", "s"),
    ("deepseek/deepseek-v4-flash",    "DeepSeek V4 Flash","#FFBF79", "^"),
]

EVAL_IDS_FILE = "eval_108_ids.txt"  # 108 contamination-filtered question IDs
CUTOFF_CONFIG = Path("config/llm_cutoff_dates.json")
CUTOFF_ALIASES = {
    "gemini/gemini-3-flash-preview": "gemini-3-flash",
    "gemini/gemini-3-pro-preview": "gemini-3-pro",
    "deepseek/deepseek-v4-flash": "deepseek-v4",
}
MIN_N = 25


# ── Data ──────────────────────────────────────────────────────────────────────

def load_eval_ids(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_cutoff_dates(path: Path) -> dict[str, dt.datetime]:
    with open(path, encoding="utf-8") as f:
        config = json.load(f).get("models", {})

    cutoffs: dict[str, dt.datetime] = {}
    for model_key, alias in CUTOFF_ALIASES.items():
        value = (config.get(alias) or {}).get("cutoff_date")
        if not value:
            continue
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        cutoffs[model_key] = parsed
    return cutoffs


def load_deduped(db_path: str) -> dict:
    """
    Load metrics for each (model, condition, slot) point defined in POINTS,
    restricted to the canonical 108-question contamination-filtered eval set.
    Returns: res[model_key][(condition, slot)] = {"n": int, "accuracy": float, "brier": float}
    """
    import datetime as dt

    eval_ids = load_eval_ids(EVAL_IDS_FILE)
    cutoff_dates = load_cutoff_dates(CUTOFF_CONFIG)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load all relevant forecast rows for the eval set
    ph = ",".join("?" * len(eval_ids))
    rows = conn.execute(f"""
        SELECT f.question_id, q.estimated_start_time,
               f.evaluation_metadata, f.is_correct, f.brier_score
        FROM forecasts f
        JOIN questions q ON q.id = f.question_id
        WHERE f.is_correct IS NOT NULL
          AND f.question_id IN ({ph})
    """, eval_ids).fetchall()

    # Apply contamination filter and keep latest per (model, condition, question).
    # For the oracle condition, slot tags are inconsistent across models ('mid' vs
    # 'near-res') so we bucket all oracle rows together and deduplicate by question.
    from collections import defaultdict
    latest = defaultdict(dict)  # (model, cond) -> {qid: row}
    for r in rows:
        start = r["estimated_start_time"]
        meta  = json.loads(r["evaluation_metadata"] or "{}")
        cond  = meta.get("benchmark_condition")
        model = meta.get("benchmark_model")
        if not cond or not model:
            continue
        cutoff = cutoff_dates.get(model)
        if cutoff and start:
            s = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=dt.timezone.utc)
            if s < cutoff:
                continue
        # For non-oracle conditions keep slot granularity; oracle: merge all slots
        slot = meta.get("slot", "mid")
        if cond == "oracle":
            key = (model, cond, "oracle")  # unified oracle key
        else:
            key = (model, cond, slot)
        latest[key][r["question_id"]] = r  # last row per qid wins (rows in rowid order)

    conn.close()

    res = {}
    for model_key, *_ in MODELS:
        res[model_key] = {}
        for _x, _label, cond, slot in POINTS:
            # oracle uses unified key regardless of slot tag in metadata
            lookup_key = (model_key, cond, "oracle") if cond == "oracle" else (model_key, cond, slot)
            q_map = latest.get(lookup_key, {})
            n = len(q_map)
            if n == 0:
                res[model_key][(cond, slot)] = {"n": 0, "accuracy": None, "brier": None}
                continue
            correct = sum(1 for r in q_map.values() if r["is_correct"])
            briers  = [r["brier_score"] for r in q_map.values() if r["brier_score"] is not None]
            res[model_key][(cond, slot)] = {
                "n":        n,
                "accuracy": correct / n,
                "brier":    sum(briers) / len(briers) if briers else None,
            }
    return res


# ── Plot ──────────────────────────────────────────────────────────────────────

def make_figure(results: dict, out_dir: Path):
    fig, ax = plt.subplots(figsize=(8.4, 4.2))

    x_positions = [p[0] for p in POINTS]
    x_labels    = [p[1] for p in POINTS]

    for model_key, label, color, marker in MODELS:
        model_res = results.get(model_key, {})
        xs, ys = [], []
        for x, _lbl, cond, slot in POINTS:
            d   = model_res.get((cond, slot), {})
            n   = d.get("n", 0)
            val = d.get("accuracy")
            if val is not None and n >= MIN_N:
                xs.append(x)
                ys.append(val * 100)

        ax.plot(xs, ys, color=color, marker=marker,
                linewidth=1.8, markersize=6, label=label, alpha=0.86, zorder=2)

    # Dashed separator before real-time column
    ax.axvline(x=3.7, color="#555555", linestyle=(0, (3, 3)), linewidth=1.2, alpha=0.6, zorder=1)

    ax.set_ylim(55, 100)
    ax.set_yticks([60, 70, 80, 90, 100])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:.0f}%"))
    ax.set_ylabel("Accuracy (%)", labelpad=6)
    ax.set_xlabel("Forecast horizon (simulated date position)", labelpad=10)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels, fontsize=9)
    ax.tick_params(axis="x", pad=6)

    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.7)
    ax.grid(True, axis="x", color="#efefef", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        ncol=1,
        frameon=False,
        fontsize=8,
    )

    fig.tight_layout(rect=(0, 0, 0.84, 0.98))
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = out_dir / f"sliding_window.{ext}"
        fig.savefig(path, bbox_inches="tight", dpi=150)
        print(f"Saved: {path}")

    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",  default="combined.db")
    parser.add_argument("--out", default="assets/figures",
                        help="Output directory for PDF/PNG")
    args = parser.parse_args()

    results  = load_deduped(args.db)
    out_dir  = Path(args.out)
    make_figure(results, out_dir)

    # Sanity-check printout
    print("\nAccuracy values used in plot:")
    print(f"{'Model':<25} {'Point':<20} {'N':>5} {'Acc':>7} {'Brier':>8}")
    print("-" * 68)
    for model_key, label, *_ in MODELS:
        model_res = results.get(model_key, {})
        for _x, lbl, cond, slot in POINTS:
            d     = model_res.get((cond, slot), {})
            n     = d.get("n", 0)
            acc   = d.get("accuracy")
            brier = d.get("brier")
            acc_s   = f"{acc:.4f}"   if acc   is not None else "  N/A"
            brier_s = f"{brier:.4f}" if brier is not None else "    N/A"
            print(f"{label:<25} {lbl.replace(chr(10),' '):<20} {n:>5} {acc_s:>7} {brier_s:>8}")
        print()


if __name__ == "__main__":
    main()
