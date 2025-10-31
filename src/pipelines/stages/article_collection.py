"""Article collection stage for Question Pipeline."""

import json
import asyncio
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from ..base import PipelineStage
from src.domain.models import Article
from src.agents.factory import AgentFactory
from .tools import ArticleCollectorTool, RssFetchTool
from .collectors import ResultCollector
from ..prompts import ArticleCollectionPrompts
from src.utils.logging import logger


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
        # RSS fetch tool for direct RSS ingestion
        self.rss_tool = RssFetchTool()
        
        # Create WebAgent using factory
        self.web_agent = AgentFactory.create_web_agent(tools=[self.article_tool])
    
    async def _fetch_rss_item_async(self, item: dict, source_name: str) -> bool:
        """Fetch a single RSS item asynchronously.
        
        Args:
            item: RSS feed item with title, link, published
            source_name: Name of the source
            
        Returns:
            True if successfully collected, False otherwise
        """
        try:
            link = item.get('link') or item.get('url')
            if not link:
                logger.warning(f"[RSS] Item missing link, skipping")
                return False
            
            title = item.get('title', '')
            published = item.get('published', None)
            author = item.get('author', "")
            
            # Fetch full article content (runs in executor to not block)
            # Note: article_tool.forward is synchronous, but we run it in executor
            # Use lambda to pass keyword arguments correctly
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(
                None,
                lambda: self.article_tool.forward(
                    url=link,
                    title=title,
                    source=source_name,
                    domain="general",  # Default domain category for RSS articles
                    published_date=published,
                    author=author
                )
            )
            
            logger.debug(f"[RSS] Collected: {summary}")
            return True
            
        except Exception as e:
            logger.error(f"[RSS] Failed to collect item from {item.get('link', 'unknown')}: {e}")
            return False
    
    async def _collect_from_rss(self, source: ArticleSource) -> int:
        """Collect articles from RSS feed source using async fetching.
        
        Args:
            source: RSS article source
            
        Returns:
            Number of articles collected
        """
        logger.info(f"[RSS] Fetching feed: {source.name} -> {source.url}")
        
        try:
            # Fetch RSS feed (synchronous, but fast)
            rss_resp = self.rss_tool.forward(
                feed_url=source.url, 
                max_items=self.config.max_articles_per_source or 5
            )
            
            # Parse response
            try:
                rss_json = json.loads(rss_resp)
            except Exception as e:
                logger.error(f"[RSS] Failed to parse RSS response for {source.name}: {e}")
                return 0
            
            # Check for errors
            if 'error' in rss_json:
                logger.error(f"[RSS] Error from feed {source.name}: {rss_json['error']}")
                return 0
            
            items = rss_json.get('items', [])
            logger.info(f"[RSS] Feed returned {len(items)} items for {source.name}")
            
            # Fetch all items concurrently using asyncio.gather
            logger.info(f"[RSS] Fetching {len(items)} items concurrently...")
            tasks = [self._fetch_rss_item_async(item, source.name) for item in items]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count successful fetches (ignore exceptions)
            collected_count = sum(1 for r in results if r is True)
            
            logger.info(f"[RSS] Successfully collected {collected_count}/{len(items)} articles from {source.name}")
            return collected_count
            
        except Exception as e:
            logger.error(f"[RSS] Error collecting from source {source.name}: {e}")
            return 0
    
    async def _collect_from_web_agent(self, source: ArticleSource) -> int:
        """Collect articles using agentic web scraping.
        
        Args:
            source: Web article source
            
        Returns:
            Number of articles collected
        """
        logger.info(f"[AGENT] Starting collection: {source.name}")
        
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
            
            # Track articles before agent run
            articles_before = self.collector.count()
            
            # Run the agent with the instruction
            logger.info(f"[AGENT] Running agent for: {source.name}")
            result = self.web_agent.run(instruction)
            
            # Calculate articles collected
            articles_after = self.collector.count()
            collected_count = articles_after - articles_before
            
            # Agent's response is just a summary for logging
            logger.debug(f"[AGENT] Response from {source.name}: {result[:200] if isinstance(result, str) else result}")
            logger.info(f"[AGENT] Collected {collected_count} articles from {source.name}")
            
            return collected_count
            
        except Exception as e:
            logger.error(f"[AGENT] Error collecting from source {source.name}: {e}")
            return 0
    
    async def process(self, inputs: List[ArticleSource]) -> List[Article]:
        """Collect articles from sources using appropriate method based on scraper_type.
        
        Args:
            inputs: List of article sources to scrape
            
        Returns:
            List of collected articles
        """
        # Separate RSS and non-RSS sources
        rss_sources = [s for s in inputs if s.scraper_type.lower() == 'rss']
        agent_sources = [s for s in inputs if s.scraper_type.lower() != 'rss']
        
        total_collected = 0
        
        # Process RSS sources concurrently (they're fast and non-LLM)
        if rss_sources:
            logger.info(f"[RSS] Processing {len(rss_sources)} RSS sources concurrently...")
            rss_tasks = [self._collect_from_rss(source) for source in rss_sources]
            rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)
            
            # Count successful RSS collections
            for source, result in zip(rss_sources, rss_results):
                if isinstance(result, int):
                    total_collected += result
                else:
                    logger.error(f"[RSS] Error collecting from {source.name}: {result}")
        
        # Process agent-based sources sequentially (they use LLM and are expensive)
        if agent_sources:
            logger.info(f"[AGENT] Processing {len(agent_sources)} agent sources sequentially...")
            for source in agent_sources:
                try:
                    count = await self._collect_from_web_agent(source)
                    total_collected += count
                except Exception as e:
                    logger.error(f"[AGENT] Error collecting from {source.name}: {e}")
                    continue
        
        # Get all collected articles from the collector
        all_articles = self.collector.get_all()
        logger.info(f"ArticleCollectionStage collected {len(all_articles)} total articles ({total_collected} new)")
        return all_articles
