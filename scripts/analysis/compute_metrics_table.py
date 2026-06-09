"""
Compute all implemented metrics from the eval JSON and append a results table
to docs/metrics.md.

Usage:
    cd worldreasoner
    uv run python scripts/analysis/compute_metrics_table.py
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

EVAL_JSON = "experiments/evaluation/reasoning_graph_eval_filtered_latest.json"
DOCS_MD   = "docs/metrics.md"

CONDITION_LABELS = {
    "vanilla_llm":          "Vanilla LLM",
    "structured_scenario":  "Causal Sim.",
    "search_enabled":       "Search-Enabled",
    "worldreasoner":        "Search-Enabled Graph",
    "oracle":               "Near-Resolution",
    "real_time":            "Real-Time",
}
CONDITION_ORDER = list(CONDITION_LABELS.keys())

PAPER_MODELS = {
    "gemini/gemini-3-flash-preview": "Gemini Flash",
    "gemini/gemini-3-pro-preview":   "Gemini Pro",
    "deepseek/deepseek-v4-flash":    "DeepSeek Flash",
    "deepseek/deepseek-v4-pro":      "DeepSeek Pro",
    "openai/gpt-4o-2024-11-20":      "GPT-4o",
    "openai/gpt-5.4":                "GPT-5.4",
}


def avg(vals):
    return statistics.mean(vals) if vals else None

def pct(v):
    return f"{v*100:.1f}%" if v is not None else "--"

def num(v, decimals=3):
    return f"{v:.{decimals}f}" if v is not None else "--"


def load(json_path):
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def compute_kf1(kr, kp):
    if kr is not None and kp is not None and (kr + kp) > 0:
        return 2 * kr * kp / (kr + kp)
    return None


def aggregate_rows(rows):
    def _avg(key):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        return avg(vals)

    kr  = _avg("key_event_recall")
    kp  = _avg("key_event_precision")
    return {
        "n":                    len(rows),
        "accuracy":             _avg("is_correct"),
        "brier":                _avg("brier_score"),
        "log_score":            _avg("log_score"),
        "source_precision":     _avg("exact_source_precision"),
        "event_f1":             _avg("event_f1"),
        "key_event_recall":     kr,
        "key_event_precision":  kp,
        "key_event_f1":         compute_kf1(kr, kp),
        "temporal_mae":         _avg("temporal_mae_days"),
        "market_signal_recall": _avg("market_signal_recall"),
        "accessible_event_f1":  _avg("accessible_event_f1"),
    }


def build_tables(data):
    rows = data["rows"]

    # ── by condition (all models) ────────────────────────────────────────────
    by_cond = defaultdict(list)
    for r in rows:
        by_cond[r.get("condition", "")].append(r)

    cond_stats = {}
    for c in CONDITION_ORDER:
        if c in by_cond:
            cond_stats[c] = aggregate_rows(by_cond[c])

    # ── by condition × model ─────────────────────────────────────────────────
    by_cond_model = defaultdict(list)
    for r in rows:
        key = (r.get("condition", ""), r.get("model", ""))
        by_cond_model[key].append(r)

    return cond_stats, by_cond_model


def render_aggregate_table(cond_stats):
    lines = []
    lines.append("### By condition (all models, N=605)\n")
    lines.append("| Condition | N | Acc | Brier | Log | Src Prec | Event F1 | KE Recall | KE F1 | KE Prec | Temporal MAE |")
    lines.append("|-----------|---|-----|-------|-----|----------|----------|-----------|-------|---------|--------------|")
    for c in CONDITION_ORDER:
        if c not in cond_stats:
            continue
        s = cond_stats[c]
        lines.append(
            f"| {CONDITION_LABELS[c]} | {s['n']} "
            f"| {pct(s['accuracy'])} | {num(s['brier'])} | {num(s['log_score'])} "
            f"| {pct(s['source_precision'])} | {pct(s['event_f1'])} "
            f"| {pct(s['key_event_recall'])} | {pct(s['key_event_f1'])} | {pct(s['key_event_precision'])} "
            f"| {num(s['temporal_mae'], 1)} days |"
        )
    return "\n".join(lines)


def render_per_model_table(by_cond_model):
    lines = []
    lines.append("\n### By condition × model\n")
    lines.append("| Condition | Model | N | Acc | Src Prec | Event F1 | KE Recall | KE F1 | KE Prec |")
    lines.append("|-----------|-------|---|-----|----------|----------|-----------|-------|---------|")
    for c in CONDITION_ORDER:
        for m, mlabel in PAPER_MODELS.items():
            key = (c, m)
            if key not in by_cond_model:
                continue
            s = aggregate_rows(by_cond_model[key])
            lines.append(
                f"| {CONDITION_LABELS[c]} | {mlabel} | {s['n']} "
                f"| {pct(s['accuracy'])} | {pct(s['source_precision'])} "
                f"| {pct(s['event_f1'])} | {pct(s['key_event_recall'])} "
                f"| {pct(s['key_event_f1'])} | {pct(s['key_event_precision'])} |"
            )
    return "\n".join(lines)


def render_retrieval_vs_forecast_note(by_cond_model, rows_all):
    """Accessible vs future event split — accessible_event_f1 is implemented
    but has known artifacts; report it with a caveat."""
    lines = []
    lines.append("\n### Retrieval vs. forecasting split (accessible event F1)\n")
    lines.append("> **Caveat:** Accessible event F1 uses only hindsight events that occurred ≤ simulated_date as the denominator. This inflates Causal Simulation scores (small pool at early dates) and is undefined for Real-Time (no simulated_date). Treat as indicative only.\n")
    lines.append("| Condition | Model | Accessible Event F1 |")
    lines.append("|-----------|-------|---------------------|")

    GRAPH_CONDS = ["structured_scenario", "worldreasoner", "oracle"]
    for c in GRAPH_CONDS:
        for m, mlabel in PAPER_MODELS.items():
            key = (c, m)
            if key not in by_cond_model:
                continue
            s = aggregate_rows(by_cond_model[key])
            lines.append(f"| {CONDITION_LABELS[c]} | {mlabel} | {pct(s['accessible_event_f1'])} |")
    return "\n".join(lines)


def main():
    data = load(EVAL_JSON)
    cond_stats, by_cond_model = build_tables(data)

    agg_table    = render_aggregate_table(cond_stats)
    model_table  = render_per_model_table(by_cond_model)
    split_table  = render_retrieval_vs_forecast_note(by_cond_model, data["rows"])

    results_block = "\n".join([agg_table, model_table, split_table])

    # Replace everything after the sentinel comment in metrics.md
    md_path = Path(DOCS_MD)
    md_text = md_path.read_text(encoding="utf-8")
    sentinel = "<!-- results table generated by scripts/analysis/compute_metrics_table.py -->"
    if sentinel in md_text:
        md_text = md_text[:md_text.index(sentinel) + len(sentinel)]
    md_text += "\n\n" + results_block + "\n"
    md_path.write_text(md_text, encoding="utf-8")
    print(f"Written: {md_path}")


if __name__ == "__main__":
    main()
