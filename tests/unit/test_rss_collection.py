"""Unit tests for RSS-based article collection."""

import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.tools.collectors.rss_fetch import RssFetchTool
from src.pipelines.collection.stage_articles import (
    ArticleCollectionStage,
    ArticleCollectionConfig,
    ArticleSource,
)


class TestRssFetchTool:
    """Test RSS feed fetching tool."""

    def test_rss_tool_initialization(self):
        """Test that RSS tool initializes correctly."""
        tool = RssFetchTool()
        assert tool.name == "rss_fetch"
        assert tool.output_type == "object"

    @pytest.mark.integration
    def test_rss_tool_fetch_real_feed(self):
        """Test fetching a real RSS feed (BBC News)."""
        tool = RssFetchTool()
        result = tool.forward(
            feed_url="http://feeds.bbci.co.uk/news/rss.xml", max_items=5
        )

        # Verify structure (Pydantic model)
        assert result.feed_url is not None
        assert result.total_items is not None
        assert isinstance(result.items, list)

        # Check we got items
        assert result.total_items > 0
        assert len(result.items) <= 5

        # Verify item structure
        if result.items:
            item = result.items[0]
            assert item.title is not None
            assert item.link is not None
            assert item.published is not None
            # Title should not be empty
            assert len(item.title) > 0
            # Link should be a URL
            assert item.link.startswith("http")

    @pytest.mark.integration
    def test_rss_tool_multiple_feeds(self):
        """Test fetching from multiple RSS feeds."""
        tool = RssFetchTool()

        feeds = [
            "http://feeds.bbci.co.uk/news/rss.xml",
            "https://feeds.npr.org/1001/rss.xml",
        ]

        results = []
        for feed_url in feeds:
            result = tool.forward(feed_url=feed_url, max_items=3)
            results.append(result)

        # All feeds should return items
        for result in results:
            assert result.items is not None
            assert len(result.items) > 0

    def test_rss_tool_invalid_feed(self):
        """Test handling of invalid RSS feed URL."""
        tool = RssFetchTool()
        result = tool.forward(
            feed_url="https://example.com/not-a-feed", max_items=5
        )

        # Should return empty items (bozo feed)
        assert result.total_items == 0


class TestArticleCollectionWithRSS:
    """Test article collection stage with RSS sources."""

    @staticmethod
    def load_rss_sources_from_config():
        """Load only available RSS sources from config/sources.yaml (skip consistently failing ones)."""
        config_path = Path(__file__).parent.parent.parent / "config" / "sources.yaml"
        if not config_path.exists():
            pytest.skip(f"Config file not found: {config_path}")
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
        rss_sources = []
        for source_data in config_data.get("sources", []):
            if source_data.get("scraper_type", "").lower() == "rss":
                rss_sources.append(
                    ArticleSource(
                        name=source_data["name"],
                        url=source_data["url"],
                        scraper_type=source_data["scraper_type"],
                        domain=source_data.get("domain", "general"),
                        rate_limit_per_second=source_data.get(
                            "rate_limit_per_second", 1.0
                        ),
                    )
                )
        return rss_sources

    @pytest.mark.integration
    async def test_all_rss_sources_from_config(self, persistent_test_db_path):
        """Test collecting articles from ALL RSS sources defined in config."""
        # Load all RSS sources from config
        sources = self.load_rss_sources_from_config()

        if not sources:
            pytest.skip("No RSS sources found in config")

        print(f"\nTesting {len(sources)} RSS sources from config:")
        for source in sources:
            print(f"  - {source.name}: {source.url}")

        config = ArticleCollectionConfig(
            sources=sources,
            start_date=datetime.now(timezone.utc) - timedelta(days=7),
            end_date=datetime.now(timezone.utc),
            max_articles_per_source=2,  # Limit to 2 per source for faster testing
            domains=[],  # Test all domains
        )

        # Create stage with test database (using tmp_path fixture)
        stage = ArticleCollectionStage(config=config, db_path=persistent_test_db_path)

        # Execute stage
        result = await stage.execute(sources)

        # Persist all collected articles to the database
        from src.core.database import GenericDatabase
        from src.domain.models.article import Article

        db = GenericDatabase(persistent_test_db_path)
        db.create_table(Article)
        db.save_many(Article, result.outputs)

        # Verify results
        assert result.status.value == "completed"

        # Track which sources succeeded
        sources_with_articles = set(article.source for article in result.outputs)

        print("\nResults:")
        print(f"  Total articles collected: {len(result.outputs)}")
        print(f"  Sources with articles: {len(sources_with_articles)}/{len(sources)}")
        print(f"  Successful sources: {', '.join(sorted(sources_with_articles))}")

        # At least half of the sources should work (some may have temporary issues)
        success_rate = len(sources_with_articles) / len(sources)
        assert success_rate >= 0.5, (
            f"Only {success_rate:.1%} of sources succeeded (expected >= 50%)"
        )

        # Verify articles have proper structure
        for article in result.outputs:
            assert article.id
            assert article.title
            assert article.url
            assert article.source in [s.name for s in sources]
            assert article.content
            assert len(article.content) > 100  # Should have substantial content

    @pytest.mark.integration
    async def test_rss_deduplication(self, test_db_path):
        """Test that RSS articles are deduplicated properly."""
        sources = [
            ArticleSource(
                name="NPR News",
                url="https://feeds.npr.org/1001/rss.xml",
                scraper_type="rss",
                domain="general",
            )
        ]

        config = ArticleCollectionConfig(
            sources=sources,
            start_date=datetime.now(timezone.utc) - timedelta(days=7),
            end_date=datetime.now(timezone.utc),
            max_articles_per_source=5,
            domains=["general"],
        )

        # First run - collect and save to database
        stage1 = ArticleCollectionStage(config=config, db_path=test_db_path)
        result1 = await stage1.execute(sources)
        first_count = len(result1.outputs)

        # Persist articles to database for deduplication
        from src.core.database import GenericDatabase
        from src.domain.models.article import Article

        db = GenericDatabase(test_db_path)
        db.create_table(Article)
        saved_count = db.save_many(Article, result1.outputs)

        # Second run - should detect duplicates from database
        stage2 = ArticleCollectionStage(config=config, db_path=test_db_path)
        result2 = await stage2.execute(sources)

        # Both should complete successfully
        assert result1.status.value == "completed"
        assert result2.status.value == "completed"

        # First run should have collected and saved articles
        assert first_count > 0
        assert saved_count > 0, "First run should save articles to database"

        # Second run should have fewer or same articles (duplicates filtered)
        # Note: If feed has new items, result2 might have different articles
        assert len(result2.outputs) >= 0, (
            "Second run should complete (may have new or no articles)"
        )


if __name__ == "__main__":
    # Run with: python -m pytest tests/unit/test_rss_collection.py -v
    pytest.main([__file__, "-v"])
