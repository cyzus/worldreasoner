import json

BEFORE = "experiments/evaluation/reasoning_graph_eval_filtered_latest.json"
AFTER  = "experiments/evaluation/annotation_filtered/reasoning_graph_eval_filtered_latest.json"

COND_LABELS = {
    "vanilla_llm": "Vanilla LLM",
    "structured_scenario": "Causal Sim.",
    "search_enabled": "Search-Enabled",
    "worldreasoner": "Search-Enabled Graph",
    "oracle": "Near-Resolution",
    "real_time": "Real-Time",
}
METRICS = [
    ("event_f1",           "Event F1"),
    ("key_event_recall",   "KE Recall"),
    ("key_event_precision","KE Precision"),
    ("exact_source_precision", "Src Precision"),
    ("accuracy",           "Accuracy"),
]

with open(BEFORE) as f: before = json.load(f)
with open(AFTER)  as f: after  = json.load(f)

print(f"{'Condition':<22}  {'Metric':<16}  {'Before':>8}  {'After':>8}  {'Delta':>8}")
print("-" * 70)
for cond, clabel in COND_LABELS.items():
    b = before.get("by_condition", {}).get(cond, {})
    a = after.get("by_condition",  {}).get(cond, {})
    if not b or not a:
        continue
    first = True
    for key, mlabel in METRICS:
        bv = b.get(key)
        av = a.get(key)
        if bv is None and av is None:
            continue
        bstr = f"{bv*100:.1f}%" if bv is not None else "--"
        astr = f"{av*100:.1f}%" if av is not None else "--"
        dstr = f"{(av-bv)*100:+.1f}pp" if (bv is not None and av is not None) else "--"
        label = clabel if first else ""
        print(f"{label:<22}  {mlabel:<16}  {bstr:>8}  {astr:>8}  {dstr:>8}")
        first = False
    print()
