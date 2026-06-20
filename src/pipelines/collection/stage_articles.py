"""Article collection stage for Question Pipeline."""

import asyncio
from typing import List, Optional, Dict, Union
from datetime import datetime
from pydantic import BaseModel

from src.pipelines.base import PipelineStage, PipelineStageResult
from src.domain.models import Article
from src.agents.factory import AgentFactory
from src.tools import ArticleCollectorTool, RssFetchTool
from src.core.collectors import ResultCollector
from src.pipelines.prompts import article_collection as article_collection_prompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class ArticleSource(BaseModel):
    """Configuration for an article source."""

    name: str
    url: str
    scraper_type: str  # "rss", "web", "api"
    domain: str  # Domain category for articles from this source
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

    def __init__(
        self, config: ArticleCollectionConfig, db_path: str = "worldreasoner.db"
    ):
        """Initialize article collection stage.

        Args:
            config: Article collection configuration
            db_path: Path to database for cross-run deduplication
        """
        super().__init__(name="ArticleCollection", config=config)

        # Create result collector for articles
        self.collector = ResultCollector[Article]()

        # Create ArticleCollectorTool with collector and database for deduplication
        self.article_tool = ArticleCollectorTool(
            db_path=db_path, collector=self.collector
        )
        # RSS fetch tool for direct RSS ingestion
        self.rss_tool = RssFetchTool()

        # Create WebAgent using factory
        self.web_agent = AgentFactory.create_web_agent(tools=[self.article_tool])


        # Usage tracking
        self.usage_tracker = UsageTracker()

        # Category filter (set during execute)
        self._category_filter = None

    async def execute(
        self,
        inputs: List[ArticleSource],
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
    ) -> PipelineStageResult[Article]:
        """Execute article collection with optional category filtering.

        Args:
            inputs: List of article sources to scrape
            category_filter: Optional dict mapping categories to number needed

        Returns:
            PipelineStageResult with collected articles
        """
        # Store category filter for use in processing
        self._category_filter = category_filter
        logger.debug(
            f"ArticleCollectionStage.execute() received category_filter: {category_filter}"
        )

        # If a dict of category gaps is provided, prefer its keys as the
        # active domains so prompts and downstream filtering reflect the
        # actual missing categories (not the original full domain list).
        if isinstance(category_filter, dict):
            try:
                self.config.domains = list(category_filter.keys())
            except Exception:
                # Be defensive: if something goes wrong, keep existing domains
                logger.debug(
                    "Failed to set domains from category_filter; using existing domains"
                )

        # Call parent execute method
        return await super().execute(inputs)

    async def _fetch_rss_item_async(self, item: dict, source: ArticleSource) -> bool:
        """Fetch a single RSS item asynchronously.

        Args:
            item: RSS feed item with title, link, published
            source: Article source configuration

        Returns:
            True if successfully collected, False otherwise
        """
        try:
            link = item.get("link") or item.get("url")
            if not link:
                logger.warning("[RSS] Item missing link, skipping")
                return False

            title = item.get("title", "")
            published = item.get("published", None)
            author = item.get("author", "")

            # Fetch full article content (runs in executor to not block)
            # Note: article_tool.forward is synchronous, but we run it in executor
            # Use lambda to pass keyword arguments correctly
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(
                None,
                lambda: self.article_tool.forward(
                    url=link,
                    title=title,
                    source=source.name,
                    domain=source.domain,  # Use actual domain from source config
                    published_date=published,
                    author=author,
                ),
            )

            # forward() returns an ArticleOutput even when it could not store
            # the article (web fetch failed, content too short, duplicate).
            # Only count it as collected if it was actually stored.
            status = getattr(summary, "status", "") or ""
            if status.startswith("error") or status.startswith("duplicate"):
                logger.info(
                    f"[RSS] Not collected ({status}): {item.get('link', 'unknown')}"
                )
                return False

            logger.debug(f"[RSS] Collected: {summary}")
            return True

        except Exception as e:
            logger.error(
                f"[RSS] Failed to collect item from {item.get('link', 'unknown')}: {e}"
            )
            return False

    async def _collect_from_rss(self, source: ArticleSource) -> int:
        """Collect articles from RSS feed source using async fetching.

        Args:
            source: RSS article source

        Returns:
            Number of articles collected
        """
        logger.debug(f"[RSS] Fetching feed: {source.name} -> {source.url}")

        try:
            # Fetch RSS feed (synchronous, but fast)
            rss_resp = self.rss_tool.forward(
                feed_url=source.url, max_items=self.config.max_articles_per_source or 5
            )

            # rss_resp is already an RssFetchOutput object, not a JSON string.
            # No need to parse it.
            rss_data = rss_resp

            if rss_data.total_items == 0:
                logger.warning(f"[RSS] No items returned for {source.name}")
                return 0

            # Convert Pydantic items to dicts for _fetch_rss_item_async
            # Using model_dump() for Pydantic v2 compatibility (or .dict() if needed)
            items = []
            for item in rss_data.items:
                try:
                    items.append(item.model_dump())
                except AttributeError:
                    # Fallback for Pydantic v1
                    items.append(item.dict())

            logger.info(f"[RSS] Feed returned {len(items)} items for {source.name}")

            # Fetch all items concurrently using asyncio.gather
            logger.debug(f"[RSS] Fetching {len(items)} items concurrently...")
            tasks = [self._fetch_rss_item_async(item, source) for item in items]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Count successful fetches (ignore exceptions)
            collected_count = sum(1 for r in results if r is True)

            logger.info(
                f"[RSS] Successfully collected {collected_count}/{len(items)} articles from {source.name}"
            )
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

            # Build domain context from category filter if provided
            domain_context = ""
            logger.debug(
                f"_collect_from_web_agent: self._category_filter = {self._category_filter}"
            )
            if self._category_filter is not None:
                if isinstance(self._category_filter, dict):
                    if self._category_filter:  # Non-empty dict
                        # Build specific context with gap amounts
                        gap_parts = []
                        for category, needed in self._category_filter.items():
                            gap_parts.append(f"{needed} more in {category}")
                        domain_context = f" We need: {', '.join(gap_parts)}."
                        logger.debug(
                            f"Using category gaps for domain context: {list(self._category_filter.keys())}"
                        )
                    else:
                        logger.debug(
                            "Empty category_filter dict - no domain context needed"
                        )
                    # else: empty dict means no specific gaps, skip domain context
                elif self._category_filter:  # Non-empty list
                    # Fallback for list format
                    domain_context = f" Focus on topics related to: {', '.join(self._category_filter)}."
                    logger.debug(
                        f"Using category list for domain context: {self._category_filter}"
                    )
            elif self.config.domains:
                # Only use config.domains if no category_filter was provided at all
                logger.warning(
                    f"No category_filter provided, falling back to ALL config.domains: {self.config.domains}"
                )
                domain_context = (
                    f" Focus on topics related to: {', '.join(self.config.domains)}."
                )
            else:
                logger.debug("No domain context available")

            # Get instruction from prompts module
            instruction = article_collection_prompts.get_instruction(
                current_date=current_date,
                source_name=source.name,
                days_back=days_back,
                max_articles=max_articles,
                domain_context=domain_context,
            )

            # Track articles before agent run
            articles_before = self.collector.count()

            # Run the agent with the instruction
            logger.debug(f"[AGENT] Running agent for: {source.name}")
            result = self.web_agent.run(instruction)

            # Track token usage
            usage_metrics = self.web_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context=f"ArticleCollection - {source.name}")

            # Calculate articles collected
            articles_after = self.collector.count()
            collected_count = articles_after - articles_before

            # Agent's response is just a summary for logging
            logger.debug(
                f"[AGENT] Response from {source.name}: {result[:200] if isinstance(result, str) else result}"
            )
            logger.info(
                f"[AGENT] Collected {collected_count} articles from {source.name}"
            )

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
        rss_sources = [s for s in inputs if s.scraper_type.lower() == "rss"]
        agent_sources = [s for s in inputs if s.scraper_type.lower() != "rss"]

        total_collected = 0

        # Process RSS sources concurrently (they're fast and non-LLM)
        if rss_sources:
            logger.info(
                f"[RSS] Processing {len(rss_sources)} RSS sources concurrently..."
            )
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
            logger.info(
                f"[AGENT] Processing {len(agent_sources)} agent sources sequentially..."
            )
            for source in agent_sources:
                try:
                    count = await self._collect_from_web_agent(source)
                    total_collected += count
                except Exception as e:
                    logger.error(f"[AGENT] Error collecting from {source.name}: {e}")
                    continue

        # Get all collected articles from the collector
        all_articles = self.collector.get_all()
        logger.info(
            f"ArticleCollectionStage collected {len(all_articles)} total articles ({total_collected} new)"
        )

        # Log usage summary for this stage
        if self.usage_tracker.total_calls > 0:
            self.usage_tracker.log_summary(context="ArticleCollection")

        return all_articles
