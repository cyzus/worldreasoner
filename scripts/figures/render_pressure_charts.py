"""Render CausalPressureChart as SVG for paper figures.

Fetches Polymarket price history live, pulls hindsight graph events and
impact scores from combined.db, and writes one SVG per question.

Usage:
    uv run python scripts/figures/render_pressure_charts.py \
        --db combined.db \
        --out-dir experiments/figures/pressure_charts \
        --questions <qid1> <qid2> ...   # or omit to use candidate list
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Candidate question IDs (edit to taste) ─────────────────────────────────
CANDIDATES = [
    # (id, short_label)
    ("polymarket_0xf65fdce18270522fac3f549a4b8812ac7d0e7fdc71dcac8d91caa4d8460aa877",
     "starship_ft11"),
    ("polymarket_0x13c8546e1600edd62efa2c0530d99214cbbb3e9eb27c3e72fd09e50e874f17b3",
     "nvidia_earnings"),
    ("polymarket_0xdb46432765f4f6e902618d2746b289d4fb4a80c0d0cb9697c2dfda186cd0e0c9",
     "microstrategy_margin"),
    ("polymarket_0x677c19032d9fc09658a4b05826e3efd656d725394bc2f5a4ea4b2c4e41a2077a",
     "chatgpt_1b_users"),
    ("polymarket_event_179295",
     "vietnam_president"),
    ("polymarket_event_45883",
     "fed_january"),
]

DIRECTION_SIGN  = {"positive": 1, "negative": -1, "neutral": 0, "mixed": 0}
DIRECTION_COLOR = {"positive": "#22c55e", "negative": "#ef4444",
                   "neutral": "#94a3b8", "mixed": "#a855f7"}

# ── SVG layout constants ────────────────────────────────────────────────────
W, H   = 680, 240
PL, PR_BASE, PT, PB = 52, 20, 28, 42
PRICE_RIGHT_PAD = 56   # extra right padding when price series present


def fmt_date(ts_ms: float) -> str:
    d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return d.strftime("%b %d %Y")


def x_scale(t, min_t, max_t, pl, iw):
    return pl + (t - min_t) / max(max_t - min_t, 1) * iw


def render_svg(question_text: str, events_with_impacts, price_series,
               price_label: str, resolution_ts_ms, ground_truth: str) -> str:
    """Render one SVG string.

    events_with_impacts: list of dicts with keys:
        date_ts_ms, title, direction, magnitude, confidence, contribution
    price_series: list of {t: ts_ms, p: 0-1} or None
    """
    has_price = bool(price_series)
    pr = PRICE_RIGHT_PAD if has_price else PR_BASE
    iw = W - PL - pr
    ih = H - PT - PB

    # ── Build cumulative pressure trajectory ──────────────────────────────
    pts = sorted(events_with_impacts, key=lambda e: e["date_ts_ms"])
    cumulative = 0.0
    for p in pts:
        cumulative += p["contribution"]
        p["cumulative"] = cumulative

    if not pts:
        return ""   # nothing to draw

    # ── Time domain ───────────────────────────────────────────────────────
    traj_ts   = [p["date_ts_ms"] for p in pts]
    price_ts  = [p["t"] for p in price_series] if has_price else []
    res_ts    = [resolution_ts_ms] if resolution_ts_ms else []
    all_ts    = traj_ts + price_ts + res_ts
    min_t, max_t = min(all_ts), max(all_ts)

    def xof(t): return x_scale(t, min_t, max_t, PL, iw)

    # ── Pressure Y axis ───────────────────────────────────────────────────
    pressures = [p["cumulative"] for p in pts]
    max_abs   = max(abs(min(pressures)), abs(max(pressures)), 0.1)
    zero_y    = PT + ih / 2

    def y_pressure(v): return PT + ih / 2 - (v / max_abs) * (ih / 2)
    def y_price(p):    return PT + ih - p * ih

    # ── Step path ─────────────────────────────────────────────────────────
    step_parts = [f"M {xof(min_t):.1f} {y_pressure(0):.1f}"]
    prev = 0.0
    for p in pts:
        x = xof(p["date_ts_ms"])
        step_parts.append(
            f"L {x:.1f} {y_pressure(prev):.1f} L {x:.1f} {y_pressure(p['cumulative']):.1f}"
        )
        prev = p["cumulative"]
    step_parts.append(f"L {xof(max_t):.1f} {y_pressure(prev):.1f}")
    step_d = " ".join(step_parts)
    area_d = (f"{step_d} L {xof(max_t):.1f} {zero_y:.1f} "
              f"L {xof(min_t):.1f} {zero_y:.1f} Z")

    net = pts[-1]["cumulative"]
    net_color = ("#22c55e" if net > 0.05 else "#ef4444" if net < -0.05 else "#94a3b8")

    # ── Price polyline ─────────────────────────────────────────────────────
    price_poly = (" ".join(f"{xof(p['t']):.1f},{y_price(p['p']):.1f}"
                           for p in price_series)
                  if has_price else None)

    # ── Y tick values ──────────────────────────────────────────────────────
    y_ticks  = [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]
    p_ticks  = [0.0, 0.25, 0.5, 0.75, 1.0]

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Arial, sans-serif">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    # title (truncated)
    title_text = question_text if len(question_text) <= 80 else question_text[:77] + "…"
    lines.append(
        f'<text x="{PL}" y="16" font-size="11" font-weight="600" fill="#1e293b">'
        f'{title_text}</text>'
    )

    # ── Grid + left Y axis ────────────────────────────────────────────────
    for v in y_ticks:
        y = y_pressure(v)
        dash = "none" if v == 0 else "4,3"
        sw   = "1.2"  if v == 0 else "0.7"
        col  = "#adb5bd" if v == 0 else "#e9ecef"
        lines.append(
            f'<line x1="{PL}" y1="{y:.1f}" x2="{W - pr}" y2="{y:.1f}" '
            f'stroke="{col}" stroke-width="{sw}" stroke-dasharray="{dash}"/>'
        )
        label = "0" if v == 0 else (f"+{v:.2f}" if v > 0 else f"{v:.2f}")
        lines.append(
            f'<text x="{PL - 4}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'font-size="9" fill="#64748b">{label}</text>'
        )
    # left axis label
    mid_y = PT + ih / 2
    lines.append(
        f'<text transform="rotate(-90) translate(-{mid_y:.0f},{PL - 38})" '
        f'text-anchor="middle" font-size="9" fill="#64748b">causal pressure</text>'
    )

    # ── Right Y axis (price) ───────────────────────────────────────────────
    if has_price:
        for v in p_ticks:
            y = y_price(v)
            lines.append(
                f'<text x="{W - pr + 4}" y="{y + 3.5:.1f}" '
                f'font-size="9" fill="#3b82f6">{int(v * 100)}%</text>'
            )
            if v == 0.5:
                lines.append(
                    f'<line x1="{PL}" y1="{y:.1f}" x2="{W - pr}" y2="{y:.1f}" '
                    f'stroke="#3b82f6" stroke-width="0.5" stroke-dasharray="3,4" stroke-opacity="0.35"/>'
                )
        # right axis label
        lines.append(
            f'<text transform="rotate(90) translate({mid_y:.0f},-{W - pr + 42})" '
            f'text-anchor="middle" font-size="9" fill="#3b82f6">'
            f'{price_label[:24]}</text>'
        )

    # ── Pressure area + step line ──────────────────────────────────────────
    area_fill = "#22c55e" if net >= 0 else "#ef4444"
    lines.append(f'<path d="{area_d}" fill="{area_fill}" fill-opacity="0.07"/>')
    lines.append(
        f'<path d="{step_d}" fill="none" stroke="{net_color}" stroke-width="2"/>'
    )

    # ── Price curve ────────────────────────────────────────────────────────
    if price_poly:
        lines.append(
            f'<polyline points="{price_poly}" fill="none" stroke="#3b82f6" '
            f'stroke-width="1.5" stroke-opacity="0.75"/>'
        )

    # ── Resolution line ────────────────────────────────────────────────────
    if resolution_ts_ms:
        rx = xof(resolution_ts_ms)
        lines.append(
            f'<line x1="{rx:.1f}" y1="{PT}" x2="{rx:.1f}" y2="{PT + ih}" '
            f'stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="5,3"/>'
        )
        lines.append(
            f'<text x="{rx + 3:.1f}" y="{PT + 10}" font-size="9" '
            f'fill="#f59e0b" font-weight="600">resolved</text>'
        )

    # ── Event dots ────────────────────────────────────────────────────────
    for p in pts:
        cx = xof(p["date_ts_ms"])
        cy = y_pressure(p["cumulative"])
        color = DIRECTION_COLOR.get(p["direction"], "#94a3b8")
        lines.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" '
            f'fill="{color}" stroke="#fff" stroke-width="1.5"/>'
        )

    # ── X axis labels ──────────────────────────────────────────────────────
    base_y = PT + ih + 14
    lines.append(
        f'<text x="{xof(min_t):.1f}" y="{base_y}" font-size="9" '
        f'fill="#adb5bd" text-anchor="middle">{fmt_date(min_t)}</text>'
    )
    lines.append(
        f'<text x="{xof(max_t):.1f}" y="{base_y}" font-size="9" '
        f'fill="#adb5bd" text-anchor="middle">{fmt_date(max_t)}</text>'
    )
    # mid tick if span > 60 days
    span_days = (max_t - min_t) / 86_400_000
    if span_days > 60:
        mid_t = (min_t + max_t) / 2
        lines.append(
            f'<text x="{xof(mid_t):.1f}" y="{base_y}" font-size="9" '
            f'fill="#adb5bd" text-anchor="middle">{fmt_date(mid_t)}</text>'
        )

    # ── Legend ─────────────────────────────────────────────────────────────
    leg_y = H - 10
    leg_x = PL
    for direction, color in DIRECTION_COLOR.items():
        lines.append(
            f'<circle cx="{leg_x + 5}" cy="{leg_y - 3}" r="4" fill="{color}"/>'
        )
        lines.append(
            f'<text x="{leg_x + 12}" y="{leg_y}" font-size="9" fill="#6c757d">'
            f'{direction}</text>'
        )
        leg_x += 68
    if has_price:
        lines.append(
            f'<line x1="{leg_x}" y1="{leg_y - 3}" x2="{leg_x + 18}" y2="{leg_y - 3}" '
            f'stroke="#3b82f6" stroke-width="2" stroke-opacity="0.75"/>'
        )
        lines.append(
            f'<text x="{leg_x + 22}" y="{leg_y}" font-size="9" fill="#6c757d">'
            f'market price</text>'
        )

    # ── Net pressure badge ─────────────────────────────────────────────────
    net_str = f"Net {'+' if net > 0 else ''}{net:.3f}"
    badge_x = W - pr - 80
    lines.append(
        f'<rect x="{badge_x}" y="{PT - 2}" width="72" height="16" rx="4" '
        f'fill="{net_color}" fill-opacity="0.12"/>'
    )
    lines.append(
        f'<text x="{badge_x + 36}" y="{PT + 10}" text-anchor="middle" '
        f'font-size="10" font-weight="700" fill="{net_color}">{net_str}</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


def load_events_for_question(conn, qid: str, ground_truth: str):
    """Load hindsight graph events + impacts for one question."""
    rows = conn.execute("""
        SELECT e.id, e.title, e.occurred_date, e.predicted_date,
               eoi.impact_direction, eoi.impact_magnitude, eoi.confidence
        FROM events e
        JOIN event_outcome_impacts eoi ON eoi.event_id = e.id
        WHERE e.extracted_for_question_id = ?
          AND e.is_outcome = 0
        ORDER BY COALESCE(e.occurred_date, e.predicted_date)
    """, [qid]).fetchall()

    seen = set()
    events = []
    for row in rows:
        eid, title, occ, pred, direction, magnitude, confidence = row
        # prefer actual outcome row; fall back to matching ground truth scenario
        if eid in seen:
            continue
        date_str = occ or pred
        if not date_str:
            continue
        try:
            ts_ms = datetime.fromisoformat(
                date_str.replace("Z", "+00:00")
            ).timestamp() * 1000
        except Exception:
            continue
        sign = DIRECTION_SIGN.get(direction, 0)
        mag  = magnitude or 0.0
        conf = confidence or 1.0
        events.append({
            "date_ts_ms":   ts_ms,
            "title":        title or eid,
            "direction":    direction or "neutral",
            "magnitude":    mag,
            "confidence":   conf,
            "contribution": sign * mag * conf,
        })
        seen.add(eid)

    return events


async def fetch_price(qid: str, clob_token_ids: list):
    """Fetch price history from Polymarket CLOB API."""
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from src.integrations.polymarket import get_price_history_for_market
    try:
        data = await get_price_history_for_market(
            clob_token_ids, interval="max", fidelity=720
        )
        return data   # {token_id: [{t: sec, p: 0-1}, ...]}
    except Exception as e:
        print(f"  [warn] price fetch failed: {e}")
        return {}


async def process_question(conn, qid: str, label: str, out_dir: Path):
    row = conn.execute(
        "SELECT question_text, resolution_date, ground_truth, metadata FROM questions WHERE id = ?",
        [qid]
    ).fetchone()
    if not row:
        print(f"  [skip] {qid} not found in DB")
        return None

    question_text, res_date, ground_truth, meta_str = row
    meta = {}
    try:
        meta = json.loads(meta_str) if meta_str else {}
    except Exception:
        pass

    clob_token_ids = meta.get("clob_token_ids", [])
    outcomes       = meta.get("outcomes", [])

    print(f"  Loading events for {label}...")
    events = load_events_for_question(conn, qid, ground_truth)
    if not events:
        print(f"  [skip] {label}: no events with impacts")
        return None
    print(f"  {len(events)} events loaded")

    # Fetch price history
    price_series = None
    price_label  = "Market Probability"
    if clob_token_ids:
        print(f"  Fetching price history ({len(clob_token_ids)} tokens)...")
        raw = await fetch_price(qid, clob_token_ids)
        if raw:
            # Pick the first token (or "Yes" token if present)
            token_id = clob_token_ids[0]
            pts = raw.get(token_id, [])
            if pts:
                # convert seconds → ms
                price_series = [{"t": p["t"] * 1000, "p": p["p"]}
                                for p in sorted(pts, key=lambda x: x["t"])]
                price_label  = outcomes[0] if outcomes else "Yes"
                print(f"  {len(price_series)} price points")
    else:
        print(f"  [info] no CLOB token IDs — pressure chart only")

    # Resolution timestamp
    res_ts_ms = None
    if res_date:
        try:
            res_ts_ms = datetime.fromisoformat(
                str(res_date).replace("Z", "+00:00")
            ).timestamp() * 1000
        except Exception:
            pass

    # Stats summary for candidate selection
    directions = [e["direction"] for e in events]
    pos = directions.count("positive")
    neg = directions.count("negative")
    net = sum(e["contribution"] for e in events)
    print(f"  pos={pos} neg={neg} net={net:.3f} price={'yes' if price_series else 'no'}")

    svg = render_svg(question_text, events, price_series, price_label,
                     res_ts_ms, ground_truth)
    if not svg:
        print(f"  [skip] {label}: SVG empty")
        return None

    out_path = out_dir / f"{label}.svg"
    out_path.write_text(svg, encoding="utf-8")
    print(f"  -> {out_path}")
    return out_path


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",       default="combined.db")
    parser.add_argument("--out-dir",  default="experiments/figures/pressure_charts")
    parser.add_argument("--questions", nargs="*",
                        help="Question IDs to render (space-separated). "
                             "Omit to use built-in candidate list.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)

    if args.questions:
        targets = [(qid, qid.split("_")[-1][:20]) for qid in args.questions]
    else:
        targets = CANDIDATES

    results = []
    for qid, label in targets:
        print(f"\n=== {label} ({qid[:50]}...) ===")
        path = await process_question(conn, qid, label, out_dir)
        if path:
            results.append((label, path))

    conn.close()

    print(f"\nDone. {len(results)} SVGs written to {out_dir}/")
    for label, path in results:
        print(f"  {label}: {path}")


if __name__ == "__main__":
    asyncio.run(main())
