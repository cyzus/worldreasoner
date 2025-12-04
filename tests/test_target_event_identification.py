"""Test script for target event identification.

Tests the new target event identification stage with sample questions.
"""

import asyncio
from datetime import datetime, timezone

from src.pipelines.stages import (
    TargetEventIdentificationStage,
    TargetEventIdentificationConfig
)
from src.domain.models import Question, Article
from src.domain.models.domain import Domain
from src.domain.models.question import QuestionType
from src.core.database import GenericDatabase
from src.utils.logging import logger


async def test_target_event_identification():
    """Test target event identification with sample questions."""
    
    # Initialize stage
    config = TargetEventIdentificationConfig(
        similarity_threshold=0.75,
        create_if_not_found=True
    )
    stage = TargetEventIdentificationStage(config, db_path="worldreasoner.db")
    
    # Create sample questions without target events (like Polymarket questions)
    sample_questions = [
        Question(
            id="test_polymarket_001",
            question_text="Will Bitcoin reach $100,000 by December 31, 2024?",
            question_type=QuestionType.BOOLEAN,
            domain=Domain.FINANCE,
            source="polymarket",
            difficulty=3,
            resolution_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            ground_truth=True,  # It happened!
            target_event_id=None,  # No target event yet
            related_event_ids=[],
            created_at=datetime.now(timezone.utc),
        ),
        Question(
            id="test_polymarket_002",
            question_text="Will Donald Trump win the 2024 US Presidential Election?",
            question_type=QuestionType.BOOLEAN,
            domain=Domain.POLITICS,
            source="polymarket",
            difficulty=4,
            resolution_date=datetime(2024, 11, 5, tzinfo=timezone.utc),
            ground_truth=True,
            target_event_id=None,
            related_event_ids=[],
            created_at=datetime.now(timezone.utc)
        ),
        Question(
            id="test_polymarket_003",
            question_text="Will there be a global recession in 2024?",
            question_type=QuestionType.BOOLEAN,
            domain=Domain.FINANCE,
            source="polymarket",
            difficulty=5,
            resolution_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            ground_truth=False,  # Didn't happen
            target_event_id=None,
            related_event_ids=[],
            created_at=datetime.now(timezone.utc)
        )
    ]
    
    # Create dummy evidence articles (stage needs them but won't use much)
    dummy_articles = [
        Article(
            id="dummy_article_001",
            url="https://example.com/btc",
            title="Bitcoin Price Analysis - December 2024",
            content="Bitcoin has reached new all-time highs in December 2024, breaking through the $100,000 barrier for the first time in history. Market analysts attribute this surge to increased institutional adoption and favorable regulatory developments.",
            source="Crypto News Daily",
            published_date=datetime(2024, 12, 30, tzinfo=timezone.utc),
            domain=Domain.FINANCE
        )
    ]
    
    # Prepare inputs (Question, List[Article] pairs)
    inputs = [(q, dummy_articles) for q in sample_questions]
    
    # Run the stage
    logger.info("=" * 60)
    logger.info("Testing Target Event Identification Stage")
    logger.info("=" * 60)
    
    try:
        updated_questions = await stage.process(inputs)
        
        logger.info("=" * 60)
        logger.info("RESULTS")
        logger.info("=" * 60)
        
        for question in updated_questions:
            logger.info(f"Question: {question.question_text}")
            logger.info(f"  Ground Truth: {question.ground_truth}")
            logger.info(f"  Target Event ID: {question.target_event_id}")
            
            if question.target_event_id:
                # Try to fetch the created event
                db = GenericDatabase("worldreasoner.db")
                event = db.get(Event, question.target_event_id)
                if event:
                    logger.info(f"  Event Name: {event.title}")
                    logger.info(f"  Event Date: {event.occurred_date}")
                    logger.info(f"  Event Domain: {event.domain}")
        
        logger.info("=" * 60)
        logger.info(f"Successfully processed {len(updated_questions)} questions")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Need to import Event here for the test
    from src.domain.models import Event
    
    asyncio.run(test_target_event_identification())
