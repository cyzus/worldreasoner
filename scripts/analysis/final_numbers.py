import json

FILES = {
    "original":   "experiments/evaluation/reasoning_graph_eval_filtered_latest.json",
    "annotation": "experiments/evaluation/annotation_filtered/reasoning_graph_eval_filtered_latest.json",
}
CONDS = ["vanilla_llm","structured_scenario","search_enabled","worldreasoner","oracle","real_time"]
LABELS = {
    "vanilla_llm":         "Vanilla LLM",
    "structured_scenario": "Causal Sim.",
    "search_enabled":      "Search-Enabled",
    "worldreasoner":       "Search-Enabled Graph",
    "oracle":              "Near-Resolution",
    "real_time":           "Real-Time",
}

def p(v):
    return f"{v*100:.1f}" if v is not None else "--"

def n(v, d=3):
    return f"{v:.{d}f}" if v is not None else "--"

def kf1(s):
    kr = s.get("key_event_recall")
    kp = s.get("key_event_precision")
    if kr and kp and (kr + kp) > 0:
        return 2 * kr * kp / (kr + kp)
    return None

for label, path in FILES.items():
    with open(path) as f:
        d = json.load(f)
    print(f"=== {label} ===")
    hdr = f"{'Condition':<22} {'N':>5} {'Acc':>6} {'Brier':>7} {'Log':>7} {'SrcPrec':>8} {'EvF1':>6} {'KERecall':>9} {'KE-F1':>7} {'KEPrec':>7}"
    print(hdr)
    print("-" * len(hdr))
    for c in CONDS:
        s = d.get("by_condition", {}).get(c, {})
        if not s:
            continue
        print(
            f"{LABELS[c]:<22} {s['n']:>5}"
            f" {p(s.get('accuracy')):>6}"
            f" {n(s.get('brier_score')):>7}"
            f" {n(s.get('log_score')):>7}"
            f" {p(s.get('exact_source_precision')):>8}"
            f" {p(s.get('event_f1')):>6}"
            f" {p(s.get('key_event_recall')):>9}"
            f" {p(kf1(s)):>7}"
            f" {p(s.get('key_event_precision')):>7}"
        )
    print()
