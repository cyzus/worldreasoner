"""Simple RSS fetch tool using feedparser.

This tool parses RSS/Atom feeds and returns a list of items with title, link,
published date, and summary/content. It keeps the output compact (JSON string)
so it can be passed to ArticleCollectorTool which will fetch full content.
"""

import feedparser

from typing import List
from datetime import datetime

from smolagents import Tool
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import RssFetchOutput, RssFeedItem


class RssFetchTool(Tool):
    name = "rss_fetch"
    description = (
        "Fetch items from an RSS/Atom feed URL and return item metadata as JSON"
    )

    inputs = {
        "feed_url": {"type": "string", "description": "RSS/Atom feed URL"},
        "max_items": {
            "type": "integer",
            "description": "Maximum items to return",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(RssFetchOutput)

    def __init__(self):
        super().__init__()

    def forward(self, feed_url: str, max_items: int = 10) -> RssFetchOutput:
        """Fetch and parse feed_url and return RSS feed output.

        Each item contains: title, link, published (ISO), summary.
        """
        parsed = feedparser.parse(feed_url)
        if parsed.bozo:
            # bozo indicates parse issue; return empty output with error info
            # Note: Returning RssFetchOutput even on error to maintain type consistency
            return RssFetchOutput(
                feed_url=feed_url,
                total_items=0,
                items=[],
            )

        items: List[RssFeedItem] = []
        for entry in parsed.entries[: max_items or 10]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            # Try to convert to ISO format if possible
            published_iso = ""
            if published:
                try:
                    # feedparser gives a struct_time in published_parsed
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published_iso = datetime(
                            *entry.published_parsed[:6]
                        ).isoformat()
                    else:
                        published_iso = datetime.fromisoformat(published).isoformat()
                except Exception:
                    published_iso = published

            summary = entry.get(
                "summary", entry.get("content", [{"value": ""}])[0].get("value", "")
            )

            items.append(
                RssFeedItem(
                    title=title,
                    link=link,
                    published=published_iso,
                    summary=summary,
                )
            )

        return RssFetchOutput(
            feed_url=feed_url,
            total_items=len(items),
            items=items,
        )
