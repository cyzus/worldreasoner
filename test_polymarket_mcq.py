"""Test script to check MCQ (multi-outcome) question availability in Polymarket."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from src.pipelines.question.sources.polymarket_client import PolymarketClient
from src.config.collection_goal import QualityRequirements


async def test_mcq_availability():
    """Check if Polymarket has MCQ questions available."""
    client = PolymarketClient()
    
    # Setup quality requirements for filtering
    quality_req = QualityRequirements(
        min_resolution_days=-90,
        max_resolution_days=0,
        require_resolution_criteria=True,
        min_confidence_score=0.7
    )
    
    # Test 1: Check for multi-outcome markets in general
    print("=" * 80)
    print("TEST 1: Checking for multi-outcome markets (MCQ questions)")
    print("=" * 80)
    
    # Fetch more markets to see what's available
    markets = await client.fetch_markets(
        limit=100,
        require_ground_truth=True,
        quality_requirements=quality_req
    )
    
    print(f"\nTotal markets fetched: {len(markets)}")
    
    # Analyze outcomes (need to parse from raw API)
    binary_count = 0
    multi_outcome_count = 0
    multi_outcome_examples = []
    
    import json
    print(len(markets))
    for market in markets:
        # Parse outcomes from the "outcomes" field (JSON string)
        print(list(market.keys()))
        print(market.get("outcomes"))
        outcomes_str = market.get("outcomes", '["Yes", "No"]')
        try:
            outcomes = json.loads(outcomes_str)
        except:
            outcomes = ["Yes", "No"]
        print(outcomes)
        if len(outcomes) > 2:
            multi_outcome_count += 1
            if len(multi_outcome_examples) < 5:
                multi_outcome_examples.append({
                    'question': market.get('question', 'N/A'),
                    'outcomes': outcomes,
                    'closed_time': market.get('closedTime', 'N/A')
                })
        else:
            binary_count += 1
    
    print(f"\nBinary markets (2 outcomes): {binary_count}")
    print(f"Multi-outcome markets (>2 outcomes): {multi_outcome_count}")
    print(f"Percentage MCQ: {multi_outcome_count / len(markets) * 100:.1f}%")
    
    if multi_outcome_examples:
        print("\n" + "=" * 80)
        print("SAMPLE MULTI-OUTCOME MARKETS:")
        print("=" * 80)
        for i, ex in enumerate(multi_outcome_examples, 1):
            print(f"\n{i}. Question: {ex['question']}")
            print(f"   Outcomes ({len(ex['outcomes'])}): {ex['outcomes']}")
            print(f"   Closed: {ex['closed_time']}")
    else:
        print("\n⚠️  NO MULTI-OUTCOME MARKETS FOUND IN LAST 90 DAYS")
    
    # Test 2: Check specific tags for MCQ markets
    print("\n" + "=" * 80)
    print("TEST 2: Checking specific tags that might have MCQ questions")
    print("=" * 80)
    
    tags_to_check = [
        ('sports', '86'),
        ('elections', '227'),
        ('entertainment', '315'),
    ]
    
    for tag_name, tag_id in tags_to_check:
        print(f"\nChecking tag: {tag_name}")
        markets = await client.fetch_markets(
            limit=20,
            require_ground_truth=True,
            quality_requirements=quality_req,
            tag_slugs=[tag_name]
        )
        
        mcq_count = 0
        for m in markets:
            outcomes_str = m.get("outcomes", '["Yes", "No"]')
            try:
                outcomes = json.loads(outcomes_str)
            except:
                outcomes = ["Yes", "No"]
            if len(outcomes) > 2:
                mcq_count += 1
        
        print(f"  Total: {len(markets)}, MCQ: {mcq_count} ({mcq_count/max(len(markets),1)*100:.0f}%)")
        
        # Show one example
        for m in markets:
            outcomes_str = m.get("outcomes", '["Yes", "No"]')
            try:
                outcomes = json.loads(outcomes_str)
            except:
                outcomes = ["Yes", "No"]
            if len(outcomes) > 2:
                print(f"  Example: {m.get('question', 'N/A')}")
                print(f"    Outcomes: {outcomes[:3]}{'...' if len(outcomes) > 3 else ''}")
                break
    
    # Test 3: Check API usage - are we filtering out MCQ markets?
    print("\n" + "=" * 80)
    print("TEST 3: Checking if API filters are excluding MCQ markets")
    print("=" * 80)
    
    # Fetch with different parameters
    print("\nFetching markets with closed=true (our current approach)...")
    markets_closed = await client.fetch_markets(
        limit=30,
        require_ground_truth=True,
        quality_requirements=quality_req
    )
    mcq_count = 0
    for m in markets_closed:
        outcomes_str = m.get("outcomes", '["Yes", "No"]')
        try:
            outcomes = json.loads(outcomes_str)
        except:
            outcomes = ["Yes", "No"]
        if len(outcomes) > 2:
            mcq_count += 1
    print(f"  Total: {len(markets_closed)}, MCQ: {mcq_count} ({mcq_count/max(len(markets_closed),1)*100:.0f}%)")
    
    print("\nConclusion:")
    if multi_outcome_count == 0:
        print("⚠️  The Polymarket API may not be returning multi-outcome markets")
        print("    OR all multi-outcome markets resolved outside the 90-day window")
        print("    Consider:")
        print("    1. Extending the date range")
        print("    2. Checking if API endpoint supports multi-outcome markets")
        print("    3. Using a different endpoint or parameter")
    else:
        print(f"✓ Found {multi_outcome_count} MCQ markets in last 90 days")
        print(f"  This represents {multi_outcome_count / len(markets) * 100:.1f}% of all markets")


if __name__ == "__main__":
    asyncio.run(test_mcq_availability())
