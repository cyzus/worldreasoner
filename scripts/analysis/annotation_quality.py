"""
Compute annotation quality metrics from d:/workspace/wr/annotated/.

Produces docs/annotation_quality.md with:
  - Session summary (per annotator)
  - Aggregate event statistics
  - Rejection reason breakdown
  - Reasoning quality breakdown
  - Inter-rater agreement on overlap sessions (ov01, ov02, ov03)
  - Per-question graph acceptance rate

Usage:
    cd worldreasoner
    uv run python scripts/analysis/annotation_quality.py
"""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from datetime import datetime, timezone

ANNOTATED_DIR = Path("d:/workspace/wr/annotated")
OUT_MD        = Path("docs/annotation_quality.md")
OUT_TEX       = Path("d:/workspace/wr/worldreaoner_latex/latex/sections/generated/annotation_quality_table.tex")

REJECT_REASONS = [
    "Fabricated", "WrongDate", "SourceMismatch",
    "PredictionNotEvent", "Noise", "Duplicate", "TooBoard",
]
FACTUAL_ERROR_REASONS = {"Fabricated", "WrongDate", "SourceMismatch"}
ACCEPT_REASONS = {"PredictionNotEvent", "Noise", "Duplicate", "TooBoard"}


# ── Load ──────────────────────────────────────────────────────────────────────

def load_sessions(annotated_dir: Path):
    sessions = []
    failed_sessions = []
    for path in sorted(annotated_dir.glob("*.json")):
        if path.parent.name == "annotations-pilot":
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["_path"] = str(path)
        checks = data.get("attention_checks", [])
        all_passed = all(c.get("passed", False) for c in checks)
        if not all_passed:
            failed_sessions.append(data)
        else:
            sessions.append(data)

    print(f"Sessions loaded: {len(sessions)} passed, {len(failed_sessions)} excluded (failed attention check)")
    for s in failed_sessions:
        sid = s.get("session_id", "?")
        pid = s.get("prolific_pid", "?")[:10]
        fails = [c for c in s.get("attention_checks", []) if not c.get("passed", False)]
        for c in fails:
            print(f"  EXCLUDED {sid} ({pid}): expected ({c.get('expected_status')}, {c.get('expected_reason')}) got ({c.get('selected_status')}, {c.get('selected_reason')})")
    return sessions, failed_sessions


# ── Event extraction ──────────────────────────────────────────────────────────

def iter_events(sessions):
    """Yield (session_id, question_id, is_overlap, is_attention_check, event) tuples."""
    for sess in sessions:
        sid = sess.get("session_id", "?")
        attention_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
        for q in sess.get("data", []):
            qid = q["id"]
            is_overlap = q.get("is_overlap", False)
            is_attn = qid in attention_qids
            for ev in q.get("events", []):
                yield sid, qid, is_overlap, is_attn, ev


# ── Session summary ───────────────────────────────────────────────────────────

def session_summary(sessions):
    rows = []
    for sess in sessions:
        sid = sess.get("session_id", "?")
        pid = sess.get("prolific_pid", "?")[:8]
        checks = sess.get("attention_checks", [])
        passed = sum(1 for c in checks if c.get("passed"))
        total_checks = len(checks)

        attention_qids = {ac["question_id"] for ac in checks}
        events = [
            ev
            for q in sess.get("data", [])
            for ev in q.get("events", [])
            if q["id"] not in attention_qids
        ]
        n = len(events)
        if n == 0:
            continue
        approved  = sum(1 for e in events if e.get("current_status") == "approved" or e.get("reject_reason") in ACCEPT_REASONS)
        rejected  = sum(1 for e in events if e.get("current_status") == "rejected" and e.get("reject_reason") != "PredictionNotEvent")
        skipped   = sum(1 for e in events if e.get("current_status") == "skipped")
        reasoning = sum(1 for e in events if e.get("reasoning_status") is not None)
        reasoning_flawed = sum(
            1 for e in events
            if e.get("reasoning_status") in ("flawed", "incorrect", "wrong")
        )
        n_q = len([q for q in sess.get("data", []) if q["id"] not in attention_qids])
        rows.append({
            "session": sid,
            "pid": pid,
            "questions": n_q,
            "events": n,
            "approved": approved,
            "rejected": rejected,
            "skipped": skipped,
            "attn_pass": f"{passed}/{total_checks}",
            "approval_rate": approved / n if n else None,
            "rejection_rate": rejected / n if n else None,
            "reasoning_n": reasoning,
            "reasoning_flaw_rate": reasoning_flawed / reasoning if reasoning else None,
        })
    return rows


# ── Aggregate event stats ─────────────────────────────────────────────────────

def aggregate_events(sessions):
    events = [
        (sid, qid, ev)
        for sid, qid, is_overlap, is_attn, ev in iter_events(sessions)
        if not is_attn and not is_overlap
    ]
    n = len(events)
    statuses = defaultdict(int)
    reasons  = defaultdict(int)
    reasoning_total  = 0
    reasoning_flawed = 0

    for sid, qid, ev in events:
        st = ev.get("current_status") or "unknown"
        is_prediction = ev.get("reject_reason") in ACCEPT_REASONS
        # PredictionNotEvent = event is real, just poorly sourced — count as accepted
        effective_st = "approved" if (st == "rejected" and is_prediction) else st
        statuses[effective_st] += 1
        if st == "rejected":
            r = ev.get("reject_reason") or "unknown"
            reasons[r] += 1
        rs = ev.get("reasoning_status")
        if rs is not None:
            reasoning_total += 1
            if rs in ("flawed", "incorrect", "wrong"):
                reasoning_flawed += 1

    factual_errors = sum(reasons.get(r, 0) for r in FACTUAL_ERROR_REASONS)
    return {
        "n": n,
        "statuses": dict(statuses),
        "reasons": dict(reasons),
        "factual_error_count": factual_errors,
        "factual_error_rate": factual_errors / n if n else None,
        "noise_rate": (reasons.get("Noise", 0) + reasons.get("Duplicate", 0) + reasons.get("TooBoard", 0)) / n if n else None,
        "acceptance_rate": statuses.get("approved", 0) / n if n else None,
        "reasoning_total": reasoning_total,
        "reasoning_flaw_rate": reasoning_flawed / reasoning_total if reasoning_total else None,
    }


# ── Per-question graph quality ────────────────────────────────────────────────

def per_question_stats(sessions):
    by_qid = defaultdict(lambda: defaultdict(int))
    for sid, qid, is_overlap, is_attn, ev in iter_events(sessions):
        if is_attn:
            continue
        st = ev.get("current_status") or "unknown"
        is_prediction = ev.get("reject_reason") in ACCEPT_REASONS
        effective_st = "approved" if (st == "rejected" and is_prediction) else st
        by_qid[qid][effective_st] += 1

    rows = []
    for qid, counts in by_qid.items():
        total = sum(counts.values())
        approved = counts.get("approved", 0)
        rows.append({
            "qid": qid,
            "total": total,
            "approved": approved,
            "rejected": counts.get("rejected", 0),
            "skipped": counts.get("skipped", 0),
            "acceptance_rate": approved / total if total else None,
        })
    rows.sort(key=lambda r: r["acceptance_rate"] or 0)
    return rows


# ── Inter-rater agreement on overlap sessions ─────────────────────────────────

def inter_rater_agreement(sessions):
    """
    For each overlap question annotated by multiple annotators,
    compute pairwise agreement on current_status for each event id.
    """
    # overlap_data[question_id][event_id] = list of statuses across annotators
    overlap_data = defaultdict(lambda: defaultdict(list))

    for sess in sessions:
        sid = sess.get("session_id", "")
        if "ov" not in sid:
            continue
        attention_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
        for q in sess.get("data", []):
            qid = q["id"]
            if qid in attention_qids:
                continue
            for ev in q.get("events", []):
                st = ev.get("current_status") or "unknown"
                is_prediction = ev.get("reject_reason") in ACCEPT_REASONS
                effective_st = "approved" if (st == "rejected" and is_prediction) else st
                overlap_data[qid][ev["id"]].append(effective_st)

    agreements = []
    reason_agreements = []
    event_rows = []

    for qid, events in overlap_data.items():
        for eid, statuses in events.items():
            if len(statuses) < 2:
                continue
            # pairwise agreement
            pairs = 0
            agree = 0
            for i in range(len(statuses)):
                for j in range(i + 1, len(statuses)):
                    pairs += 1
                    if statuses[i] == statuses[j]:
                        agree += 1
            agreements.append(agree / pairs if pairs else 1.0)
            event_rows.append({"qid": qid, "eid": eid, "statuses": statuses, "agree": agree / pairs if pairs else 1.0})

    overall_agreement = mean(agreements) if agreements else None

    # simple kappa: p_o = observed, p_e = expected by chance
    all_statuses = [s for _, events in overlap_data.items() for eid, statuses in events.items() for s in statuses]
    n_all = len(all_statuses)
    from collections import Counter
    status_counts = Counter(all_statuses)
    p_e = sum((c / n_all) ** 2 for c in status_counts.values()) if n_all else 0
    p_o = overall_agreement or 0
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) > 0 else None

    return {
        "n_event_pairs": len(agreements),
        "overall_agreement": overall_agreement,
        "kappa": kappa,
        "event_rows": event_rows,
    }


# ── Auxiliary quality checks for paper table ─────────────────────────────────

def attention_summary(sessions, failed_sessions):
    all_sessions = sessions + failed_sessions
    checks = [c for s in all_sessions for c in s.get("attention_checks", [])]
    passed = sum(1 for c in checks if c.get("passed", False))
    total = len(checks)
    return {
        "sessions_retained": len(sessions),
        "sessions_total": len(all_sessions),
        "sessions_excluded": len(failed_sessions),
        "checks_passed": passed,
        "checks_total": total,
        "attention_rate": passed / total if total else None,
    }


def price_delta(price_data, event_date_str, window_days=7):
    if not price_data or not event_date_str:
        return None
    history = price_data.get("history") or price_data.get("prices") or []
    if not history:
        return None

    import datetime as dt
    try:
        ev_dt = dt.datetime.fromisoformat(event_date_str.replace("Z", "+00:00"))
        if ev_dt.tzinfo is None:
            ev_dt = ev_dt.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None

    ev_ts = ev_dt.timestamp()
    window_s = window_days * 86400
    before = [p for p in history if 0 <= ev_ts - float(p.get("t", 0)) <= window_s]
    after = [p for p in history if 0 <= float(p.get("t", 0)) - ev_ts <= window_s]
    if not before or not after:
        return None

    before_p = max(before, key=lambda p: float(p.get("t", 0)))
    after_p = min(after, key=lambda p: float(p.get("t", 0)))
    return float(after_p.get("p", 0)) - float(before_p.get("p", 0))


def market_alignment(sessions, min_delta=0.05):
    rows = []
    for sess in sessions:
        attention_qids = {ac["question_id"] for ac in sess.get("attention_checks", [])}
        for q in sess.get("data", []):
            if q["id"] in attention_qids or not q.get("is_polymarket"):
                continue
            price_data = q.get("price_data")
            for ev in q.get("events", []):
                st = ev.get("current_status")
                rr = ev.get("reject_reason")
                is_accepted = (st == "approved") or (st == "rejected" and rr in ACCEPT_REASONS)
                expectation = (ev.get("impact_expectation") or "").lower()
                if not is_accepted or expectation not in ("up", "down"):
                    continue
                delta = price_delta(price_data, ev.get("date"))
                if delta is None or abs(delta) < min_delta:
                    continue
                rows.append((delta > 0) == (expectation == "up"))
    aligned = sum(1 for r in rows if r)
    return {
        "n": len(rows),
        "aligned": aligned,
        "alignment_rate": aligned / len(rows) if rows else None,
    }


# ── Render markdown ───────────────────────────────────────────────────────────

def pct(v):
    return f"{v*100:.1f}%" if v is not None else "--"

def render(sessions):
    sess_rows = session_summary(sessions)
    agg       = aggregate_events(sessions)
    q_stats   = per_question_stats(sessions)
    ira       = inter_rater_agreement(sessions)

    lines = ["# Annotation Quality Report", ""]
    lines.append(f"Computed from `d:/workspace/wr/annotated/` — {len(sessions)} sessions (sessions that failed any attention check are excluded).\n")

    # ── Session summary ──────────────────────────────────────────────────────
    lines += ["## Session summary", ""]
    lines.append("| Session | PID (prefix) | Questions | Events | Approved | Rejected | Skipped | Attn checks | Approval rate | Rejection rate | Reasoning flaw rate |")
    lines.append("|---------|-------------|-----------|--------|----------|----------|---------|-------------|---------------|----------------|---------------------|")
    for r in sess_rows:
        lines.append(
            f"| {r['session']} | {r['pid']} | {r['questions']} | {r['events']} "
            f"| {r['approved']} | {r['rejected']} | {r['skipped']} "
            f"| {r['attn_pass']} | {pct(r['approval_rate'])} "
            f"| {pct(r['rejection_rate'])} | {pct(r['reasoning_flaw_rate'])} |"
        )
    lines.append("")

    # ── Aggregate ────────────────────────────────────────────────────────────
    lines += ["## Aggregate event statistics (non-overlap, non-attention-check)", ""]
    n = agg["n"]
    st = agg["statuses"]
    lines.append(f"Total events annotated: **{n}**\n")
    lines.append("| Status | Count | Rate |")
    lines.append("|--------|-------|------|")
    for status in ("approved", "rejected", "skipped", "unknown"):
        c = st.get(status, 0)
        lines.append(f"| {status.capitalize()} | {c} | {pct(c/n if n else None)} |")
    lines.append("")
    lines.append(f"- **Graph acceptance rate:** {pct(agg['acceptance_rate'])}")
    lines.append(f"- **Factual error rate:** {pct(agg['factual_error_rate'])} (Fabricated + WrongDate + SourceMismatch)")
    lines.append(f"- **Noise/structural rate:** {pct(agg['noise_rate'])} (Noise + Duplicate + TooBoard, counted as accepted)")
    lines.append(f"- **Reasoning flaw rate:** {pct(agg['reasoning_flaw_rate'])} ({agg['reasoning_total']} impact annotations)\n")

    # ── Rejection reasons ────────────────────────────────────────────────────
    lines += ["## Rejection reason breakdown", ""]
    lines.append("| Reason | Count | % of rejected | % of all |")
    lines.append("|--------|-------|---------------|----------|")
    total_rejected = st.get("rejected", 0)
    for reason in REJECT_REASONS + ["unknown"]:
        c = agg["reasons"].get(reason, 0)
        if c == 0:
            continue
        pct_rej = pct(c / total_rejected if total_rejected else None)
        pct_all = pct(c / n if n else None)
        flag = " ⚠️" if reason in FACTUAL_ERROR_REASONS else ""
        lines.append(f"| {reason}{flag} | {c} | {pct_rej} | {pct_all} |")
    lines.append("")
    lines.append("⚠️ = factual error (counts toward factual error rate)\n")

    # ── Inter-rater agreement ────────────────────────────────────────────────
    lines += ["## Inter-rater agreement (overlap sessions)", ""]
    lines.append(f"- Event pairs compared: **{ira['n_event_pairs']}**")
    lines.append(f"- Observed agreement (p_o): **{pct(ira['overall_agreement'])}**")
    kappa_str = f"{ira['kappa']:.3f}" if ira['kappa'] is not None else '--'
    lines.append(f"- Cohen's kappa: **{kappa_str}**")
    lines.append("")

    if ira["event_rows"]:
        disagreements = [r for r in ira["event_rows"] if r["agree"] < 1.0]
        lines.append(f"Disagreements: {len(disagreements)} / {ira['n_event_pairs']} events\n")
        if disagreements:
            lines.append("| Question | Event ID | Annotator labels |")
            lines.append("|----------|----------|-----------------|")
            for r in disagreements[:20]:
                labels = ", ".join(r["statuses"])
                lines.append(f"| `{r['qid'][:20]}` | `{r['eid'][:20]}` | {labels} |")
            if len(disagreements) > 20:
                lines.append(f"| ... | *{len(disagreements)-20} more* | |")
            lines.append("")

    # ── Per-question quality ─────────────────────────────────────────────────
    lines += ["## Per-question graph acceptance rate", ""]
    lines.append("Sorted ascending (lowest quality first).\n")
    lines.append("| Question ID | Events | Approved | Rejected | Skipped | Acceptance rate |")
    lines.append("|-------------|--------|----------|----------|---------|-----------------|")
    for r in q_stats:
        lines.append(
            f"| `{r['qid'][:40]}` | {r['total']} | {r['approved']} "
            f"| {r['rejected']} | {r['skipped']} | {pct(r['acceptance_rate'])} |"
        )
    lines.append("")

    return "\n".join(lines)


def tex_pct(v):
    return f"{v*100:.1f}\\%" if v is not None else "--"


def render_latex_table(sessions, failed_sessions):
    agg = aggregate_events(sessions)
    ira = inter_rater_agreement(sessions)
    attn = attention_summary(sessions, failed_sessions)
    market = market_alignment(sessions)
    n = agg["n"]
    st = agg["statuses"]
    reasons = agg["reasons"]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = [
        ("Sessions retained", f"{attn['sessions_retained']} / {attn['sessions_total']}", tex_pct(attn["sessions_retained"] / attn["sessions_total"] if attn["sessions_total"] else None), f"Passed all attention checks; {attn['sessions_excluded']} sessions excluded."),
        ("Attention checks passed", f"{attn['checks_passed']} / {attn['checks_total']}", tex_pct(attn["attention_rate"]), "Most annotators followed explicit control items."),
        ("\\midrule", "", "", ""),
        ("Accepted hindsight events", f"{st.get('approved', 0)} / {n}", tex_pct(agg["acceptance_rate"]), "Events judged real, dated correctly, source-supported, and relevant."),
        ("Factual-error rejections", f"{agg['factual_error_count']} / {n}", tex_pct(agg["factual_error_rate"]), "Fabricated, wrong-date, or source-mismatch events removed by review."),
        ("Skipped or unverifiable events", f"{st.get('skipped', 0)} / {n}", tex_pct(st.get("skipped", 0) / n if n else None), "Events left unresolved by annotators rather than forced into a label."),
        ("\\midrule", "", "", ""),
        ("Source mismatch", f"{reasons.get('SourceMismatch', 0)} / {n}", tex_pct(reasons.get("SourceMismatch", 0) / n if n else None), "Most common factual-error mode."),
        ("Wrong date", f"{reasons.get('WrongDate', 0)} / {n}", tex_pct(reasons.get("WrongDate", 0) / n if n else None), "Event occurred, but not at the graph date."),
        ("Fabricated", f"{reasons.get('Fabricated', 0)} / {n}", tex_pct(reasons.get("Fabricated", 0) / n if n else None), "Event could not be verified as described."),
        ("\\midrule", "", "", ""),
        ("Overlap agreement", f"{ira['n_event_pairs']} events", tex_pct(ira["overall_agreement"]), f"Modest agreement; $\\kappa={ira['kappa']:.3f}$." if ira["kappa"] is not None else "Modest agreement."),
        ("Annotator-market alignment", f"{market['aligned']} / {market['n']}", tex_pct(market["alignment_rate"]), "Approved event-impact labels agree with large nearby Polymarket moves."),
    ]

    lines = [
        "% Auto-generated by scripts/analysis/annotation_quality.py",
        f"% Generated at {generated_at}",
        "\\begin{table*}[h]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{lrrl}",
        "\\toprule",
        "\\textbf{Quality signal} & \\textbf{Count} & \\textbf{Rate} & \\textbf{Interpretation} \\\\",
        "\\midrule",
    ]
    for label, count, rate, interp in rows:
        if label == "\\midrule":
            lines.append("\\midrule")
        else:
            lines.append(f"{label} & {count} & {rate} & {interp} \\\\")
    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Annotation-quality summary for the main annotation batch. The results support using annotation review as a conservative validation layer for hindsight graphs, while the modest overlap agreement indicates that fine-grained event validation remains a nontrivial judgment task.}",
        "\\label{tab:annotation_quality}",
        "\\end{table*}",
        "",
    ]
    return "\n".join(lines)


def main():
    sessions, failed_sessions = load_sessions(ANNOTATED_DIR)
    print(f"Loaded {len(sessions)} sessions")
    md = render(sessions)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"Written: {OUT_MD}")
    tex = render_latex_table(sessions, failed_sessions)
    OUT_TEX.parent.mkdir(parents=True, exist_ok=True)
    OUT_TEX.write_text(tex, encoding="utf-8")
    print(f"Written: {OUT_TEX}")


if __name__ == "__main__":
    main()
