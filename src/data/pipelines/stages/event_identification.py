"""Event identification stage for Question Pipeline."""

import json
from typing import List
from pydantic import BaseModel

from ..base import PipelineStage
from ...models import Article, Event
from src.agents.base import BaseAgent
from src.utils.config import get_config
from .tools import EventIdentifierTool, ArticleRetrievalTool
from ..prompts import EventIdentificationPrompts


class EventIdentificationConfig(BaseModel):
    """Configuration for event identification."""
    min_articles_per_event: int = 3
    confidence_threshold: float = 0.7
    use_llm: bool = True  # Use LLM for event extraction
    llm_model: str = "gpt-4"
    clustering_method: str = "semantic"  # "semantic", "temporal", "hybrid"


class EventIdentificationStage(PipelineStage[Article, Event]):
    """Identifies events from articles using LLM-powered agent.
    
    Uses agentic approach to analyze articles and extract structured events.
    Agent has access to database to query articles as needed.
    """
    
    def __init__(self, config: EventIdentificationConfig, db_path: str = "worldreasoner.db"):
        """Initialize event identification stage.
        
        Args:
            config: Event identification configuration
            db_path: Path to database for article retrieval
        """
        super().__init__(name="EventIdentification", config=config)
        # Create BaseAgent with EventIdentifierTool and ArticleRetrievalTool
        app_config = get_config()
        self.event_tool = EventIdentifierTool()  # Keep reference to tool
        self.article_retrieval_tool = ArticleRetrievalTool(db_path=db_path)  # Database access
        self.base_agent = BaseAgent(
            config=app_config,
            tools=[self.event_tool, self.article_retrieval_tool]
        )
    
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
            from datetime import datetime, timezone
            current_date = datetime.now(timezone.utc)
            
            # Get instruction from prompts module
            instruction = EventIdentificationPrompts.get_identification_instruction(
                current_date=current_date,
                articles=inputs,
                confidence_threshold=self.config.confidence_threshold
            )
            
            # Run the agent with the instruction
            result = self.base_agent.run(instruction)
            
            # Agent's response is just a summary for logging
            print(f"Agent response: {result[:200] if isinstance(result, str) else result}")
            
            # Get identified events from the tool's internal storage
            events = self.event_tool.identified_events
            
            # Update article.event_ids to link articles to events
            for article in inputs:
                # Find events that mention this article's topics
                for event in events:
                    if event.domain == article.domain:
                        if event.id not in article.event_ids:
                            article.event_ids.append(event.id)
            
            return events
            
        except Exception as e:
            print(f"Error identifying events: {e}")
            return []
