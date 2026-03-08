"""Test script to validate all tools return proper Pydantic models.

This script tests that all 13 tools correctly return Pydantic model instances
that pass validation.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

# Tool imports
from src.tools.inspectors.article_retrieval import ArticleRetrievalTool
from src.tools.collectors.rss_fetch import RssFetchTool
from src.tools.collectors.web_fetch import WebFetchTool
from src.tools.inspectors.event_details import EventDetailsTool
from src.tools.collectors.article_collector import ArticleCollectorTool
from src.tools.reasoning.causal_reasoner import CausalReasonerTool
from src.tools.generators.question_articles import QuestionArticlesTool
from src.tools.generators.question_events import QuestionEventsTool
from src.tools.reasoning.forecast_causal_reasoner import ForecastCausalReasonerTool
from src.tools.reasoning.forecast_event_identifier import ForecastEventIdentifierTool
from src.tools.reasoning.event_identifier import EventIdentifierTool
from src.tools.generators.question_generator import QuestionGeneratorTool
from src.tools.generators.question_quality_scorer import QuestionQualityScorer

# Output model imports
from src.tools.base.output_models import (
    ArticleRetrievalOutput,
    RssFetchOutput,
    WebFetchOutput,
    EventDetailsOutput,
    ArticleOutput,
    HypothesisOutput,
    QuestionArticlesOutput,
    QuestionEventsOutput,
    ForecastHypothesisOutput,
    ForecastEventOutput,
    EventOutput,
    QuestionOutput,
    QuestionQualityOutput,
)

from pydantic import ValidationError


def _validate_tool_return_type(tool_name: str, result, expected_type):
    """Validate a tool's return value is correct Pydantic type."""
    print(f"\n{'='*60}")
    print(f"Testing {tool_name}")
    print(f"{'='*60}")
    
    # Check type
    if not isinstance(result, expected_type):
        print(f"❌ FAILED: Expected {expected_type.__name__}, got {type(result).__name__}")
        print(f"   Result: {result}")
        return False
    
    print(f"✅ Type check passed: {expected_type.__name__}")
    
    # Try to validate by reconstructing (tests all fields)
    try:
        if isinstance(result, expected_type):
            # Convert to dict and back to validate
            result_dict = result.model_dump() if hasattr(result, 'model_dump') else result.dict()
            validated = expected_type(**result_dict)
            print("✅ Pydantic validation passed")
            print(f"   Fields: {list(result_dict.keys())}")
            print(f"   Sample: {str(result)[:200]}")
            return True
    except ValidationError as e:
        print("❌ FAILED: Pydantic validation error")
        print(f"   {e}")
        return False
    except Exception as e:
        print("⚠️  WARNING: Unexpected error during validation")
        print(f"   {e}")
        return False


def main():
    """Run validation tests on all tools."""
    print("="*60)
    print("PYDANTIC TOOL RETURN VALIDATION TEST")
    print("="*60)
    
    test_db = "test_validation.db"
    results = {}
    
    # Test 1: RssFetchTool (simple, no DB needed)
    try:
        tool = RssFetchTool()
        # Use a known RSS feed
        result = tool.forward("https://hnrss.org/newest", max_items=2)
        results["RssFetchTool"] = _validate_tool_return_type("RssFetchTool", result, RssFetchOutput)
    except Exception as e:
        print(f"\n❌ RssFetchTool failed with error: {e}")
        results["RssFetchTool"] = False
    
    # Test 2: WebFetchTool (simple, no DB needed)
    try:
        tool = WebFetchTool()
        result = tool.forward("https://example.com")
        results["WebFetchTool"] = _validate_tool_return_type("WebFetchTool", result, WebFetchOutput)
    except Exception as e:
        print(f"\n❌ WebFetchTool failed with error: {e}")
        results["WebFetchTool"] = False
    
    # Test 3: ArticleRetrievalTool (needs DB with article)
    try:
        tool = ArticleRetrievalTool(db_path=test_db)
        # Test with non-existent ID to get error response
        result = tool.forward("test_article_id")
        results["ArticleRetrievalTool"] = _validate_tool_return_type("ArticleRetrievalTool", result, ArticleRetrievalOutput)
    except Exception as e:
        print(f"\n❌ ArticleRetrievalTool failed with error: {e}")
        results["ArticleRetrievalTool"] = False
    
    # Test 4: EventDetailsTool
    try:
        tool = EventDetailsTool(db_path=test_db)
        result = tool.forward("test_event_id")
        results["EventDetailsTool"] = _validate_tool_return_type("EventDetailsTool", result, EventDetailsOutput)
    except Exception as e:
        print(f"\n❌ EventDetailsTool failed with error: {e}")
        results["EventDetailsTool"] = False
    
    # Test 5: ArticleCollectorTool
    try:
        tool = ArticleCollectorTool(db_path=test_db)
        result = tool.forward(
            url="https://example.com/test-article",
            title="Test Article",
            source="Test Source",
            published_date=datetime.now(timezone.utc).isoformat(),
            domain="technology"
        )
        results["ArticleCollectorTool"] = _validate_tool_return_type("ArticleCollectorTool", result, ArticleOutput)
    except Exception as e:
        print(f"\n❌ ArticleCollectorTool failed with error: {e}")
        results["ArticleCollectorTool"] = False
    
    # Test 6: CausalReasonerTool
    try:
        tool = CausalReasonerTool(db_path=test_db, default_question_id="test_q")
        result = tool.forward(
            source_event_id="evt_test_1",
            target_event_id="evt_test_2",
            relation_type="causes",
            strength=0.8,
            confidence=0.7,
            reasoning="Test reasoning",
            evidence_article_ids="art1,art2"
        )
        results["CausalReasonerTool"] = _validate_tool_return_type("CausalReasonerTool", result, HypothesisOutput)
    except Exception as e:
        print(f"\n❌ CausalReasonerTool failed with error: {e}")
        results["CausalReasonerTool"] = False
    
    # Test 7: QuestionArticlesTool
    try:
        tool = QuestionArticlesTool(db_path=test_db, question_id="test_q")
        result = tool.forward(limit=10)
        results["QuestionArticlesTool"] = _validate_tool_return_type("QuestionArticlesTool", result, QuestionArticlesOutput)
    except Exception as e:
        print(f"\n❌ QuestionArticlesTool failed with error: {e}")
        results["QuestionArticlesTool"] = False
    
    # Test 8: QuestionEventsTool
    try:
        tool = QuestionEventsTool(db_path=test_db, question_id="test_q")
        result = tool.forward()
        results["QuestionEventsTool"] = _validate_tool_return_type("QuestionEventsTool", result, QuestionEventsOutput)
    except Exception as e:
        print(f"\n❌ QuestionEventsTool failed with error: {e}")
        results["QuestionEventsTool"] = False
    
    # Test 9: ForecastCausalReasonerTool
    try:
        tool = ForecastCausalReasonerTool(session_id="test_session")
        result = tool.forward(
            source_event_id="fevt_1",
            target_event_id="fevt_2",
            relation_type="causes",
            strength=0.8,
            confidence=0.7,
            reasoning="Test forecast reasoning",
            evidence_article_ids="art1"
        )
        results["ForecastCausalReasonerTool"] = _validate_tool_return_type("ForecastCausalReasonerTool", result, ForecastHypothesisOutput)
    except Exception as e:
        print(f"\n❌ ForecastCausalReasonerTool failed with error: {e}")
        results["ForecastCausalReasonerTool"] = False
    
    # Test 10: ForecastEventIdentifierTool
    try:
        tool = ForecastEventIdentifierTool(session_id="test_session")
        result = tool.forward(
            title="Test Forecast Event",
            description="Test description",
            domain="technology",
            occurred_date=datetime.now(timezone.utc).isoformat()
        )
        results["ForecastEventIdentifierTool"] = _validate_tool_return_type("ForecastEventIdentifierTool", result, ForecastEventOutput)
    except Exception as e:
        print(f"\n❌ ForecastEventIdentifierTool failed with error: {e}")
        results["ForecastEventIdentifierTool"] = False
    
    # Test 11: EventIdentifierTool
    try:
        tool = EventIdentifierTool(db_path=test_db)
        result = tool.forward(
            title="Test Event",
            description="Test event description",
            domain="technology",
            source_article_ids="art1,art2",
            occurred_date=datetime.now(timezone.utc).isoformat()
        )
        results["EventIdentifierTool"] = _validate_tool_return_type("EventIdentifierTool", result, EventOutput)
    except Exception as e:
        print(f"\n❌ EventIdentifierTool failed with error: {e}")
        results["EventIdentifierTool"] = False
    
    # Test 12: QuestionGeneratorTool
    try:
        tool = QuestionGeneratorTool(require_ground_truth=False)
        result = tool.forward(
            question_text="Will Bitcoin reach $100k by end of 2025?",
            question_type="binary",
            domain="finance",
            difficulty=3,
            resolution_date="2025-12-31T23:59:59Z",
            resolution_criteria="Based on CoinMarketCap closing price"
        )
        results["QuestionGeneratorTool"] = _validate_tool_return_type("QuestionGeneratorTool", result, QuestionOutput)
    except Exception as e:
        print(f"\n❌ QuestionGeneratorTool failed with error: {e}")
        results["QuestionGeneratorTool"] = False
    
    # Test 13: QuestionQualityScorer (async)
    try:
        from src.domain.models import Question, QuestionType, Domain
        test_question = Question(
            id="test_q",
            question_text="Test question?",
            question_type=QuestionType.BINARY,
            domain=Domain.TECHNOLOGY,
            difficulty=3,
            resolution_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
            resolution_criteria="Test criteria"
        )
        
        tool = QuestionQualityScorer()
        # Run async function
        result = asyncio.run(tool.forward([test_question]))
        results["QuestionQualityScorer"] = _validate_tool_return_type("QuestionQualityScorer", result, QuestionQualityOutput)
    except Exception as e:
        print(f"\n❌ QuestionQualityScorer failed with error: {e}")
        results["QuestionQualityScorer"] = False
    
    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for tool_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {tool_name}")
    
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} tools passed validation")
    print(f"{'='*60}")
    
    # Cleanup test DB
    try:
        Path(test_db).unlink(missing_ok=True)
        Path(f"{test_db}-shm").unlink(missing_ok=True)
        Path(f"{test_db}-wal").unlink(missing_ok=True)
    except:
        pass
    
    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
