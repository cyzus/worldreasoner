import json
from pathlib import Path
from collections import defaultdict

ANNOTATED_DIR = Path("d:/workspace/wr/annotated")

sessions = []
for path in sorted(ANNOTATED_DIR.glob("*.json")):
    with open(path, encoding="utf-8") as f:
        sessions.append(json.load(f))

print("=== ATTENTION CHECK ANALYSIS ===")
total_checks = 0
passed_n = 0
failed_details = []
for sess in sessions:
    sid = sess.get("session_id", "?")
    pid = sess.get("prolific_pid", "?")[:10]
    for ac in sess.get("attention_checks", []):
        total_checks += 1
        p = ac.get("passed", False)
        if p:
            passed_n += 1
        else:
            failed_details.append({
                "session": sid,
                "pid": pid,
                "exp_status": ac.get("expected_status"),
                "exp_reason": ac.get("expected_reason"),
                "got_status": ac.get("selected_status"),
                "got_reason": ac.get("selected_reason"),
            })

print(f"Total checks: {total_checks}")
print(f"Passed: {passed_n} ({passed_n/total_checks*100:.1f}%)")
print(f"Failed: {len(failed_details)}")
if failed_details:
    print()
    print("Failed checks:")
    for f in failed_details:
        exp = f"({f['exp_status']}, {f['exp_reason']})"
        got = f"({f['got_status']}, {f['got_reason']})"
        print(f"  Session {f['session']} ({f['pid']}): expected {exp} got {got}")

print()
print("=== ANNOTATOR APPROVAL RATE DISTRIBUTION ===")
approval_rates = []
for sess in sessions:
    sid = sess.get("session_id", "?")
    pid = sess.get("prolific_pid", "?")[:10]
    attn_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
    ACCEPT_REASONS = {"PredictionNotEvent", "Noise", "Duplicate", "TooBoard"}
    events = []
    for q in sess.get("data", []):
        if q["id"] in attn_qids:
            continue
        events.extend(q.get("events", []))
    if not events:
        continue
    approved = sum(
        1 for e in events
        if e.get("current_status") == "approved"
        or e.get("reject_reason") in ACCEPT_REASONS
    )
    rate = approved / len(events)
    approval_rates.append((rate, sid, pid, len(events)))

approval_rates.sort()
print(f"{'Session':<8} {'PID':<12} {'Events':<8} {'Approval rate'}")
for rate, sid, pid, n in approval_rates:
    flag = " *** OUTLIER" if rate < 0.15 or rate > 0.98 else ""
    print(f"{sid:<8} {pid:<12} {n:<8} {rate*100:.1f}%{flag}")

print()
print("=== OVERLAP QUESTION AGREEMENT DETAIL ===")
# For each overlap question, show all annotator judgments side by side
overlap_by_qid = defaultdict(list)
for sess in sessions:
    sid = sess.get("session_id", "?")
    if "ov" not in sid:
        continue
    pid = sess.get("prolific_pid", "?")[:10]
    attn_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
    for q in sess.get("data", []):
        qid = q["id"]
        if qid in attn_qids:
            continue
        ev_judgments = {}
        for ev in q.get("events", []):
            st = ev.get("current_status") or "?"
            rr = ev.get("reject_reason") or ""
            ev_judgments[ev["id"]] = f"{st}({rr})" if rr else st
        overlap_by_qid[qid].append({"sid": sid, "pid": pid, "judgments": ev_judgments})

for qid, annotators in sorted(overlap_by_qid.items()):
    print(f"\nQuestion: {qid[:60]}")
    all_event_ids = list(dict.fromkeys(eid for a in annotators for eid in a["judgments"]))
    header = f"  {'Event':<35} " + "  ".join(f"{a['sid']}({a['pid'][:6]})" for a in annotators)
    print(header)
    agree_count = 0
    total_count = 0
    for eid in all_event_ids:
        labels = [a["judgments"].get(eid, "--") for a in annotators]
        total_count += 1
        unanimous = len(set(labels)) == 1
        if unanimous:
            agree_count += 1
        flag = "" if unanimous else " <-- DISAGREE"
        print(f"  {eid[:35]:<35} {('  '.join(labels))}{flag}")
    print(f"  Agreement: {agree_count}/{total_count} ({agree_count/total_count*100:.0f}%)")
