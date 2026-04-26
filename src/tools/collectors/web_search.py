from dotenv import load_dotenv
import os
import json
from typing import Optional, List, Dict, Any
import httpx
from smolagents.tools import Tool
from smolagents import WebSearchTool as SmolWebSearchTool

from src.utils.logging import logger

load_dotenv()

# Keep article collection timeout consistent across all ArticleCollector calls.
ARTICLE_COLLECT_TIMEOUT_SECONDS = 15


class WebSearchTool(Tool):
    """
    A unified web search tool that uses SearXNG if configured, otherwise falls back to default web search.

    If SEARXNG_BASE_URL is set in environment variables, this tool will use a SearXNG instance
    for privacy-focused meta-search. Otherwise, it uses the default smolagents WebSearchTool.
    """

    name: str = "WebSearchTool"
    description: str = (
        "Performs a web search using either SearXNG or default search. "
        "Returns search results formatted as markdown with titles, links, and descriptions.\n\n"
        "CUSTOM DATE RANGES:\n"
        "To define a custom date range, include search operators directly in your query string:\n"
        "  - after:YYYY-MM-DD  (e.g., after:2025-01-01)\n"
        "  - before:YYYY-MM-DD (e.g., before:2025-12-31)\n"
        "  - Example: 'AI news after:2025-11-01 before:2025-11-30'"
    )

    is_initialized: bool = False

    inputs = {
        "query": {"type": "string", "description": "The search query string."},
        "categories": {
            "type": "string",
            "description": "Optional categories to search (e.g., 'general', 'news', 'images')",
            "nullable": True,
        },
        "language": {
            "type": "string",
            "description": "Optional language code (e.g., 'en', 'fr')",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "Optional page number for results (default: 1)",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(
        self,
        db_path: str = None,
        collector=None,
        question_id: Optional[str] = None,
        auto_collect_enabled: bool = False,
        max_auto_collect: int = 10,
        domain: str = "general",
    ):
        """Initialize WebSearchTool with optional auto-collect.

        Args:
            auto_collect_enabled: If True, automatically collect articles with publishedDate < question_resolution_date
            question_id, question_resolution_date: Required if auto_collect_enabled=True
            db, db_path, collector, domain, max_auto_collect: Passed to ArticleCollectorTool if enabled
        """
        # Initialize attributes that may be used later
        self.auto_collect_enabled = False
        self.question_id = question_id
        self.question = None
        self.question_resolution_date = None

        self.db = None
        if db_path:
            from src.core.database import GenericDatabase

            self.db = GenericDatabase(db_path)
        if self.db and question_id:
            from src.domain.models.question import Question

            self.question = self.db.get(Question, question_id)
            self.auto_collect_enabled = self.question is not None
            self.question_resolution_date = (
                self.question.resolution_date if self.question else None
            )

        self.max_auto_collect = max_auto_collect
        self.domain = domain

        # Initialize article collector if enabled
        if self.auto_collect_enabled:
            from src.tools.collectors.article_collector import ArticleCollectorTool

            self.article_collector = ArticleCollectorTool(
                db=self.db,
                db_path=db_path,
                collector=collector,
                question_id=self.question_id,
            )
            logger.info(
                f"Auto-collect enabled (question_id={question_id}, max={max_auto_collect})"
            )
        else:
            self.article_collector = None

        # Set up search backend
        self.searxng_base_url = os.getenv("SEARXNG_BASE_URL")
        self.use_searxng = bool(self.searxng_base_url)

        if self.use_searxng:
            logger.info(f"Using SearXNG at {self.searxng_base_url}")
            self.client = httpx.Client(
                base_url=self.searxng_base_url,
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
            )
        else:
            logger.info("Using default smolagents WebSearchTool")
            self.fallback_tool = SmolWebSearchTool()
            self.client = None

    def forward(
        self,
        query: str,
        categories: Optional[str] = None,
        language: Optional[str] = None,
        page: Optional[int] = 1,
    ) -> str:
        """
        Perform a web search using either SearXNG or the default search tool.

        Args:
            query: The search query string
            categories: Optional categories for SearXNG (ignored for default search)
            language: Optional language code for SearXNG (ignored for default search)
            page: Optional page number for SearXNG (ignored for default search)

        Returns:
            Search results as a string
        """
        if self.use_searxng:
            return self._search_with_searxng(query, categories, language, page)
        else:
            # Use the fallback tool, which only accepts query parameter
            return self.fallback_tool.forward(query=query)

    def _get_structured_results(
        self,
        query: str,
        categories: Optional[str] = None,
        language: Optional[str] = None,
        page: Optional[int] = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get structured search results before markdown formatting.

        This method provides programmatic access to search result metadata,
        including publishedDate when available from SearXNG.

        Args:
            query: The search query string
            categories: Optional categories for SearXNG
            language: Optional language code for SearXNG
            page: Optional page number for SearXNG

        Returns:
            List of result dicts with keys: title, url, content, engines, publishedDate
            publishedDate may be None if not available
            Empty list if search fails or using fallback tool
        """
        if not self.use_searxng:
            # Fallback tool doesn't provide structured results with publishedDate
            logger.warning("Fallback tool doesn't support structured results")
            return []

        try:
            params = {
                "q": query,
                "format": "json",
                "page": page or 1,
            }

            # Add optional parameters if provided
            if categories:
                params["categories"] = categories
            if language:
                params["language"] = language

            response = self.client.get("/search", params=params)

            # If JSON format is forbidden (403), fall back
            if response.status_code == 403:
                logger.warning(
                    "SearXNG JSON format restricted, no structured results available"
                )
                return []

            response.raise_for_status()

            # Parse and return structured results
            try:
                data = json.loads(response.text)
                results = data.get("results", [])

                # Build structured result list
                structured = []
                for result in results:
                    structured.append(
                        {
                            "title": result.get("title", "No title"),
                            "url": result.get("url", ""),
                            "content": result.get(
                                "content", "No description available"
                            ),
                            "engines": result.get("engines", []),
                            "publishedDate": result.get("publishedDate", None),
                        }
                    )
                return structured
            except json.JSONDecodeError:
                logger.error("Failed to parse SearXNG JSON response")
                return []

        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG returned status {e.response.status_code}")
            return []
        except httpx.RequestError as e:
            logger.error(
                f"Failed to connect to SearXNG at {self.searxng_base_url}: {str(e)}"
            )
            return []
        except Exception as e:
            logger.error(f"Error querying SearXNG: {str(e)}")
            return []

    def _search_with_searxng(
        self,
        query: str,
        categories: Optional[str] = None,
        language: Optional[str] = None,
        page: Optional[int] = 1,
    ) -> str:
        """
        Perform a search using SearXNG instance.

        Args:
            query: The search query string
            categories: Optional categories to search
            language: Optional language code
            page: Optional page number

        Returns:
            Formatted markdown string with search results (+ collection summary if auto-collect enabled)
        """
        # Get structured results (DRY: reuse query logic)
        structured_results = self._get_structured_results(
            query, categories, language, page
        )

        # If no results (error or fallback), use fallback tool
        if not structured_results:
            if hasattr(self, "fallback_tool"):
                return self.fallback_tool.forward(query=query)
            else:
                self.fallback_tool = SmolWebSearchTool()
                return self.fallback_tool.forward(query=query)

        # Format structured results as markdown
        search_results = self._format_search_results_from_list(
            query, structured_results
        )

        # If auto-collect disabled, return search results only
        if not self.auto_collect_enabled:
            return search_results

        # Auto-collect eligible articles
        collection_summary = self._auto_collect_articles(structured_results)

        # Append collection summary to search results
        return f"{search_results}\n\n{collection_summary}"

    def _format_search_results_from_list(
        self, query: str, results: List[Dict[str, Any]]
    ) -> str:
        """
        Format structured search results into a readable markdown string.

        Args:
            query: The search query
            results: List of structured result dicts

        Returns:
            Formatted markdown string with search results
        """
        if not results:
            return f"No results found for query: '{query}'"

        # Build formatted output
        output = [f"# Search Results for: {query}\n"]

        # Limit to top 10 results for readability
        for i, result in enumerate(results[:10], 1):
            title = result.get("title", "No title")
            url = result.get("url", "")
            content = result.get("content", "No description available")
            engines = result.get("engines", [])
            published_date = result.get("publishedDate", None)

            # Clean up content - remove extra whitespace and limit length
            content = " ".join(content.split())
            if len(content) > 200:
                content = content[:197] + "..."

            output.append(f"## {i}. {title}")
            output.append(f"**URL:** {url}")
            output.append(f"**Description:** {content}")
            if published_date:
                output.append(f"**Published Date:** {published_date}")

            if engines:
                output.append(f"**Sources:** {', '.join(engines)}")
            output.append("")  # Empty line for spacing

        return "\n".join(output)

    def _format_search_results(self, data: dict) -> str:
        """
        Format SearXNG JSON results into a readable markdown string.

        Args:
            data: Parsed JSON response from SearXNG

        Returns:
            Formatted markdown string with search results
        """
        query = data.get("query", "")
        results = data.get("results", [])

        # Convert to structured list format and reuse formatting logic (DRY)
        structured_results = []
        for result in results:
            structured_results.append(
                {
                    "title": result.get("title", "No title"),
                    "url": result.get("url", ""),
                    "content": result.get("content", "No description available"),
                    "engines": result.get("engines", []),
                    "publishedDate": result.get("publishedDate", None),
                }
            )

        return self._format_search_results_from_list(query, structured_results)

    def _auto_collect_articles(self, structured_results: List[Dict[str, Any]]) -> str:
        """Automatically collect articles that meet temporal criteria.

        Args:
            structured_results: List of structured search result dicts

        Returns:
            Brief summary of collection activity
        """
        # Safety check: ensure resolution date is set
        if not self.question_resolution_date:
            logger.warning("Auto-collect skipped: question_resolution_date is not set")
            return "\n---\n**Auto-collected 0 article(s)** (auto-collect disabled: no resolution date)"

        from src.utils.date_utils import parse_flexible_datetime
        import concurrent.futures

        collected = []
        skipped = {"no_date": 0, "after_resolution": 0, "error": 0, "timeout": 0}
        
        eligible_items = []

        for result in structured_results:
            if len(eligible_items) >= self.max_auto_collect:
                break

            url, title, published_date_str = (
                result.get("url"),
                result.get("title", ""),
                result.get("publishedDate"),
            )

            if not url or not published_date_str:
                if not published_date_str:
                    skipped["no_date"] += 1
                continue

            try:
                published_date = parse_flexible_datetime(published_date_str)

                # Normalize both datetimes for comparison (handle timezone-aware vs naive)
                # Convert both to naive UTC to avoid TypeError
                pub_dt = (
                    published_date.replace(tzinfo=None)
                    if published_date.tzinfo
                    else published_date
                )
                res_dt = (
                    self.question_resolution_date.replace(tzinfo=None)
                    if self.question_resolution_date.tzinfo
                    else self.question_resolution_date
                )

                if pub_dt >= res_dt:
                    skipped["after_resolution"] += 1
                    continue

                # Collect article
                engines = result.get("engines", [])
                source = (
                    engines[0]
                    if engines
                    else url.split("/")[2]
                    if "/" in url
                    else "Unknown"
                )

                eligible_items.append({
                    "url": url,
                    "title": title,
                    "source": source,
                    "published_date": published_date.isoformat(),
                    "domain": self.domain,
                    "author": None,
                })

            except Exception as e:
                logger.warning(f"Auto-collect validation skipped {url}: {type(e).__name__}: {e}")
                skipped["error"] += 1

        if eligible_items:
            def fetch_article(item):
                self.article_collector.forward(
                    url=item["url"],
                    title=item["title"],
                    source=item["source"],
                    published_date=item["published_date"],
                    domain=item["domain"],
                    author=item["author"],
                    timeout=ARTICLE_COLLECT_TIMEOUT_SECONDS,
                )
                return item["title"]

            # Execute concurrently with a timeout consistent with ArticleCollector fetch timeout.
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(eligible_items)) as executor:
                future_to_item = {executor.submit(fetch_article, item): item for item in eligible_items}
                
                done, not_done = concurrent.futures.wait(
                    future_to_item.keys(), timeout=float(ARTICLE_COLLECT_TIMEOUT_SECONDS)
                )
                
                for future in done:
                    item = future_to_item[future]
                    try:
                        title = future.result()
                        collected.append(title[:30] + "..." if len(title) > 30 else title)
                    except Exception as e:
                        logger.warning(f"Auto-collect failed for {item['url']}: {type(e).__name__}: {e}")
                        skipped["error"] += 1
                        
                for future in not_done:
                    item = future_to_item[future]
                    logger.warning(f"Auto-collect timed out for {item['url']}")
                    skipped["timeout"] += 1

        # Build concise summary
        total_skipped = sum(skipped.values())
        summary = f"\n---\n**Auto-collected {len(collected)} article(s):**"
        if collected:
            summary += "\n" + "\n".join([f"- {t}" for t in collected])

        if total_skipped > 0:
            details = [
                f"{v} {k.replace('_', ' ')}" for k, v in skipped.items() if v > 0
            ]
            summary += f"\n\n(Skipped {total_skipped}: {', '.join(details)}. **Please manually collect relevant articles if they were skipped.**)"

        return summary

    def __del__(self):
        """Clean up HTTP client when tool is destroyed."""
        if hasattr(self, "client") and self.client:
            try:
                self.client.close()
            except Exception:
                pass
