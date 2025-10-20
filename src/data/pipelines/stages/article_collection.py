"""Article collection stage for Question Pipeline."""

import json
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from ..base import PipelineStage
from ...models import Article
from src.agents.factory import AgentFactory
from .tools import ArticleCollectorTool
from .collectors import ResultCollector
from ..prompts import ArticleCollectionPrompts


class ArticleSource(BaseModel):
    """Configuration for an article source."""
    name: str
    url: str
    scraper_type: str  # "rss", "web", "api"
    auth_token: Optional[str] = None
    rate_limit_per_second: float = 1.0


class ArticleCollectionConfig(BaseModel):
    """Configuration for article collection."""
    sources: List[ArticleSource]
    start_date: datetime
    end_date: datetime
    max_articles_per_source: Optional[int] = None
    domains: List[str] = []  # Filter by domains


class ArticleCollectionStage(PipelineStage[ArticleSource, Article]):
    """Collects articles from various sources using WebAgent.
    
    Uses agentic approach with WebAgent to intelligently search and scrape articles.
    """
    
    def __init__(self, config: ArticleCollectionConfig, db_path: str = "worldreasoner.db"):
        """Initialize article collection stage.
        
        Args:
            config: Article collection configuration
            db_path: Path to database for cross-run deduplication
        """
        super().__init__(name="ArticleCollection", config=config)
        
        # Create result collector for articles
        self.collector = ResultCollector[Article]()
        
        # Create ArticleCollectorTool with collector and database for deduplication
        self.article_tool = ArticleCollectorTool(db_path=db_path, collector=self.collector)
        
        # Create WebAgent using factory
        self.web_agent = AgentFactory.create_web_agent(tools=[self.article_tool])
    
    async def process(self, inputs: List[ArticleSource]) -> List[Article]:
        """Collect articles from sources using WebAgent.
        
        Args:
            inputs: List of article sources to scrape
            
        Returns:
            List of collected articles
        """
        # Use agentic approach: give high-level instructions to WebAgent
        for source in inputs:
            try:
                # Calculate time parameters
                current_date = datetime.now()
                days_back = (self.config.end_date - self.config.start_date).days
                # Limit to 3 articles per source to keep token usage reasonable
                max_articles = min(self.config.max_articles_per_source or 3, 3)
                
                # Build domain context
                domain_context = ""
                if self.config.domains:
                    domain_context = f" Focus on topics related to: {', '.join(self.config.domains)}."
                
                # Get instruction from prompts module
                instruction = ArticleCollectionPrompts.get_collection_instruction(
                    current_date=current_date,
                    source_name=source.name,
                    days_back=days_back,
                    max_articles=max_articles,
                    domain_context=domain_context
                )
                
                # Run the agent with the instruction
                result = self.web_agent.run(instruction)
                
                # Agent's response is just a summary for logging
                print(f"Agent response: {result[:200] if isinstance(result, str) else result}")
                    
            except Exception as e:
                # Log error but continue with other sources
                print(f"Error collecting from source {source.name}: {e}")
                continue
        
        # Get all collected articles from the collector
        all_articles = self.collector.get_all()
        return all_articles
