"""
Polymarket utility functions for fetching market data and price history.
"""

import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from src.utils.logging import logger


def detect_turning_points(
    price_history: List[Dict[str, Any]],
    min_change_pct: float = 5.0,
    lookback_window: int = 5,
    lookahead_window: int = 5,
    min_time_between_points_hours: float = 6.0,
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

    # Sort by timestamp to ensure chronological order
    sorted_history = sorted(price_history, key=lambda x: x["t"])

    # Adapt window sizes for sparse data
    # Need at least 3 points (1 before, current, 1 after) to detect a turning point
    n_points = len(sorted_history)
    # Scale windows based on data density, minimum of 2 points each side
    effective_lookback = min(lookback_window, max(2, (n_points - 1) // 3))
    effective_lookahead = min(lookahead_window, max(2, (n_points - 1) // 3))

    turning_points = []
    min_time_gap = min_time_between_points_hours * 3600  # Convert to seconds

    for i in range(effective_lookback, len(sorted_history) - effective_lookahead):
        current = sorted_history[i]
        current_price = current["p"]
        current_time = current["t"]

        # Get prices in lookback and lookahead windows
        lookback_prices = [sorted_history[j]["p"] for j in range(i - effective_lookback, i)]
        lookahead_prices = [sorted_history[j]["p"] for j in range(i + 1, i + effective_lookahead + 1)]

        # Get the first and last prices in each window for change calculation
        first_lookback_price = sorted_history[i - effective_lookback]["p"]
        last_lookahead_price = sorted_history[i + effective_lookahead]["p"]

        # Check if local maximum (peak) - higher than all surrounding points
        is_peak = (
            current_price >= max(lookback_prices) and
            current_price >= max(lookahead_prices)
        )

        # Check if local minimum (trough) - lower than all surrounding points
        is_trough = (
            current_price <= min(lookback_prices) and
            current_price <= min(lookahead_prices)
        )

        if not (is_peak or is_trough):
            continue

        # Calculate change from first lookback to current (before)
        # and from current to last lookahead (after)
        change_before = (current_price - first_lookback_price) * 100
        change_after = (last_lookahead_price - current_price) * 100

        # For a true peak: price went up, then went down
        # change_before should be positive, change_after should be negative
        if is_peak:
            if change_before <= 0 or change_after >= 0:
                continue  # Not a real reversal
            # Significance is the total swing (up then down)
            significance = abs(change_before) + abs(change_after)

        # For a true trough: price went down, then went up
        # change_before should be negative, change_after should be positive
        else:  # is_trough
            if change_before >= 0 or change_after <= 0:
                continue  # Not a real reversal
            # Significance is the total swing (down then up)
            significance = abs(change_before) + abs(change_after)

        # Check if this turning point is significant enough
        if significance < min_change_pct:
            continue

        # Check time gap from last turning point
        if turning_points:
            last_time = turning_points[-1]["timestamp"]
            if current_time - last_time < min_time_gap:
                # Keep the more significant one
                if significance > turning_points[-1]["significance"]:
                    turning_points[-1] = {
                        "timestamp": current_time,
                        "price": current_price,
                        "type": "peak" if is_peak else "trough",
                        "change_before": round(change_before, 2),
                        "change_after": round(change_after, 2),
                        "significance": round(significance, 2),
                    }
                continue

        turning_points.append({
            "timestamp": current_time,
            "price": current_price,
            "type": "peak" if is_peak else "trough",
            "change_before": round(change_before, 2),
            "change_after": round(change_after, 2),
            "significance": round(significance, 2),
        })

    # Sort by significance and return top turning points
    turning_points.sort(key=lambda x: x["significance"], reverse=True)

    return turning_points


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

                movements.append({
                    "start_timestamp": start_time,
                    "end_timestamp": end_time,
                    "start_price": round(start_price, 4),
                    "end_price": round(end_price, 4),
                    "change_pct": round(change_pct, 2),
                    "direction": "up" if change_pct > 0 else "down",
                    "duration_hours": round(duration_hours, 2),
                })

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
            overlap_start = max(movement["start_timestamp"], existing["start_timestamp"])
            overlap_end = min(movement["end_timestamp"], existing["end_timestamp"])
            if overlap_end > overlap_start:
                # There's overlap - skip this one if less significant
                overlaps = True
                break
        if not overlaps:
            filtered.append(movement)

    return filtered[:20]  # Limit to top 20 movements


def analyze_price_curve(
    price_history: List[Dict[str, Any]],
    min_turning_point_change: float = 5.0,
    min_sharp_movement_change: float = 10.0,
) -> Dict[str, Any]:
    """
    Comprehensive analysis of a price curve, detecting turning points and sharp movements.

    Args:
        price_history: List of price points [{"t": timestamp_seconds, "p": price_0_to_1}, ...]
        min_turning_point_change: Minimum change for turning points (percentage points)
        min_sharp_movement_change: Minimum change for sharp movements (percentage points)

    Returns:
        {
            "turning_points": [...],
            "sharp_movements": [...],
            "summary": {
                "total_points": int,
                "time_range_days": float,
                "price_range": {"min": float, "max": float},
                "volatility": float,  # Standard deviation of prices
                "trend": str,  # "up", "down", or "sideways"
            }
        }
    """
    if not price_history:
        return {
            "turning_points": [],
            "sharp_movements": [],
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
    volatility = variance ** 0.5

    # Time range
    time_range_seconds = sorted_history[-1]["t"] - sorted_history[0]["t"]
    time_range_days = time_range_seconds / 86400

    # Trend (compare first 10% to last 10%)
    n = len(prices)
    first_segment = prices[:max(1, n // 10)]
    last_segment = prices[-(max(1, n // 10)):]
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
    )

    # Detect sharp movements
    sharp_movements = detect_sharp_movements(
        price_history,
        min_change_pct=min_sharp_movement_change,
    )

    return {
        "turning_points": turning_points,
        "sharp_movements": sharp_movements,
        "summary": {
            "total_points": len(price_history),
            "time_range_days": round(time_range_days, 1),
            "price_range": {
                "min": round(min_price, 4),
                "max": round(max_price, 4),
            },
            "volatility": round(volatility, 4),
            "trend": trend,
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
                title = f"Market peak: {primary_outcome} reached {tp['price']*100:.1f}%"
                description = (
                    f"Market probability for '{primary_outcome}' peaked at {tp['price']*100:.1f}%, "
                    f"rising {tp['change_before']:.1f}pp before reversing down {abs(tp['change_after']):.1f}pp. "
                    f"This turning point indicates a significant shift in market sentiment."
                )
            else:
                title = f"Market trough: {primary_outcome} dropped to {tp['price']*100:.1f}%"
                description = (
                    f"Market probability for '{primary_outcome}' reached a low of {tp['price']*100:.1f}%, "
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
