"""
Simple example: Fetch Polymarket price history.

Shows how to get the price curve over time for a resolved Polymarket market.
"""

import asyncio
import json
import aiohttp
from src.utils.logging import logger


async def get_price_history(token_id: str, interval: str = "max"):
    """
    Fetch price history for a Polymarket token.

    Args:
        token_id: Token ID (hex with 0x prefix, or decimal string)
        interval: "max", "1d", "1h", or "5m"

    Returns:
        List of price points: [{"t": timestamp, "p": price}, ...]
    """
    url = f"https://clob.polymarket.com/prices-history?market={token_id}&interval={interval}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(data)
                return data.get('history', [])
            return []


async def main():
    """Example: Fetch a resolved market and its price history."""

    async with aiohttp.ClientSession() as session:
        # Fetch a recent resolved market
        url = "https://gamma-api.polymarket.com/markets"
        params = {"limit": 10, "closed": "true", "order": "closedTime", "ascending": "false"}

        async with session.get(url, params=params) as response:
            markets = await response.json()

        # Find a market with CLOB token IDs
        for market in markets:
            clob_ids_raw = market.get('clobTokenIds', '[]')
            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw

            if clob_ids:
                logger.info(f"\n{'='*80}")
                logger.info(f"Market: {market.get('question')}")
                logger.info(f"Closed: {market.get('closedTime')}")
                logger.info(f"Final Price: {market.get('lastTradePrice')}")
                logger.info(f"{'='*80}\n")
                logger.info(f"CLOB Token IDs: {clob_ids}")

                # Fetch price history
                logger.info(f"Fetching price history...")
                history = await get_price_history(clob_ids[0], interval="1d")

                if history:
                    logger.info(f"✓ Found {len(history)} price points")
                    logger.info(f"  First: t={history[0]['t']}, p={history[0]['p']}")
                    logger.info(f"  Last:  t={history[-1]['t']}, p={history[-1]['p']}")
                else:
                    logger.info(f"× No price history available")

                break  # Found one, exit
        else:
            logger.warning("No markets with CLOB token IDs found")


if __name__ == "__main__":
    asyncio.run(main())
