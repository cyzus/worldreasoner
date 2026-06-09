"""
Sliding window ablation analysis.

Produces:
  1. Per-model accuracy & Brier score across early/mid/late/near-res/real_time slots
  2. Knowledge-only gap: container vs knowledge_only at each slot
  3. LaTeX table fragment for the paper

Usage:
    cd worldreasoner
    uv run python scripts/analysis/sliding_window_results.py [--db combined.db] [--latex]
"""

import argparse
import sqlite3
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

SLOT_ORDER = ["early", "mid", "late", "near-res", "real_time"]
SLOT_LABELS = {
    "early":     "Early",
    "mid":       "Mid",
    "late":      "Late",
    "near-res":  "Near-res",
    "real_time": "Real-time",
}

# Models that ran the full sliding window ablation, in display order.
# Tuple: (model_name_in_db, display_label)
MODELS = [
    ("gemini/gemini-3-flash-preview", "Gemini 3 Flash"),
    ("gemini/gemini-3-pro-preview",   "Gemini 3 Pro"),
    ("deepseek/deepseek-v4-flash",    "DeepSeek V4 Flash"),
]

MIN_N = 30  # minimum forecasts to report a cell


# ── Data loading ──────────────────────────────────────────────────────────────

def load_results(db_path: str) -> dict:
    """
    Returns nested dict:
      results[model_name][mode][slot] = {"n": int, "accuracy": float, "brier": float}

    Deduplicates by keeping the latest forecast per (question_id, model_name, mode, slot).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Subquery selects the single latest forecast id per (question, model, mode, slot).
    cur.execute("""
        WITH deduped AS (
            SELECT id
            FROM forecasts
            WHERE evaluation_metadata IS NOT NULL
              AND json_extract(evaluation_metadata, '$.slot') IS NOT NULL
              AND model_name IN (
                SELECT DISTINCT model_name FROM forecasts
              )
            GROUP BY question_id, model_name, mode,
                     json_extract(evaluation_metadata, '$.slot')
            HAVING id = MAX(id)
        )
        SELECT f.model_name, f.mode,
               json_extract(f.evaluation_metadata, '$.slot') AS slot,
               COUNT(*) AS n,
               AVG(CASE WHEN f.is_correct THEN 1.0 ELSE 0.0 END) AS accuracy,
               AVG(f.brier_score) AS avg_brier
        FROM forecasts f
        JOIN deduped d ON f.id = d.id
        GROUP BY f.model_name, f.mode, slot
    """)
    rows = cur.fetchall()
    conn.close()

    results = defaultdict(lambda: defaultdict(dict))
    for model, mode, slot, n, acc, brier in rows:
        results[model][mode][slot] = {
            "n": n,
            "accuracy": acc,
            "brier": brier,
        }
    return results


# ── Printing ──────────────────────────────────────────────────────────────────

def fmt_cell(val, n, fmt=".3f"):
    if val is None or n < MIN_N:
        return f"{'--':>7}"
    return f"{val:{fmt}}"


def print_accuracy_table(results: dict):
    """Container accuracy across slots for each model."""
    print("\n" + "=" * 90)
    print("CONTAINER MODE — Accuracy (↑) across time slots")
    print("=" * 90)
    header = f"{'Model':<25}" + "".join(f"{SLOT_LABELS[s]:>10}" for s in SLOT_ORDER)
    print(header)
    print("-" * 90)
    for model_key, label in MODELS:
        row = results.get(model_key, {})
        container = row.get("container", {})
        rt = row.get("real_time", {})

        cells = []
        for slot in SLOT_ORDER:
            src = rt if slot == "real_time" else container
            d = src.get(slot, {})
            cells.append(fmt_cell(d.get("accuracy"), d.get("n", 0)))
        print(f"{label:<25}" + "".join(cells))

    print()


def print_brier_table(results: dict):
    """Container Brier score across slots for each model."""
    print("\n" + "=" * 90)
    print("CONTAINER MODE — Brier Score (↓) across time slots")
    print("=" * 90)
    header = f"{'Model':<25}" + "".join(f"{SLOT_LABELS[s]:>10}" for s in SLOT_ORDER)
    print(header)
    print("-" * 90)
    for model_key, label in MODELS:
        row = results.get(model_key, {})
        container = row.get("container", {})
        rt = row.get("real_time", {})

        cells = []
        for slot in SLOT_ORDER:
            src = rt if slot == "real_time" else container
            d = src.get(slot, {})
            cells.append(fmt_cell(d.get("brier"), d.get("n", 0)))
        print(f"{label:<25}" + "".join(cells))

    print()


def print_gap_table(results: dict):
    """Container minus knowledge_only accuracy gap (search benefit) per slot."""
    print("\n" + "=" * 90)
    print("SEARCH BENEFIT — Container minus Knowledge-Only accuracy (Δ)")
    print("=" * 90)
    header = f"{'Model':<25}" + "".join(f"{SLOT_LABELS[s]:>10}" for s in SLOT_ORDER if s != 'real_time')
    print(header)
    print("-" * 90)
    for model_key, label in MODELS:
        row = results.get(model_key, {})
        container = row.get("container", {})
        ko = row.get("knowledge_only", {})

        cells = []
        for slot in [s for s in SLOT_ORDER if s != "real_time"]:
            cd = container.get(slot, {})
            kd = ko.get(slot, {})
            c_acc = cd.get("accuracy")
            k_acc = kd.get("accuracy")
            c_n   = cd.get("n", 0)
            k_n   = kd.get("n", 0)
            if c_acc is not None and k_acc is not None and c_n >= MIN_N and k_n >= MIN_N:
                delta = c_acc - k_acc
                cells.append(f"{delta:>+10.3f}")
            else:
                cells.append(f"{'--':>10}")
        print(f"{label:<25}" + "".join(cells))

    print()


def print_n_table(results: dict):
    """Sample counts per cell."""
    print("\n" + "=" * 90)
    print("SAMPLE COUNTS (container / knowledge_only)")
    print("=" * 90)
    header = f"{'Model':<25}" + "".join(f"{SLOT_LABELS[s]:>14}" for s in SLOT_ORDER)
    print(header)
    print("-" * 90)
    for model_key, label in MODELS:
        row = results.get(model_key, {})
        container = row.get("container", {})
        ko = row.get("knowledge_only", {})
        rt = row.get("real_time", {})

        cells = []
        for slot in SLOT_ORDER:
            if slot == "real_time":
                d = rt.get(slot, {})
                cells.append(f"{d.get('n', 0):>14}")
            else:
                cn = container.get(slot, {}).get("n", 0)
                kn = ko.get(slot, {}).get("n", 0)
                cells.append(f"{cn:>6}/{kn:<6}")
        print(f"{label:<25}" + "".join(cells))

    print()


# ── LaTeX output ──────────────────────────────────────────────────────────────

def print_latex_table(results: dict):
    """Print a LaTeX table of container accuracy across slots."""
    slots = ["early", "mid", "late", "near-res", "real_time"]
    col_labels = ["Early", "Mid", "Late", "Near-res", "Real-time"]

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{l" + "c" * len(slots) + "}",
        r"\toprule",
        r"\textbf{Model} & " + " & ".join(f"\\textbf{{{l}}}" for l in col_labels) + r" \\",
        r"\midrule",
    ]

    for model_key, label in MODELS:
        row = results.get(model_key, {})
        container = row.get("container", {})
        rt = row.get("real_time", {})

        cells = []
        for slot in slots:
            src = rt if slot == "real_time" else container
            d = src.get(slot, {})
            acc = d.get("accuracy")
            n   = d.get("n", 0)
            if acc is None or n < MIN_N:
                cells.append("--")
            else:
                cells.append(f"{acc:.3f}")

        lines.append(f"{label} & " + " & ".join(cells) + r" \\")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\caption{Sliding-window ablation: accuracy of the Search-Enabled Graph Agent "
        r"(container mode) across simulated forecast horizons. "
        r"Early/Mid/Late/Near-res correspond to the 0--33\%, 33--67\%, 67--95\%, and "
        r"95--100\% percentile of the forecast window; Real-time uses the resolution date.}",
        r"\label{tab:sliding_window}",
        r"\end{table}",
    ]

    print("\n% ── LaTeX table ──────────────────────────────────────────────")
    print("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="combined.db")
    parser.add_argument("--latex", action="store_true", help="Also print LaTeX table")
    args = parser.parse_args()

    results = load_results(args.db)

    print_accuracy_table(results)
    print_brier_table(results)
    print_gap_table(results)
    print_n_table(results)

    if args.latex:
        print_latex_table(results)


if __name__ == "__main__":
    main()
