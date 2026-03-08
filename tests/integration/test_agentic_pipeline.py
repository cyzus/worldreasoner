"""Test the agentic pipeline with NewsBasedRunner."""

import asyncio
from datetime import datetime, timedelta
from src.pipelines.collection.runner_news import NewsBasedRunner
from src.pipelines.collection.stage_articles import (
    ArticleSource,
    ArticleCollectionConfig,
)
from src.config.pipeline import QuestionPipelineConfig
from src.config import get_config, reset_config


async def test_agentic_pipeline():
    """Test the NewsBasedRunner: ArticleCollection → EventIdentification → QuestionGeneration"""

    print("=" * 80)
    print("Testing NewsBasedRunner Integration")
    print("=" * 80)

    # Reset and load config
    reset_config()
    config = get_config()

    print("\n1. Setting up runner configuration...")

    # Configure article collection
    article_sources = [
        ArticleSource(
            name="climate change",
            url="https://news.google.com",
            scraper_type="web",
            domain="climate",
        ),
        ArticleSource(
            name="artificial intelligence",
            url="https://news.google.com",
            scraper_type="web",
            domain="tech",
        ),
    ]

    article_config = ArticleCollectionConfig(
        sources=article_sources,
        start_date=datetime.now() - timedelta(days=7),
        end_date=datetime.now(),
        max_articles_per_source=3,
        domains=["technology", "environment"],
    )

    # Configure question generation
    question_config = QuestionPipelineConfig(
        domains=["technology", "environment"],
        max_questions=5,
        difficulty_levels=[2, 3, 4],
    )

    print(f"   - Article sources: {len(article_sources)}")
    print(f"   - Domains: {article_config.domains}")
    print(f"   - Max questions: {question_config.max_questions}")

    # Create runner
    print("\n2. Creating NewsBasedRunner...")
    runner = NewsBasedRunner(
        article_config=article_config,
        question_config=question_config,
        db_path=config.database.db_path,
    )

    print("   [OK] Runner created with:")
    print("     - ArticleCollectionStage (WebAgent + ArticleCollectorTool)")
    print("     - EventIdentificationStage (BaseAgent + EventIdentifierTool)")
    print("     - QuestionGenerationStage (BaseAgent + QuestionGeneratorTool)")

    # Run collection
    print("\n3. Running collection...")
    print("-" * 80)

    try:
        # Collect questions
        result = await runner.collect(count=5)

        questions = result.questions

        print("-" * 80)
        print("\n4. Collection completed successfully!")
        print(f"   [OK] Generated {len(questions)} forecast questions")
        print(
            f"   [OK] Articles collected: {result.metadata.get('articles_collected', 0)}"
        )
        print(
            f"   [OK] Events identified: {result.metadata.get('events_identified', 0)}"
        )

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
        print("[PASS] NewsBasedRunner Test PASSED")
        print("=" * 80)

        return True

    except Exception as e:
        print("-" * 80)
        print("\n[ERROR] Collection failed with error:")
        print(f"   {type(e).__name__}: {e}")
        print("\n" + "=" * 80)
        print("[FAIL] NewsBasedRunner Test FAILED")
        print("=" * 80)

        import traceback

        traceback.print_exc()

        return False


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(test_agentic_pipeline())
    exit(0 if success else 1)
