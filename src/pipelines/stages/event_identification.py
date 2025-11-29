"""Event identification stage for Question Pipeline."""

import json
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from ..base import PipelineStage
from src.domain.models import Article, Event
from src.agents.factory import AgentFactory
from .tools import BatchEventIdentifierTool, ArticleRetrievalTool
from .collectors import ResultCollector
from ..prompts import EventIdentificationPrompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class EventIdentificationConfig(BaseModel):
    """Configuration for event identification."""
    min_articles_per_event: int = 3
    confidence_threshold: float = 0.7
    clustering_method: str = "semantic"  # "semantic", "temporal", "hybrid"


class EventIdentificationStage(PipelineStage[Article, Event]):
    """Identifies events from articles using LLM-powered agent.
    
    Uses agentic approach to analyze articles and extract structured events.
    Agent has access to database to query articles as needed.
    """
    
    def __init__(self, config: EventIdentificationConfig, db_path: str = "worldreasoner.db", 
                 category_hints: Optional[List[str]] = None):
        """Initialize event identification stage.
        
        Args:
            config: Event identification configuration
            db_path: Path to database for article retrieval
            category_hints: Priority categories/domains needed (e.g., ["finance", "tech"])
        """
        super().__init__(name="EventIdentification", config=config)
        
        # Store hints for intelligent identification
        self.category_hints = category_hints
        
        # Create result collector for events
        self.collector = ResultCollector[Event]()

        # Create tools
        self.event_tool = BatchEventIdentifierTool(collector=self.collector)
        self.article_retrieval_tool = ArticleRetrievalTool(db_path=db_path)

        # Create BaseAgent using factory
        self.base_agent = AgentFactory.create_base_agent(
            tools=[self.event_tool, self.article_retrieval_tool]
        )

        # Prompt generator
        self.prompts = EventIdentificationPrompts()

        # Usage tracking
        self.usage_tracker = UsageTracker()
    
    async def process(self, inputs: List[Article]) -> List[Event]:
        """Identify events from articles using LLM agent.
        
        Args:
            inputs: List of articles to analyze
            
        Returns:
            List of identified events
        """
        if not inputs:
            return []
        
        try:
            # Get current date for context
            current_date = datetime.now(timezone.utc)
            
            # Get instruction from prompts module
            instruction = self.prompts.get_instruction(
                current_date=current_date,
                articles=inputs,
                confidence_threshold=self.config.confidence_threshold,
                category_hints=self.category_hints
            )
            
            # Run the agent with the instruction
            result = self.base_agent.run(instruction)

            # Track token usage
            usage_metrics = self.base_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context="EventIdentification")

            # Agent's response is just a summary for logging
            logger.debug(f"Agent response for event identification: {result[:200] if isinstance(result, str) else result}")

            # Get identified events from the collector
            events = self.collector.get_all()
            
            # Update article.event_ids to create bidirectional links
            # Events already have article_ids set by the agent via EventIdentifierTool
            # Now we update the reverse direction: articles pointing to events
            article_map = {article.id: article for article in inputs}

            for event in events:
                # For each article referenced by this event, add the event ID to that article
                for article_id in event.article_ids:
                    if article_id in article_map:
                        article = article_map[article_id]
                        if event.id not in article.event_ids:
                            article.event_ids.append(event.id)
                            logger.debug(f"Linked article {article_id} to event {event.id}")

            # Log usage summary for this stage
            if self.usage_tracker.total_calls > 0:
                self.usage_tracker.log_summary(context="EventIdentification")

            return events
            
        except Exception as e:
            logger.error(f"Error identifying events: {e}")
            return []
