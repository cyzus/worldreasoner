"""
Integration test: Polymarket price history with event graph correlation.

Demonstrates the complete end-to-end flow:
1. Fetch a Polymarket question
2. Get its price history
3. Load related events from the graph
4. Correlate price movements with event occurrences
5. Detect turning points in price curves
"""

import asyncio
import json
import aiohttp
from datetime import datetime
from src.utils.logging import logger
from src.integrations.polymarket import (
    get_price_history,
    get_price_history_for_market,
    detect_turning_points,
    detect_sharp_movements,
    analyze_price_curve,
)
from src.pipelines.collection.runner_polymarket import PolymarketRunner
from src.core.database import GenericDatabase


async def test_basic_price_history():
    """Test basic price history fetching (original functionality)."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 1: Basic Price History Fetching")
    logger.info("=" * 80)

    async with aiohttp.ClientSession() as session:
        # Fetch a recent resolved market
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "limit": 10,
            "closed": "true",
            "order": "closedTime",
            "ascending": "false",
            "related_tags": "true",
            "tag_id": "2",
        }
        tag_url = "https://gamma-api.polymarket.com/markets/{id}/tags"
        async with session.get(url, params=params) as response:
            markets = await response.json()

        # Find a market with CLOB token IDs
        for market in markets:
            market_id = market.get("id")
            async with session.get(tag_url.format(id=market_id)) as tag_response:
                tags = await tag_response.json()
                logger.info(f"Tags: {tags}")

            clob_ids_raw = market.get("clobTokenIds", "[]")
            clob_ids = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )

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
                    logger.info("× No price history available")

                return clob_ids, history

        logger.warning("No markets with CLOB token IDs found")
        return [], []


async def test_multi_outcome_price_history():
    """Test fetching price history for multiple outcomes."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Multi-Outcome Price History")
    logger.info("=" * 80)

    async with aiohttp.ClientSession() as session:
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "limit": 20,
            "closed": "true",
            "order": "closedTime",
            "ascending": "false",
        }

        async with session.get(url, params=params) as response:
            markets = await response.json()

        # Find a market with multiple outcomes
        for market in markets:
            clob_ids_raw = market.get("clobTokenIds", "[]")
            clob_ids = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )
            outcomes_raw = market.get("outcomes", "[]")
            outcomes = (
                json.loads(outcomes_raw)
                if isinstance(outcomes_raw, str)
                else outcomes_raw
            )

            if clob_ids and len(clob_ids) > 1:
                logger.info(f"\nMarket: {market.get('question')}")
                logger.info(f"Outcomes: {outcomes}")
                logger.info(f"Token Count: {len(clob_ids)}")

                # Fetch price history for all outcomes
                price_histories = await get_price_history_for_market(
                    clob_ids, interval="1d"
                )

                logger.info(f"✓ Fetched history for {len(price_histories)} outcomes")
                for token_id, history in price_histories.items():
                    idx = clob_ids.index(token_id)
                    outcome_name = (
                        outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"
                    )
                    logger.info(f"  {outcome_name}: {len(history)} price points")

                return outcomes, price_histories

        logger.warning("No multi-outcome markets found")
        return [], {}


async def test_end_to_end_integration():
    """Test complete integration: Polymarket → Database → Event Graph → Frontend."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: End-to-End Integration")
    logger.info("=" * 80)

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
            price_histories = await get_price_history_for_market(
                clob_ids, interval="1d"
            )

            if price_histories:
                logger.info(f"✓ Price history available: {len(price_histories)} tokens")
                for token_id, history in price_histories.items():
                    logger.info(f"  Token {token_id}: {len(history)} points")
                    if history:
                        logger.info(
                            f"    Time range: {datetime.fromtimestamp(history[0]['t'] / 1000)} to {datetime.fromtimestamp(history[-1]['t'] / 1000)}"
                        )

            # 3. Simulate event graph data
            logger.info("\nStep 3: Simulating event graph correlation...")

            # Create mock events within the price history time range
            if price_histories and any(price_histories.values()):
                first_history = next(iter(price_histories.values()))
                start_time = first_history[0]["t"] / 1000  # Convert ms to seconds
                end_time = first_history[-1]["t"] / 1000

                logger.info(
                    f"  Price data time range: {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}"
                )
                logger.info("  Events in this range would be overlaid on the chart")
                logger.info("  Target event (if set) would be highlighted in gold")

                # 4. Demonstrate what the frontend would receive
                logger.info("\nStep 4: Frontend data structure...")
                frontend_data = {
                    "question_id": question.id,
                    "market_id": question.metadata.get("market_id"),
                    "interval": "1d",
                    "price_history": {
                        token_id: history[:5]
                        for token_id, history in price_histories.items()
                    },  # First 5 points for demo
                    "outcomes": question.metadata.get("options", ["Yes", "No"]),
                }
                logger.info(
                    f"  Data structure: {json.dumps({k: (v if k != 'price_history' else '...') for k, v in frontend_data.items()}, indent=2)}"
                )
                logger.info("✓ Frontend would render TimeSeriesChart with this data")
        else:
            logger.warning(
                "  × No CLOB token IDs in metadata (older question or data format)"
            )
    else:
        logger.warning("× No questions fetched from Polymarket")


def test_turning_point_detection():
    """Test turning point detection with synthetic data."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Turning Point Detection (Unit Test)")
    logger.info("=" * 80)

    # Create synthetic price data with clear turning points
    # Pattern: rise -> peak -> fall -> trough -> rise
    base_time = 1700000000  # Nov 2023
    hour = 3600

    # Generate smooth price curve with obvious turning points
    price_history = []

    # Phase 1: Rise from 0.3 to 0.7 (over 24h)
    for i in range(24):
        price_history.append({
            "t": base_time + i * hour,
            "p": 0.3 + (0.4 * i / 24)
        })

    # Phase 2: Peak at 0.7, then fall to 0.4 (over 24h)
    peak_time = base_time + 24 * hour
    for i in range(24):
        price_history.append({
            "t": peak_time + i * hour,
            "p": 0.7 - (0.3 * i / 24)
        })

    # Phase 3: Trough at 0.4, then rise to 0.6 (over 24h)
    trough_time = peak_time + 24 * hour
    for i in range(24):
        price_history.append({
            "t": trough_time + i * hour,
            "p": 0.4 + (0.2 * i / 24)
        })

    logger.info(f"Generated {len(price_history)} price points")
    logger.info(f"Price range: {min(p['p'] for p in price_history):.2f} to {max(p['p'] for p in price_history):.2f}")

    # Detect turning points
    turning_points = detect_turning_points(
        price_history,
        min_change_pct=10.0,  # 10 percentage points
        lookback_window=5,
        lookahead_window=5,
        min_time_between_points_hours=12.0,
    )

    logger.info(f"\nDetected {len(turning_points)} turning points:")
    for tp in turning_points:
        tp_time = datetime.fromtimestamp(tp["timestamp"])
        logger.info(
            f"  {tp['type'].upper()}: price={tp['price']:.2f} at {tp_time}, "
            f"change_before={tp['change_before']:.1f}pp, "
            f"change_after={tp['change_after']:.1f}pp, "
            f"significance={tp['significance']:.1f}"
        )

    # Assertions
    assert len(turning_points) >= 2, f"Expected at least 2 turning points, got {len(turning_points)}"

    # Should have at least one peak
    peaks = [tp for tp in turning_points if tp["type"] == "peak"]
    troughs = [tp for tp in turning_points if tp["type"] == "trough"]

    logger.info(f"\nFound {len(peaks)} peaks and {len(troughs)} troughs")

    if peaks:
        logger.info(f"  Highest peak: {peaks[0]['price']:.2f}")
    if troughs:
        logger.info(f"  Lowest trough: {troughs[0]['price']:.2f}")

    logger.info("✓ Turning point detection test passed!")

    return turning_points


def test_sharp_movement_detection():
    """Test sharp movement detection."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: Sharp Movement Detection (Unit Test)")
    logger.info("=" * 80)

    base_time = 1700000000
    hour = 3600

    # Create data with a sharp drop: 0.6 -> 0.3 in 6 hours
    price_history = []

    # Stable period
    for i in range(12):
        price_history.append({"t": base_time + i * hour, "p": 0.6})

    # Sharp drop
    drop_start = base_time + 12 * hour
    for i in range(6):
        price_history.append({
            "t": drop_start + i * hour,
            "p": 0.6 - (0.3 * i / 6)
        })

    # Stable at lower level
    stable_time = drop_start + 6 * hour
    for i in range(12):
        price_history.append({"t": stable_time + i * hour, "p": 0.3})

    logger.info(f"Generated {len(price_history)} price points with sharp drop")

    # Detect sharp movements
    movements = detect_sharp_movements(
        price_history,
        min_change_pct=15.0,  # 15 percentage points
        window_hours=12.0,
    )

    logger.info(f"\nDetected {len(movements)} sharp movements:")
    for mv in movements:
        start_time = datetime.fromtimestamp(mv["start_timestamp"])
        end_time = datetime.fromtimestamp(mv["end_timestamp"])
        logger.info(
            f"  {mv['direction'].upper()}: {mv['start_price']:.2f} -> {mv['end_price']:.2f} "
            f"({mv['change_pct']:+.1f}pp) over {mv['duration_hours']:.1f}h"
        )

    # Should detect the sharp drop
    down_movements = [m for m in movements if m["direction"] == "down"]
    assert len(down_movements) >= 1, "Should detect at least one downward sharp movement"

    logger.info("✓ Sharp movement detection test passed!")

    return movements


async def test_real_market_turning_points():
    """Test turning point detection on real Polymarket data."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 6: Turning Points on Real Market Data")
    logger.info("=" * 80)

    # Fetch a real market with price history
    clob_ids, history = await test_basic_price_history()

    if not history:
        logger.warning("Skipping real market test - no price history available")
        return None

    logger.info(f"\nAnalyzing real market with {len(history)} price points...")

    # Run full analysis
    analysis = analyze_price_curve(
        history,
        min_turning_point_change=5.0,
        min_sharp_movement_change=10.0,
    )

    logger.info("\nCurve Summary:")
    if analysis["summary"]:
        summary = analysis["summary"]
        logger.info(f"  Time range: {summary['time_range_days']:.1f} days")
        logger.info(f"  Price range: {summary['price_range']['min']:.2f} to {summary['price_range']['max']:.2f}")
        logger.info(f"  Volatility: {summary['volatility']:.4f}")
        logger.info(f"  Trend: {summary['trend']}")

    logger.info(f"\nTurning Points: {len(analysis['turning_points'])}")
    for tp in analysis["turning_points"][:5]:  # Show top 5
        tp_time = datetime.fromtimestamp(tp["timestamp"])
        logger.info(
            f"  {tp['type'].upper()}: {tp['price']*100:.1f}% at {tp_time.strftime('%Y-%m-%d %H:%M')}, "
            f"significance={tp['significance']:.1f}"
        )

    logger.info(f"\nSharp Movements: {len(analysis['sharp_movements'])}")
    for mv in analysis["sharp_movements"][:5]:  # Show top 5
        start_time = datetime.fromtimestamp(mv["start_timestamp"])
        logger.info(
            f"  {mv['direction'].upper()}: {mv['start_price']*100:.1f}% -> {mv['end_price']*100:.1f}% "
            f"({mv['change_pct']:+.1f}pp) at {start_time.strftime('%Y-%m-%d')}"
        )

    logger.info("✓ Real market analysis complete!")

    return analysis


async def main():
    """Run all integration tests."""
    logger.info("\n" + "=" * 80)
    logger.info("POLYMARKET PRICE HISTORY INTEGRATION TESTS")
    logger.info("=" * 80)

    try:
        # Test 1: Basic functionality
        await test_basic_price_history()

        # Test 2: Multi-outcome markets
        # await test_multi_outcome_price_history()

        # Test 3: Complete integration flow
        # await test_end_to_end_integration()

        # Test 4: Turning point detection (unit test)
        test_turning_point_detection()

        # Test 5: Sharp movement detection (unit test)
        test_sharp_movement_detection()

        # Test 6: Real market turning points
        await test_real_market_turning_points()

        logger.info("\n" + "=" * 80)
        logger.info("✓ ALL TESTS COMPLETED")
        logger.info("=" * 80)
    except Exception as e:
        logger.error(f"\n× TEST FAILED: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
