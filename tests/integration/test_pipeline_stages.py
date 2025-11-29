"""Test individual stages of the question pipeline."""

import os
import sys

# Set UTF-8 encoding for Windows console output
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from src.pipelines.stages import (
    ArticleCollectionStage,
    ArticleCollectionConfig,
    ArticleSource,
    EventIdentificationStage,
    EventIdentificationConfig,
    QuestionGenerationStage,
)
from src.pipelines.base import PipelineStageStatus
from src.config.pipeline import QuestionPipelineConfig
from src.config import get_config, reset_config
from src.domain.models import Article, Event, Question


@pytest.mark.integration
@pytest.mark.asyncio
async def test_article_collection_stage(test_db_path):
    """Test ArticleCollectionStage in isolation."""
    print("\n" + "=" * 80)
    print("Test 1: Article Collection Stage")
    print("=" * 80)

    # Setup configuration
    sources = [
        ArticleSource(
            name="artificial intelligence",
            url="https://news.google.com",
            scraper_type="web",
            domain="tech"
        )
    ]

    config = ArticleCollectionConfig(
        sources=sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=7),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=2,
        domains=["technology"]
    )

    # Create and run stage (using tmp_path fixture)
    stage = ArticleCollectionStage(config, db_path=test_db_path)
    
    print("\n1. Processing article sources...")
    result = await stage.execute(sources)
    
    # Get collected articles from result.outputs
    articles = result.outputs
    
    # Assertions
    print(f"\n2. Validation:")
    print(f"   - Collected {len(articles)} articles")
    assert len(articles) > 0, "Should collect at least one article"
    
    # Validate article structure
    first_article = articles[0]
    print(f"   - First article ID: {first_article.id}")
    assert isinstance(first_article, Article), "Should return Article objects"
    assert first_article.id.startswith("art_"), "Article ID should have correct prefix"
    assert first_article.title, "Article should have title"
    assert first_article.content, "Article should have content"
    assert first_article.domain in ["technology", "tech"], "Article should be in tech domain"
    assert first_article.event_ids == [], "New articles should have empty event_ids"
    
    # Check result metrics
    assert result is not None, "Stage should have result"
    assert result.items_processed > 0, "Should have processed items"
    assert result.status == PipelineStageStatus.COMPLETED, "Stage should complete successfully"
    
    print(f"   [OK] Articles have correct structure")
    print(f"   [OK] Stage metrics: {result.items_output} articles from {result.items_processed} sources")
    print(f"   [OK] Duration: {result.duration_seconds():.2f}s")
    print("\n[PASS] Article Collection Stage Test")
    print("=" * 80)
    
    return articles


@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_identification_stage(test_db_path):
    """Test EventIdentificationStage in isolation."""
    print("\n" + "=" * 80)
    print("Test 2: Event Identification Stage")
    print("=" * 80)

    # First collect articles
    print("\n1. Collecting sample articles...")
    article_sources = [
        ArticleSource(
            name="technology news",
            url="https://news.google.com",
            scraper_type="web",
            domain="tech"
        )
    ]

    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=15),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=3,
        domains=["technology"]
    )

    article_stage = ArticleCollectionStage(article_config, db_path=test_db_path)
    articles = await article_stage.process(article_sources)
    print(f"   - Collected {len(articles)} articles")

    if len(articles) == 0:
        print("   [SKIP] No articles collected, skipping event identification")
        return []

    # Setup event identification
    event_config = EventIdentificationConfig(
        min_articles_per_event=1,
        confidence_threshold=0.7
    )

    # Create and run stage (using same tmp_path)
    stage = EventIdentificationStage(event_config, db_path=test_db_path)
    
    print("\n2. Identifying events from articles...")
    result = await stage.execute(articles)
    
    # Get events from result.outputs
    events = result.outputs
    
    # Assertions
    print(f"\n3. Validation:")
    print(f"   - Identified {len(events)} events")
    
    if len(events) > 0:
        # Validate event structure
        first_event = events[0]
        print(f"   - First event ID: {first_event.id}")
        print(f"   - First event title: {first_event.title[:60]}...")
        assert isinstance(first_event, Event), "Should return Event objects"
        assert first_event.id.startswith("evt_"), "Event ID should have correct prefix"
        assert first_event.title, "Event should have title"
        assert first_event.description, "Event should have description"
        assert first_event.domain, "Event should have domain"
        assert first_event.article_ids, "Event should link to articles"
        
        # Check that articles were updated with event IDs
        linked_article = next((a for a in articles if first_event.id in a.event_ids), None)
        assert linked_article is not None, "At least one article should be linked to first event"
        print(f"   [OK] Events have correct structure")
        print(f"   [OK] Articles linked to events")
    else:
        print("   ! No events identified (this can happen with certain article content)")
    
    # Check result metrics
    assert result is not None, "Stage should have result"
    assert result.status == PipelineStageStatus.COMPLETED, "Stage should complete successfully"
    print(f"   [OK] Stage metrics: {result.items_output} events from {result.items_processed} articles")
    print(f"   [OK] Duration: {result.duration_seconds():.2f}s")
    
    print("\n[PASS] Event Identification Stage Test")
    print("=" * 80)
    
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_question_generation_stage(test_db_path):
    """Test QuestionGenerationStage in isolation."""
    print("\n" + "=" * 80)
    print("Test 3: Question Generation Stage")
    print("=" * 80)

    # First collect articles and identify events
    print("\n1. Setting up prerequisites (articles + events)...")
    article_sources = [
        ArticleSource(
            name="technology trends",
            url="https://news.google.com",
            scraper_type="web",
            domain="tech"
        )
    ]

    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=7),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=3,
        domains=["technology"]
    )

    article_stage = ArticleCollectionStage(article_config, db_path=test_db_path)
    articles = await article_stage.process(article_sources)
    print(f"   - Collected {len(articles)} articles")

    if len(articles) == 0:
        print("   [SKIP] No articles collected, skipping question generation")
        return []

    event_config = EventIdentificationConfig(
        min_articles_per_event=1,
        confidence_threshold=0.7
    )

    event_stage = EventIdentificationStage(event_config, db_path=test_db_path)
    events = await event_stage.process(articles)
    print(f"   - Identified {len(events)} events")
    
    if len(events) == 0:
        print("   [SKIP] No events identified, skipping question generation")
        return []
    
    # Setup question generation
    question_config = QuestionPipelineConfig(
        domains=["technology"],
        max_questions=3,
        difficulty_levels=[2, 3, 4]
    )
    
    # Create and run stage
    stage = QuestionGenerationStage(question_config)
    
    print("\n2. Generating forecast questions from events...")
    result = await stage.execute(events)
    
    # Get questions from result.outputs
    questions = result.outputs
    
    # Assertions
    print(f"\n3. Validation:")
    print(f"   - Generated {len(questions)} questions")
    
    if len(questions) > 0:
        # Validate question structure
        first_question = questions[0]
        print(f"   - First question ID: {first_question.id}")
        print(f"   - First question text: {first_question.question_text[:80]}...")
        assert isinstance(first_question, Question), "Should return Question objects"
        assert first_question.id.startswith("q_"), "Question ID should have correct prefix"
        assert first_question.question_text, "Question should have text"
        assert first_question.question_type, "Question should have type"
        assert first_question.domain, "Question should have domain"
        assert first_question.difficulty >= 1 and first_question.difficulty <= 5, "Difficulty should be 1-5"
        assert first_question.resolution_date, "Question should have resolution date"
        assert first_question.ground_truth is not None, "Question should have ground truth"
        
        # Validate that questions link to events
        assert first_question.related_event_ids, "Question should link to events"
        assert len(first_question.related_event_ids) > 0, "Question should have at least one related event"
        
        # Check resolution date is reasonable
        now = datetime.now(timezone.utc)
        min_date = now - timedelta(days=365)
        max_date = now + timedelta(days=365)
        assert min_date <= first_question.resolution_date <= max_date, "Resolution date should be reasonable"
        
        print(f"   [OK] Questions have correct structure")
        print(f"   [OK] Questions linked to events")
        print(f"   [OK] Resolution dates are valid")
    else:
        print("   ! No questions generated (this can happen with certain event content)")
    
    # Check result metrics
    assert result is not None, "Stage should have result"
    assert result.status == PipelineStageStatus.COMPLETED, "Stage should complete successfully"
    print(f"   [OK] Stage metrics: {result.items_output} questions from {result.items_processed} events")
    print(f"   [OK] Duration: {result.duration_seconds():.2f}s")
    
    print("\n[PASS] Question Generation Stage Test")
    print("=" * 80)
    
    return questions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_stages_integration(test_db_path):
    """Test all three stages working together in sequence."""
    print("\n" + "=" * 80)
    print("Test 4: Full Pipeline Integration (All Stages)")
    print("=" * 80)

    # Reset config
    reset_config()
    config = get_config()

    # Stage 1: Article Collection
    print("\n1. STAGE 1: Article Collection")
    print("-" * 80)
    article_sources = [
        ArticleSource(
            name="artificial intelligence",
            url="https://news.google.com",
            scraper_type="web",
            domain="tech"
        )
    ]

    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=7),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=2,
        domains=["technology"]
    )

    article_stage = ArticleCollectionStage(article_config, db_path=test_db_path)
    articles = await article_stage.process(article_sources)
    print(f"   [OK] Collected {len(articles)} articles")
    assert len(articles) > 0, "Should collect articles"

    # Stage 2: Event Identification
    print("\n2. STAGE 2: Event Identification")
    print("-" * 80)
    event_config = EventIdentificationConfig(
        min_articles_per_event=1,
        confidence_threshold=0.7
    )

    event_stage = EventIdentificationStage(event_config, db_path=test_db_path)
    events = await event_stage.process(articles)
    print(f"   [OK] Identified {len(events)} events")
    
    # Stage 3: Question Generation
    print("\n3. STAGE 3: Question Generation")
    print("-" * 80)
    question_config = QuestionPipelineConfig(
        domains=["technology"],
        max_questions=3,
        difficulty_levels=[2, 3, 4]
    )
    
    question_stage = QuestionGenerationStage(question_config)
    questions = await question_stage.process(events)
    print(f"   [OK] Generated {len(questions)} questions")
    
    # Final validation
    print("\n4. Integration Validation:")
    print("-" * 80)
    print(f"   Articles -> Events:  {len(articles)} -> {len(events)}")
    print(f"   Events -> Questions: {len(events)} -> {len(questions)}")
    
    # Verify data flow
    if len(events) > 0 and len(questions) > 0:
        # Check that questions link back to events
        all_question_event_ids = set()
        for q in questions:
            all_question_event_ids.update(q.related_event_ids)
        
        event_ids = {e.id for e in events}
        linked_events = all_question_event_ids & event_ids
        print(f"   Questions reference {len(linked_events)}/{len(events)} events")
        assert len(linked_events) > 0, "Questions should reference generated events"
        
        # Check that events link back to articles
        all_event_article_ids = set()
        for e in events:
            all_event_article_ids.update(e.article_ids)
        
        article_ids = {a.id for a in articles}
        linked_articles = all_event_article_ids & article_ids
        print(f"   Events reference {len(linked_articles)}/{len(articles)} articles")
        assert len(linked_articles) > 0, "Events should reference collected articles"
        
        print(f"   [OK] Data flow validated: Articles -> Events -> Questions")
    
    print("\n" + "=" * 80)
    print("[PASS] Full Pipeline Integration Test")
    print("=" * 80)
    
    return {
        "articles": articles,
        "events": events,
        "questions": questions
    }


if __name__ == "__main__":
    """Run all tests in sequence."""
    async def run_all_tests():
        print("\n" + "=" * 80)
        print("RUNNING ALL PIPELINE STAGE TESTS")
        print("=" * 80)
        
        try:
            # Test each stage individually
            await test_article_collection_stage()
            await test_event_identification_stage()
            await test_question_generation_stage()
            
            # Test full integration
            await test_pipeline_stages_integration()
            
            print("\n" + "=" * 80)
            print("[OK] ALL TESTS PASSED")
            print("=" * 80)
            return True
            
        except AssertionError as e:
            print(f"\n[FAIL] TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False
        except Exception as e:
            print(f"\n[FAIL] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
