"""Test the agentic pipeline with WebAgent and BaseAgent orchestration."""

import asyncio
from datetime import datetime, timedelta
from src.data.pipelines.question_pipeline import QuestionPipeline
from src.data.pipelines.stages.article_collection import ArticleSource, ArticleCollectionConfig
from src.data.config.question_config import QuestionConfig
from src.utils.config import get_config, reset_config


async def test_agentic_pipeline():
    """Test the full agentic pipeline: ArticleCollection → EventIdentification → QuestionGeneration"""
    
    print("=" * 80)
    print("Testing Agentic Pipeline Integration")
    print("=" * 80)
    
    # Reset and load config
    reset_config()
    config = get_config()
    
    print("\n1. Setting up pipeline configuration...")
    
    # Configure article collection
    article_sources = [
        ArticleSource(
            name="climate change",
            url="https://news.google.com",
            scraper_type="web"
        ),
        ArticleSource(
            name="artificial intelligence",
            url="https://news.google.com", 
            scraper_type="web"
        )
    ]
    
    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now() - timedelta(days=7),
        end_date=datetime.now(),
        max_articles_per_source=3,
        domains=["technology", "environment"]
    )
    
    # Configure question generation
    question_config = QuestionConfig(
        domains=["technology", "environment"],
        max_questions=5,
        difficulty_range=(2, 4)
    )
    
    # Get database config
    database_config = config.database
    
    print(f"   - Article sources: {len(article_sources)}")
    print(f"   - Domains: {article_config.domains}")
    print(f"   - Max questions: {question_config.max_questions}")
    
    # Create pipeline
    print("\n2. Creating QuestionPipeline with agentic stages...")
    pipeline = QuestionPipeline(
        question_config=question_config,
        database_config=database_config,
        article_sources=article_sources,
        enable_persistence=False  # Disable DB persistence for MVP test
    )
    
    print("   [OK] Pipeline created with:")
    print("     - ArticleCollectionStage (WebAgent + ArticleCollectorTool)")
    print("     - EventIdentificationStage (BaseAgent + EventIdentifierTool)")
    print("     - QuestionGenerationStage (BaseAgent + QuestionGeneratorTool)")
    
    # Run pipeline
    print("\n3. Running pipeline...")
    print("-" * 80)
    
    try:
        # Pipeline.run() returns List[PipelineStageResult], not questions
        results = await pipeline.run()
        
        # Get questions from pipeline storage
        questions = pipeline.questions
        
        print("-" * 80)
        print(f"\n4. Pipeline completed successfully!")
        print(f"   [OK] Generated {len(questions)} forecast questions")
        
        # Display results
        print("\n5. Results:")
        print("=" * 80)
        
        for idx, question in enumerate(questions, 1):
            print(f"\nQuestion {idx}:")
            print(f"   Text: {question.question_text}")
            print(f"   Type: {question.question_type}")
            print(f"   Domain: {question.domain}")
            print(f"   Difficulty: {question.difficulty}")
            print(f"   Resolution Date: {question.resolution_date}")
            if question.related_event_ids:
                print(f"   Related Events: {len(question.related_event_ids)}")
        
        print("\n" + "=" * 80)
        print("[PASS] Agentic Pipeline Test PASSED")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print("-" * 80)
        print(f"\n[ERROR] Pipeline failed with error:")
        print(f"   {type(e).__name__}: {e}")
        print("\n" + "=" * 80)
        print("[FAIL] Agentic Pipeline Test FAILED")
        print("=" * 80)
        
        import traceback
        traceback.print_exc()
        
        return False


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(test_agentic_pipeline())
    exit(0 if success else 1)
