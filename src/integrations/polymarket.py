"""
Polymarket utility functions for fetching market data and price history.
"""

import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from src.utils.logging import logger


def _detect_turning_points_local(
    sorted_history: List[Dict[str, Any]],
    min_change_pct: float = 5.0,
    lookback_window: int = 5,
    lookahead_window: int = 5,
    min_time_between_points_hours: float = 6.0,
) -> List[Dict[str, Any]]:
    """Original local peak/trough turning point detector."""
    if not sorted_history or len(sorted_history) < 3:
        return []

    n_points = len(sorted_history)
    effective_lookback = min(lookback_window, max(2, (n_points - 1) // 3))
    effective_lookahead = min(lookahead_window, max(2, (n_points - 1) // 3))

    turning_points = []
    min_time_gap = min_time_between_points_hours * 3600

    for i in range(effective_lookback, len(sorted_history) - effective_lookahead):
        current = sorted_history[i]
        current_price = current["p"]
        current_time = current["t"]

        lookback_prices = [
            sorted_history[j]["p"] for j in range(i - effective_lookback, i)
        ]
        lookahead_prices = [
            sorted_history[j]["p"] for j in range(i + 1, i + effective_lookahead + 1)
        ]

        first_lookback_price = sorted_history[i - effective_lookback]["p"]
        last_lookahead_price = sorted_history[i + effective_lookahead]["p"]

        is_peak = current_price >= max(lookback_prices) and current_price >= max(
            lookahead_prices
        )

        is_trough = current_price <= min(lookback_prices) and current_price <= min(
            lookahead_prices
        )

        if not (is_peak or is_trough):
            continue

        change_before = (current_price - first_lookback_price) * 100
        change_after = (last_lookahead_price - current_price) * 100

        if is_peak:
            if change_before <= 0 or change_after >= 0:
                continue
            significance = abs(change_before) + abs(change_after)
        else:
            if change_before >= 0 or change_after <= 0:
                continue
            significance = abs(change_before) + abs(change_after)

        if significance < min_change_pct:
            continue

        candidate = {
            "timestamp": current_time,
            "price": current_price,
            "type": "peak" if is_peak else "trough",
            "change_before": round(change_before, 2),
            "change_after": round(change_after, 2),
            "significance": round(significance, 2),
        }

        if turning_points:
            last_time = turning_points[-1]["timestamp"]
            if current_time - last_time < min_time_gap:
                if significance > turning_points[-1]["significance"]:
                    turning_points[-1] = candidate
                continue

        turning_points.append(candidate)

    turning_points.sort(key=lambda x: x["significance"], reverse=True)
    return turning_points


def _detect_turning_points_pelt_bic(
    sorted_history: List[Dict[str, Any]],
    min_change_pct: float = 5.0,
    lookback_window: int = 5,
    lookahead_window: int = 5,
    min_time_between_points_hours: float = 6.0,
    pelt_min_segment_points: int = 5,
    pelt_jump: int = 1,
    pelt_penalty_scale: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Detect turning points using PELT changepoint segmentation with a BIC-style penalty.

    This method first finds regime boundaries with PELT, then extracts local peaks/troughs
    around those boundaries and applies the same reversal/significance checks as the
    original heuristic detector.
    """
    if not sorted_history or len(sorted_history) < 3:
        return []

    try:
        import numpy as np
        import ruptures as rpt
    except ImportError:
        logger.warning(
            "ruptures not installed; falling back to local turning-point detection"
        )
        return _detect_turning_points_local(
            sorted_history=sorted_history,
            min_change_pct=min_change_pct,
            lookback_window=lookback_window,
            lookahead_window=lookahead_window,
            min_time_between_points_hours=min_time_between_points_hours,
        )

    n_points = len(sorted_history)
    effective_lookback = min(lookback_window, max(2, (n_points - 1) // 3))
    effective_lookahead = min(lookahead_window, max(2, (n_points - 1) // 3))
    min_time_gap = min_time_between_points_hours * 3600

    prices = np.array([p["p"] for p in sorted_history], dtype=float)
    signal = prices.reshape(-1, 1)

    # Robust noise estimate from first differences (MAD), with std fallback.
    diffs = np.diff(prices)
    if diffs.size > 0:
        mad = np.median(np.abs(diffs - np.median(diffs)))
        sigma = mad / 0.6745 if mad > 0 else float(np.std(diffs))
    else:
        sigma = 0.0
    if sigma <= 1e-12:
        sigma = float(np.std(prices))
    if sigma <= 1e-12:
        sigma = 1e-6

    # BIC-style penalty for mean-shift segmentation (scaled for tuning).
    penalty = max(1e-8, pelt_penalty_scale * np.log(max(n_points, 2)) * (sigma**2))

    algo = rpt.Pelt(
        model="l2",
        min_size=max(2, pelt_min_segment_points),
        jump=max(1, pelt_jump),
    ).fit(signal)

    try:
        breakpoints = algo.predict(pen=penalty)
    except Exception as exc:
        logger.warning(
            f"PELT turning-point detection failed ({type(exc).__name__}); "
            "falling back to local turning-point detection"
        )
        return _detect_turning_points_local(
            sorted_history=sorted_history,
            min_change_pct=min_change_pct,
            lookback_window=lookback_window,
            lookahead_window=lookahead_window,
            min_time_between_points_hours=min_time_between_points_hours,
        )
    boundaries = [b for b in breakpoints[:-1] if 0 < b < n_points]
    if not boundaries:
        return []

    turning_points = []
    for b in boundaries:
        left_anchor = max(0, b - effective_lookback)
        right_anchor = min(n_points - 1, b + effective_lookahead)
        if right_anchor - left_anchor < 2:
            continue

        window_prices = prices[left_anchor : right_anchor + 1]
        peak_idx = int(left_anchor + int(np.argmax(window_prices)))
        trough_idx = int(left_anchor + int(np.argmin(window_prices)))

        peak_price = prices[peak_idx]
        trough_price = prices[trough_idx]
        left_price = prices[left_anchor]
        right_price = prices[right_anchor]

        peak_before = (peak_price - left_price) * 100
        peak_after = (right_price - peak_price) * 100
        peak_valid = peak_before > 0 and peak_after < 0
        peak_sig = abs(peak_before) + abs(peak_after) if peak_valid else 0.0

        trough_before = (trough_price - left_price) * 100
        trough_after = (right_price - trough_price) * 100
        trough_valid = trough_before < 0 and trough_after > 0
        trough_sig = abs(trough_before) + abs(trough_after) if trough_valid else 0.0

        candidate = None
        if peak_valid and peak_sig >= min_change_pct and peak_sig >= trough_sig:
            candidate = {
                "timestamp": sorted_history[peak_idx]["t"],
                "price": float(peak_price),
                "type": "peak",
                "change_before": round(float(peak_before), 2),
                "change_after": round(float(peak_after), 2),
                "significance": round(float(peak_sig), 2),
            }
        elif trough_valid and trough_sig >= min_change_pct:
            candidate = {
                "timestamp": sorted_history[trough_idx]["t"],
                "price": float(trough_price),
                "type": "trough",
                "change_before": round(float(trough_before), 2),
                "change_after": round(float(trough_after), 2),
                "significance": round(float(trough_sig), 2),
            }

        if candidate is None:
            continue

        if turning_points:
            last_time = turning_points[-1]["timestamp"]
            if candidate["timestamp"] - last_time < min_time_gap:
                if candidate["significance"] > turning_points[-1]["significance"]:
                    turning_points[-1] = candidate
                continue

        turning_points.append(candidate)

    turning_points.sort(key=lambda x: x["significance"], reverse=True)
    return turning_points


def detect_turning_points(
    price_history: List[Dict[str, Any]],
    min_change_pct: float = 5.0,
    lookback_window: int = 5,
    lookahead_window: int = 5,
    min_time_between_points_hours: float = 6.0,
    method: str = "pelt_bic",
    pelt_min_segment_points: int = 5,
    pelt_jump: int = 1,
    pelt_penalty_scale: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Detect major turning points in a price curve.

    A turning point is a local maximum or minimum where the price reverses
    direction significantly. This identifies moments where market sentiment
    shifted substantially.

    Args:
        price_history: List of price points [{"t": timestamp_seconds, "p": price_0_to_1}, ...]
        min_change_pct: Minimum price change (in percentage points) to qualify as a turning point
        lookback_window: Number of points to look back for comparison (adaptive for sparse data)
        lookahead_window: Number of points to look ahead for confirmation (adaptive for sparse data)
        min_time_between_points_hours: Minimum hours between detected turning points
        method: Turning point method: "pelt_bic" (default) or "local"
        pelt_min_segment_points: Minimum segment size for PELT (used when method="pelt_bic")
        pelt_jump: PELT jump parameter for speed/precision tradeoff
        pelt_penalty_scale: Multiplier for BIC-style penalty (higher = fewer changepoints)

    Returns:
        List of turning points with metadata:
        [
            {
                "timestamp": int,  # Unix timestamp in seconds
                "price": float,    # Price at turning point (0-1)
                "type": str,       # "peak" or "trough"
                "change_before": float,  # Price change leading to this point (percentage points)
                "change_after": float,   # Price change after this point (percentage points)
                "significance": float,   # Combined significance score
            },
            ...
        ]
    """
    if not price_history or len(price_history) < 3:
        return []

    sorted_history = sorted(price_history, key=lambda x: x["t"])

    normalized_method = (method or "pelt_bic").strip().lower()
    if normalized_method in {"local", "heuristic"}:
        return _detect_turning_points_local(
            sorted_history=sorted_history,
            min_change_pct=min_change_pct,
            lookback_window=lookback_window,
            lookahead_window=lookahead_window,
            min_time_between_points_hours=min_time_between_points_hours,
        )

    return _detect_turning_points_pelt_bic(
        sorted_history=sorted_history,
        min_change_pct=min_change_pct,
        lookback_window=lookback_window,
        lookahead_window=lookahead_window,
        min_time_between_points_hours=min_time_between_points_hours,
        pelt_min_segment_points=pelt_min_segment_points,
        pelt_jump=pelt_jump,
        pelt_penalty_scale=pelt_penalty_scale,
    )


def detect_sharp_movements(
    price_history: List[Dict[str, Any]],
    min_change_pct: float = 10.0,
    window_hours: float = 24.0,
) -> List[Dict[str, Any]]:
    """
    Detect sharp price movements within a time window.

    Finds periods where the price moved significantly in a short time,
    indicating sudden market reactions to events.

    Args:
        price_history: List of price points [{"t": timestamp_seconds, "p": price_0_to_1}, ...]
        min_change_pct: Minimum price change (in percentage points) to qualify
        window_hours: Time window to measure movement (in hours)

    Returns:
        List of sharp movements:
        [
            {
                "start_timestamp": int,
                "end_timestamp": int,
                "start_price": float,
                "end_price": float,
                "change_pct": float,  # Percentage points change
                "direction": str,     # "up" or "down"
                "duration_hours": float,
            },
            ...
        ]
    """
    if not price_history or len(price_history) < 2:
        return []

    sorted_history = sorted(price_history, key=lambda x: x["t"])
    window_seconds = window_hours * 3600

    movements = []

    for i, start_point in enumerate(sorted_history):
        start_time = start_point["t"]
        start_price = start_point["p"]

        # Find all points within the window
        for j in range(i + 1, len(sorted_history)):
            end_point = sorted_history[j]
            end_time = end_point["t"]

            if end_time - start_time > window_seconds:
                break

            end_price = end_point["p"]
            change_pct = (end_price - start_price) * 100  # Convert to percentage points

            if abs(change_pct) >= min_change_pct:
                duration_hours = (end_time - start_time) / 3600

                movements.append(
                    {
                        "start_timestamp": start_time,
                        "end_timestamp": end_time,
                        "start_price": round(start_price, 4),
                        "end_price": round(end_price, 4),
                        "change_pct": round(change_pct, 2),
                        "direction": "up" if change_pct > 0 else "down",
                        "duration_hours": round(duration_hours, 2),
                    }
                )

    # Remove overlapping movements, keeping the most significant
    if not movements:
        return []

    # Sort by absolute change
    movements.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    # Filter overlapping
    filtered = []
    for movement in movements:
        overlaps = False
        for existing in filtered:
            # Check if time ranges overlap significantly
            overlap_start = max(
                movement["start_timestamp"], existing["start_timestamp"]
            )
            overlap_end = min(movement["end_timestamp"], existing["end_timestamp"])
            if overlap_end > overlap_start:
                # There's overlap - skip this one if less significant
                overlaps = True
                break
        if not overlaps:
            filtered.append(movement)

    return filtered[:20]  # Limit to top 20 movements


def detect_lead_changes(
    price_history: List[Dict[str, Any]],
    threshold: float = 0.5,
    min_time_between_changes_hours: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Detect when the leading outcome changes (price crosses threshold).

    For binary markets, this detects when the market flips from "Yes likely"
    to "No likely" (or vice versa) - i.e., when price crosses 50%.

    Args:
        price_history: List of price points [{"t": timestamp_seconds, "p": price_0_to_1}, ...]
        threshold: Price level that defines lead change (default: 0.5 for binary markets)
        min_time_between_changes_hours: Minimum hours between detected changes

    Returns:
        List of lead changes:
        [
            {
                "timestamp": int,           # When the crossover happened
                "price": float,             # Price at crossover
                "direction": str,           # "above" or "below" (new state)
                "previous_price": float,    # Price before crossover
                "time_above_threshold": float,  # Hours spent above threshold before (if crossing below)
            },
            ...
        ]
    """
    if not price_history or len(price_history) < 2:
        return []

    sorted_history = sorted(price_history, key=lambda x: x["t"])
    min_time_gap = min_time_between_changes_hours * 3600

    lead_changes = []
    last_change_time = None

    for i in range(1, len(sorted_history)):
        prev_point = sorted_history[i - 1]
        curr_point = sorted_history[i]

        prev_price = prev_point["p"]
        curr_price = curr_point["p"]
        curr_time = curr_point["t"]

        # Check for threshold crossing
        crossed_above = prev_price < threshold <= curr_price
        crossed_below = prev_price >= threshold > curr_price

        if not (crossed_above or crossed_below):
            continue

        # Check time gap from last change
        if last_change_time and (curr_time - last_change_time) < min_time_gap:
            continue

        # Calculate how long the market was in the previous state
        time_in_previous_state = None
        if i >= 2:
            # Look back to find when it entered the previous state
            for j in range(i - 2, -1, -1):
                check_price = sorted_history[j]["p"]
                if crossed_above and check_price >= threshold:
                    # Was above, find when it went below
                    time_in_previous_state = (
                        curr_time - sorted_history[j + 1]["t"]
                    ) / 3600
                    break
                elif crossed_below and check_price < threshold:
                    # Was below, find when it went above
                    time_in_previous_state = (
                        curr_time - sorted_history[j + 1]["t"]
                    ) / 3600
                    break

        lead_changes.append(
            {
                "timestamp": curr_time,
                "price": round(curr_price, 4),
                "direction": "above" if crossed_above else "below",
                "previous_price": round(prev_price, 4),
                "time_in_previous_state_hours": round(time_in_previous_state, 2)
                if time_in_previous_state
                else None,
            }
        )

        last_change_time = curr_time

    return lead_changes


def analyze_price_curve(
    price_history: List[Dict[str, Any]],
    min_turning_point_change: float = 5.0,
    min_sharp_movement_change: float = 10.0,
    lead_change_threshold: float = 0.5,
    turning_point_method: str = "pelt_bic",
) -> Dict[str, Any]:
    """
    Comprehensive analysis of a price curve, detecting turning points, sharp movements,
    and lead changes.

    Args:
        price_history: List of price points [{"t": timestamp_seconds, "p": price_0_to_1}, ...]
        min_turning_point_change: Minimum change for turning points (percentage points)
        min_sharp_movement_change: Minimum change for sharp movements (percentage points)
        lead_change_threshold: Price threshold for lead changes (default: 0.5 for binary markets)
        turning_point_method: Turning point method: "pelt_bic" (default) or "local"

    Returns:
        {
            "turning_points": [...],
            "sharp_movements": [...],
            "lead_changes": [...],
            "summary": {
                "total_points": int,
                "time_range_days": float,
                "price_range": {"min": float, "max": float},
                "volatility": float,  # Standard deviation of prices
                "trend": str,  # "up", "down", or "sideways"
                "lead_changes_count": int,  # Number of times lead changed
            }
        }
    """
    if not price_history:
        return {
            "turning_points": [],
            "sharp_movements": [],
            "lead_changes": [],
            "summary": None,
        }

    sorted_history = sorted(price_history, key=lambda x: x["t"])
    prices = [p["p"] for p in sorted_history]

    # Calculate summary statistics
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) / len(prices)

    # Volatility (standard deviation)
    variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
    volatility = variance**0.5

    # Time range
    time_range_seconds = sorted_history[-1]["t"] - sorted_history[0]["t"]
    time_range_days = time_range_seconds / 86400

    # Trend (compare first 10% to last 10%)
    n = len(prices)
    first_segment = prices[: max(1, n // 10)]
    last_segment = prices[-(max(1, n // 10)) :]
    avg_first = sum(first_segment) / len(first_segment)
    avg_last = sum(last_segment) / len(last_segment)

    trend_change = avg_last - avg_first
    if trend_change > 0.05:
        trend = "up"
    elif trend_change < -0.05:
        trend = "down"
    else:
        trend = "sideways"

    # Detect turning points
    turning_points = detect_turning_points(
        price_history,
        min_change_pct=min_turning_point_change,
        method=turning_point_method,
    )

    # Detect sharp movements
    sharp_movements = detect_sharp_movements(
        price_history,
        min_change_pct=min_sharp_movement_change,
    )

    # Detect lead changes (when market crosses threshold)
    lead_changes = detect_lead_changes(
        price_history,
        threshold=lead_change_threshold,
    )

    return {
        "turning_points": turning_points,
        "sharp_movements": sharp_movements,
        "lead_changes": lead_changes,
        "summary": {
            "total_points": len(price_history),
            "time_range_days": round(time_range_days, 1),
            "price_range": {
                "min": round(min_price, 4),
                "max": round(max_price, 4),
            },
            "volatility": round(volatility, 4),
            "trend": trend,
            "lead_changes_count": len(lead_changes),
        },
    }


async def get_price_history(
    token_id: str,
    interval: str = "max",
    session: Optional[aiohttp.ClientSession] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    fidelity: int = 30,
) -> List[Dict[str, Any]]:
    """
    Fetch price history for a Polymarket token.

    Args:
        token_id: Token ID (hex with 0x prefix, or decimal string)
        interval: Time interval - "1m", "1w", "1d", "6h", "1h", "all", or "max" (deprecated, use start_ts/end_ts)
        session: Optional aiohttp session to reuse
        start_ts: Start timestamp in seconds (Unix epoch). If provided with end_ts, overrides interval.
        end_ts: End timestamp in seconds (Unix epoch). If provided with start_ts, overrides interval.
        fidelity: Price point granularity (default: 30). Higher values = more data points.
                  Note: Different intervals have minimum fidelity requirements.

    Returns:
        List of price points: [{"t": timestamp_ms, "p": price_0_to_1}, ...]
        Returns empty list if fetch fails or no data available.
    """
    # Build URL with timestamp parameters if provided, otherwise use interval
    if start_ts is not None and end_ts is not None:
        # Validate time range - API rejects ranges > ~90 days
        range_days = (end_ts - start_ts) / (24 * 60 * 60)
        if range_days > 90:
            logger.warning(
                f"Time range too long for timestamp API ({range_days:.1f} days), "
                f"using interval='{interval}' instead"
            )
            # Fall back to interval-based query
            if interval in ["all", "max"] and fidelity < 720:
                fidelity = 720
            url = f"https://clob.polymarket.com/prices-history?market={token_id}&interval={interval}&fidelity={fidelity}"
        else:
            # Use timestamp-based API for short ranges
            url = f"https://clob.polymarket.com/prices-history?startTs={start_ts}&market={token_id}&fidelity={fidelity}&endTs={end_ts}"
    else:
        # Ensure fidelity for interval-based queries
        if interval == "1w" and fidelity < 5:
            fidelity = 5
        elif interval in ["all", "max"]:
            if fidelity < 720:
                fidelity = 720
        elif interval in ["1d", "6h", "1h"] and fidelity < 60:
            fidelity = 60

        url = f"https://clob.polymarket.com/prices-history?market={token_id}&interval={interval}&fidelity={fidelity}"

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                history = data.get("history", [])
                logger.info(f"Fetched {len(history)} price points for token {token_id}")
                return history
            else:
                logger.warning(
                    f"Failed to fetch price history for {token_id}: HTTP {response.status}"
                )
                return []
    except Exception as e:
        logger.error(f"Error fetching price history for {token_id}: {e}")
        return []
    finally:
        if close_session:
            await session.close()


async def get_price_history_for_market(
    clob_token_ids: List[str],
    interval: str = "1d",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    fidelity: int = 30,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch price history for multiple tokens (outcomes) in a market.

    Args:
        clob_token_ids: List of token IDs for the market outcomes
        interval: Time interval for price history (deprecated, use start_ts/end_ts)
        start_ts: Start timestamp in seconds (Unix epoch). If provided with end_ts, overrides interval.
        end_ts: End timestamp in seconds (Unix epoch). If provided with start_ts, overrides interval.
        fidelity: Price point granularity (default: 30)

    Returns:
        Dict mapping token_id to price history list
        Example: {"0x123...": [{"t": 1234567890000, "p": 0.45}, ...], ...}
    """
    results = {}

    async with aiohttp.ClientSession() as session:
        for token_id in clob_token_ids:
            history = await get_price_history(
                token_id,
                interval=interval,
                session=session,
                start_ts=start_ts,
                end_ts=end_ts,
                fidelity=fidelity,
            )
            if history:
                results[token_id] = history

    return results


async def analyze_question_price_curve(
    question,
    db,
    min_turning_point_change: float = 5.0,
    create_events: bool = True,
    max_events: int = 10,
) -> Dict[str, Any]:
    """
    Analyze price curve for a question and optionally create Event records.

    This is a convenience function for use by pipelines that combines
    fetching price history, detecting turning points, and creating events.

    Args:
        question: Question object (must have polymarket metadata with clob_token_ids)
        db: Database instance for saving events
        min_turning_point_change: Minimum change for turning points (percentage points)
        create_events: If True, creates Event records for turning points
        max_events: Maximum number of events to create

    Returns:
        {
            "turning_points": [...],
            "sharp_movements": [...],
            "summary": {...},
            "created_events": [Event, ...],  # Event objects if create_events=True
        }
    """
    import uuid
    from src.domain.models import Event

    metadata = question.metadata or {}
    clob_token_ids = metadata.get("clob_token_ids", [])

    if not clob_token_ids:
        logger.warning(f"Question {question.id} has no CLOB token IDs")
        return {
            "turning_points": [],
            "sharp_movements": [],
            "summary": None,
            "created_events": [],
        }

    # Fetch full price history
    price_history = await get_price_history_for_market(
        clob_token_ids,
        interval="max",
        fidelity=720,
    )

    if not price_history:
        logger.warning(f"No price history available for question {question.id}")
        return {
            "turning_points": [],
            "sharp_movements": [],
            "summary": None,
            "created_events": [],
        }

    # Use first token (primary outcome)
    first_token_id = clob_token_ids[0]
    primary_history = price_history.get(first_token_id, [])

    if not primary_history:
        return {
            "turning_points": [],
            "sharp_movements": [],
            "summary": None,
            "created_events": [],
        }

    # Run analysis
    analysis = analyze_price_curve(
        primary_history,
        min_turning_point_change=min_turning_point_change,
        min_sharp_movement_change=min_turning_point_change * 2,
    )

    created_events = []

    if create_events and analysis["turning_points"]:
        from src.domain.models.event import EventType, EventStatus

        options = metadata.get("options", ["Yes", "No"])
        primary_outcome = options[0] if options else "Yes"

        # Get question domain if available
        question_domain = getattr(question, "domain", "general")

        for tp in analysis["turning_points"][:max_events]:
            event_time = datetime.fromtimestamp(tp["timestamp"], tz=timezone.utc)

            if tp["type"] == "peak":
                title = (
                    f"Market peak: {primary_outcome} reached {tp['price'] * 100:.1f}%"
                )
                description = (
                    f"Market probability for '{primary_outcome}' peaked at {tp['price'] * 100:.1f}%, "
                    f"rising {tp['change_before']:.1f}pp before reversing down {abs(tp['change_after']):.1f}pp. "
                    f"This turning point indicates a significant shift in market sentiment."
                )
            else:
                title = f"Market trough: {primary_outcome} dropped to {tp['price'] * 100:.1f}%"
                description = (
                    f"Market probability for '{primary_outcome}' reached a low of {tp['price'] * 100:.1f}%, "
                    f"dropping {abs(tp['change_before']):.1f}pp before recovering {tp['change_after']:.1f}pp. "
                    f"This turning point indicates a significant shift in market sentiment."
                )

            event = Event(
                id=str(uuid.uuid4()),
                title=title,
                description=description,
                occurred_date=event_time,
                event_type=EventType.INDICATOR,  # Use INDICATOR type for market signals
                domain=question_domain,
                status=EventStatus.OCCURRED,
                extracted_for_question_id=question.id,
                metadata={
                    "turning_point_type": tp["type"],
                    "price": tp["price"],
                    "change_before": tp["change_before"],
                    "change_after": tp["change_after"],
                    "significance": tp["significance"],
                    "auto_detected": True,
                    "source": "polymarket_price_analysis",
                },
            )

            db.save(Event, event)
            created_events.append(event)
            logger.info(
                f"Created turning point event for {question.id}: "
                f"{tp['type']} at {event_time.isoformat()}"
            )

    logger.info(
        f"Price analysis for {question.id}: "
        f"{len(analysis['turning_points'])} turning points, "
        f"{len(created_events)} events created"
    )

    return {
        "turning_points": analysis["turning_points"],
        "sharp_movements": analysis["sharp_movements"],
        "summary": analysis["summary"],
        "created_events": created_events,
    }
