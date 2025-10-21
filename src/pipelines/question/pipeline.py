"""Question generation pipeline for WorldReasoner.

This pipeline creates benchmark questions from real-world data:
1. Collect articles from various sources
2. Identify events from articles
3. Generate forecast questions about events
"""

from typing import List, Optional
from datetime import datetime, timezone

from ..base import Pipeline, PipelineStageResult, PipelineStageStatus
from ..stages import (
    ArticleCollectionStage,
    ArticleCollectionConfig,
    ArticleSource,
    EventIdentificationStage,
    EventIdentificationConfig,
    QuestionGenerationStage,
    DatabasePersistenceStage,
    DatabasePersistenceConfig,
)
from src.config.pipeline import QuestionPipelineConfig
from src.config import DatabaseConfig
from src.domain.models import Article, Event, Question
from src.utils.logging import logger


class QuestionPipeline(Pipeline):
    """Pipeline for generating forecast questions from real-world data.
    
    Flow: Article Sources → Articles → Events → Questions
    
    This pipeline:
    - Collects articles from RSS/web/API sources
    - Identifies events from article clusters
    - Generates forecast questions about future outcomes
    - Saves questions to database for benchmarking
    """
    
    def __init__(
        self,
        question_config: QuestionPipelineConfig,
        database_config: DatabaseConfig,
        article_sources: List[ArticleSource],
        enable_persistence: bool = True,
    ):
        """Initialize the question generation pipeline.
        
        Args:
            question_config: Configuration for question generation
            database_config: Database connection configuration
            article_sources: List of sources to collect articles from
            enable_persistence: Whether to save to database
        """
        super().__init__(name="QuestionPipeline")
        
        self.question_config = question_config
        self.database_config = database_config
        self.enable_persistence = enable_persistence
        
        # Configure article collection
        article_config = ArticleCollectionConfig(
            sources=article_sources,
            start_date=datetime.combine(
                question_config.start_date, 
                datetime.min.time()
            ).replace(tzinfo=timezone.utc),
            end_date=datetime.combine(
                question_config.end_date, 
                datetime.min.time()
            ).replace(tzinfo=timezone.utc),
            domains=question_config.domains,
        )
        
        # Configure event identification
        event_config = EventIdentificationConfig(
            min_articles_per_event=question_config.min_articles_per_event,
            confidence_threshold=question_config.event_confidence_threshold,
        )
        
        # Configure database persistence
        persist_config = DatabasePersistenceConfig(
            batch_size=database_config.batch_size,
        )
        
        # Build pipeline stages (use same db path for all stages)
        db_path = "worldreasoner.db"
        self.article_stage = ArticleCollectionStage(article_config, db_path=db_path)
        self.event_stage = EventIdentificationStage(event_config, db_path=db_path)
        # Question stage will receive articles later via set_articles()
        self.question_stage = QuestionGenerationStage(question_config)
        
        # Add stages to pipeline
        self.add_stage(self.article_stage)
        self.add_stage(self.event_stage)
        self.add_stage(self.question_stage)
        
        # Add persistence stages if enabled
        if enable_persistence:
            self.article_persist = DatabasePersistenceStage(
                persist_config, "article"
            )
            self.event_persist = DatabasePersistenceStage(
                persist_config, "event"
            )
            self.question_persist = DatabasePersistenceStage(
                persist_config, "question"
            )
        
        # Storage for intermediate results
        self.articles: List[Article] = []
        self.events: List[Event] = []
        self.questions: List[Question] = []
    
    async def run(self) -> List[PipelineStageResult]:
        """Run the question generation pipeline.
        
        Returns:
            List of results from each stage
        """
        self._results = []
        
        try:
            # Stage 1: Collect Articles
            logger.info("Stage 1: Collecting articles...")
            article_result = await self.article_stage.execute(
                self.article_stage.config.sources
            )
            self._results.append(article_result)
            self.articles = article_result.outputs
            
            if not self.articles:
                logger.warning("No articles collected")
                return self._results
            
            logger.info(f"Collected {len(self.articles)} articles")
            
            # Persist articles if enabled
            if self.enable_persistence and self.articles:
                persist_result = await self.article_persist.execute(self.articles)
                self._results.append(persist_result)
            
            # Stage 2: Identify Events
            logger.info("Stage 2: Identifying events...")
            event_result = await self.event_stage.execute(self.articles)
            self._results.append(event_result)
            self.events = event_result.outputs
            
            if not self.events:
                logger.warning("No events identified")
                return self._results
            
            logger.info(f"Identified {len(self.events)} events")
            
            # Persist events if enabled
            if self.enable_persistence and self.events:
                persist_result = await self.event_persist.execute(self.events)
                self._results.append(persist_result)
            
            # Stage 3: Generate Questions
            logger.info("Stage 3: Generating questions...")
            # Pass articles to question stage so EventDetailsTool can access them
            self.question_stage.set_articles(self.articles)
            question_result = await self.question_stage.execute(self.events)
            self._results.append(question_result)
            self.questions = question_result.outputs
            
            if not self.questions:
                logger.warning("No questions generated")
                return self._results
            
            logger.info(f"Generated {len(self.questions)} questions")
            
            # Persist questions if enabled
            if self.enable_persistence and self.questions:
                persist_result = await self.question_persist.execute(self.questions)
                self._results.append(persist_result)
            
            logger.success("Pipeline completed successfully!")
            
        except Exception as e:
            # Add error to last result if exists
            if self._results:
                self._results[-1].error_message = str(e)
            logger.error(f"Pipeline failed: {e}")
            raise
        
        return self._results
    
    def get_articles(self) -> List[Article]:
        """Get collected articles."""
        return self.articles
    
    def get_events(self) -> List[Event]:
        """Get identified events."""
        return self.events
    
    def get_questions(self) -> List[Question]:
        """Get generated questions."""
        return self.questions
