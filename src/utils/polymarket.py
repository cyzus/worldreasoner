"""
Polymarket utility functions for fetching market data and price history.
"""

import aiohttp
from typing import List, Dict, Any, Optional
from src.utils.logging import logger


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
