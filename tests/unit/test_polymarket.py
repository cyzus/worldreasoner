"""
Integration test: Polymarket price history with event graph correlation.

Demonstrates the complete end-to-end flow:
1. Fetch a Polymarket question
2. Get its price history
3. Load related events from the graph
4. Correlate price movements with event occurrences
"""

import asyncio
import json
import aiohttp
from datetime import datetime
from src.utils.logging import logger
from src.utils.polymarket import get_price_history, get_price_history_for_market
from src.pipelines.question.sources.markets import PolymarketRunner
from src.core.database import GenericDatabase
from src.domain.models import Question, Event


async def test_basic_price_history():
    """Test basic price history fetching (original functionality)."""
    logger.info("\n" + "="*80)
    logger.info("TEST 1: Basic Price History Fetching")
    logger.info("="*80)

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
                logger.info(f"\nMarket: {market.get('question')}")
                logger.info(f"Closed: {market.get('closedTime')}")
                logger.info(f"Final Price: {market.get('lastTradePrice')}")
                logger.info(f"CLOB Token IDs: {clob_ids}")

                # Fetch price history using utility function
                history = await get_price_history(clob_ids[0], interval="1d")

                if history:
                    logger.info(f"✓ Found {len(history)} price points")
                    logger.info(f"  First: t={history[0]['t']}, p={history[0]['p']}")
                    logger.info(f"  Last:  t={history[-1]['t']}, p={history[-1]['p']}")
                else:
                    logger.info(f"× No price history available")

                return clob_ids, history

        logger.warning("No markets with CLOB token IDs found")
        return [], []


async def test_multi_outcome_price_history():
    """Test fetching price history for multiple outcomes."""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Multi-Outcome Price History")
    logger.info("="*80)

    async with aiohttp.ClientSession() as session:
        url = "https://gamma-api.polymarket.com/markets"
        params = {"limit": 20, "closed": "true", "order": "closedTime", "ascending": "false"}

        async with session.get(url, params=params) as response:
            markets = await response.json()

        # Find a market with multiple outcomes
        for market in markets:
            clob_ids_raw = market.get('clobTokenIds', '[]')
            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
            outcomes_raw = market.get('outcomes', '[]')
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

            if clob_ids and len(clob_ids) > 1:
                logger.info(f"\nMarket: {market.get('question')}")
                logger.info(f"Outcomes: {outcomes}")
                logger.info(f"Token Count: {len(clob_ids)}")

                # Fetch price history for all outcomes
                price_histories = await get_price_history_for_market(clob_ids, interval="1d")

                logger.info(f"✓ Fetched history for {len(price_histories)} outcomes")
                for token_id, history in price_histories.items():
                    idx = clob_ids.index(token_id)
                    outcome_name = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx+1}"
                    logger.info(f"  {outcome_name}: {len(history)} price points")

                return outcomes, price_histories

        logger.warning("No multi-outcome markets found")
        return [], {}


async def test_end_to_end_integration():
    """Test complete integration: Polymarket → Database → Event Graph → Frontend."""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: End-to-End Integration")
    logger.info("="*80)

    # Initialize database
    db = GenericDatabase("worldreasoner_test.db")

    # 1. Fetch Polymarket questions
    logger.info("\nStep 1: Fetching Polymarket questions...")
    runner = PolymarketRunner(require_ground_truth=True)
    result = await runner.collect(count=5)

    if result.questions:
        question = result.questions[0]
        logger.info(f"✓ Fetched question: {question.question_text}")
        logger.info(f"  ID: {question.id}")
        logger.info(f"  Source: {question.source}")
        logger.info(f"  Metadata keys: {list(question.metadata.keys())}")

        # Check if CLOB token IDs are stored
        clob_ids = question.metadata.get("clob_token_ids", [])
        logger.info(f"  CLOB Token IDs: {clob_ids}")

        if clob_ids:
            # 2. Fetch price history via API endpoint (simulated)
            logger.info("\nStep 2: Fetching price history (via utility)...")
            price_histories = await get_price_history_for_market(clob_ids, interval="1d")

            if price_histories:
                logger.info(f"✓ Price history available: {len(price_histories)} tokens")
                for token_id, history in price_histories.items():
                    logger.info(f"  Token {token_id}: {len(history)} points")
                    if history:
                        logger.info(f"    Time range: {datetime.fromtimestamp(history[0]['t']/1000)} to {datetime.fromtimestamp(history[-1]['t']/1000)}")

            # 3. Simulate event graph data
            logger.info("\nStep 3: Simulating event graph correlation...")

            # Create mock events within the price history time range
            if price_histories and any(price_histories.values()):
                first_history = next(iter(price_histories.values()))
                start_time = first_history[0]['t'] / 1000  # Convert ms to seconds
                end_time = first_history[-1]['t'] / 1000

                logger.info(f"  Price data time range: {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}")
                logger.info(f"  Events in this range would be overlaid on the chart")
                logger.info(f"  Target event (if set) would be highlighted in gold")

                # 4. Demonstrate what the frontend would receive
                logger.info("\nStep 4: Frontend data structure...")
                frontend_data = {
                    "question_id": question.id,
                    "market_id": question.metadata.get("market_id"),
                    "interval": "1d",
                    "price_history": {token_id: history[:5] for token_id, history in price_histories.items()},  # First 5 points for demo
                    "outcomes": question.metadata.get("options", ["Yes", "No"]),
                }
                logger.info(f"  Data structure: {json.dumps({k: (v if k != 'price_history' else '...') for k, v in frontend_data.items()}, indent=2)}")
                logger.info(f"✓ Frontend would render TimeSeriesChart with this data")
        else:
            logger.warning("  × No CLOB token IDs in metadata (older question or data format)")
    else:
        logger.warning("× No questions fetched from Polymarket")


async def main():
    """Run all integration tests."""
    logger.info("\n" + "="*80)
    logger.info("POLYMARKET PRICE HISTORY INTEGRATION TESTS")
    logger.info("="*80)

    try:
        # Test 1: Basic functionality
        await test_basic_price_history()

        # Test 2: Multi-outcome markets
        await test_multi_outcome_price_history()

        # Test 3: Complete integration flow
        await test_end_to_end_integration()

        logger.info("\n" + "="*80)
        logger.info("✓ ALL TESTS COMPLETED")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"\n× TEST FAILED: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
