"""Advanced web fetching tool using crawl4ai for robust content extraction."""

import asyncio
import json
from typing import Dict, Any
from smolagents import Tool
from src.utils.schema_helper import pydantic_to_output_schema
from src.tools.output_models import WebFetchOutput


class WebFetchTool(Tool):
    """Fetch and extract clean content from web pages using crawl4ai.

    This tool provides advanced web scraping capabilities:
    - JavaScript rendering support
    - Clean markdown extraction
    - Metadata extraction (title, description, etc.)
    - Better handling of dynamic content than simple HTTP requests

    Uses crawl4ai for robust content extraction with proper handling of:
    - SPAs (Single Page Applications)
    - Dynamic content loading
    - Content cleaning and formatting
    """

    name = "web_fetch"
    description = """Fetch and extract clean content from a web page URL.
    
    This tool uses advanced web scraping to handle modern websites with JavaScript.
    It returns clean markdown content suitable for LLM processing.
    
    IMPORTANT: this tool doesn't automatically store articles to the database.
    Args:
        url (str): The URL to fetch content from
        timeout (int, optional): Maximum time to wait in seconds. Default: 30
    
    Returns:
        str: JSON string containing:
            - url: The fetched URL
            - title: Page title
            - markdown: Clean markdown content
            - metadata: Additional metadata (description, etc.)
            - success: Boolean indicating if fetch was successful
            - error: Error message if fetch failed
    """

    inputs = {
        "url": {"type": "string", "description": "URL to fetch content from"},
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default: 30)",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(WebFetchOutput)

    def __init__(self):
        """Initialize the web fetch tool."""
        super().__init__()
        self._crawler = None

    async def _fast_fetch_async(self, url: str, timeout: int = 10) -> Dict[str, Any]:
        """Try a fast fetch with AI-friendly headers.
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            Dictionary with content if successful, else None
        """
        try:
            import httpx
            headers = {
                "Accept": "text/markdown, text/plain, */*",
                "User-Agent": "MyAI-Agent/1.0 (Hybrid Fetch Controller)",
            }
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                
                # If we got markdown back directly, great!
                content_type = response.headers.get("Content-Type", "").lower()
                if response.status_code == 200 and ("markdown" in content_type or "text/plain" in content_type):
                    return {
                        "url": str(response.url),
                        "title": "", # Hard to get without parsing
                        "markdown": response.text,
                        "metadata": {"method": "fast_fetch_markdown"},
                        "success": True,
                    }
                
                # If it's HTML, we should check if it's a simple page or a wall
                # For now, if we get HTML, we might still prefer crawl4ai for cleaning
                return None
        except Exception:
            return None

    async def _fetch_async(self, url: str, timeout: int = 30) -> Dict[str, Any]:
        """Async implementation of web fetching with hybrid strategy.

        Args:
            url: URL to fetch
            timeout: Timeout in seconds

        Returns:
            Dictionary with fetched content and metadata
        """
        # 1. Try Fast Fetch first (AI-friendly)
        fast_result = await self._fast_fetch_async(url, timeout=min(timeout, 10))
        if fast_result:
            return fast_result

        # 2. Fallback to Robust Fetch with crawl4ai
        try:
            from crawl4ai import (
                AsyncWebCrawler,
                BrowserConfig,
                CrawlerRunConfig,
                CacheMode,
            )
            from crawl4ai.content_filter_strategy import PruningContentFilter
            from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

            # Configure browser with stealth and random UA for robust fallback
            browser_config = BrowserConfig(
                headless=True, 
                verbose=False,
                user_agent_mode="random",
                enable_stealth=True
            )

            # Use PruningContentFilter to strip noise and get clean fit_markdown
            md_generator = DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(threshold=0.45, threshold_type="fixed")
            )

            # JS to bypass common consent walls (like Yahoo)
            js_bypass = """
            const bypassConsent = () => {
                const agreeButtons = [
                    'button[name="agree"]', // Yahoo
                    '#L2AGLb', // Google
                    '.consent-give', // Common
                    'button:contains("Accept all")',
                    'button:contains("Agree")'
                ];
                for (const selector of agreeButtons) {
                    try {
                        const btn = document.querySelector(selector);
                        if (btn) {
                            console.log("Found consent button: " + selector);
                            btn.click();
                            return true;
                        }
                    } catch (e) {}
                }
                return false;
            };
            bypassConsent();
            """

            # Configure crawler run (bypass cache, set timeout, magic mode)
            crawler_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout * 1000,
                markdown_generator=md_generator,
                magic=True,
                js_code=js_bypass,
                wait_for="body:not(.wizard):not(.consent-page)",
                delay_before_return_html=2.0
            )

            # Fetch the page using context manager
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url, config=crawler_config)

            if not result.success:
                return {
                    "url": url,
                    "success": False,
                    "error": result.error_message or "Failed to fetch page",
                }

            # Extract metadata
            metadata = {}
            if result.metadata:
                metadata = {
                    "description": result.metadata.get("description", ""),
                    "keywords": result.metadata.get("keywords", ""),
                    "author": result.metadata.get("author", ""),
                    "method": "robust_fetch_crawl4ai"
                }

            # Extract clean markdown: prefer fit_markdown (noise-filtered), fall back to raw_markdown
            md = result.markdown
            if hasattr(md, "fit_markdown") and md.fit_markdown:
                clean_markdown = md.fit_markdown
            elif hasattr(md, "raw_markdown") and md.raw_markdown:
                clean_markdown = md.raw_markdown
            else:
                clean_markdown = str(md) if md else ""

            # Build response
            response = {
                "url": result.url,
                "title": result.metadata.get("title", "") if result.metadata else "",
                "markdown": clean_markdown,
                "metadata": metadata,
                "success": True,
            }

            return response

        except ImportError:
            return {
                "url": url,
                "success": False,
                "error": "crawl4ai is not installed. Install it with: pip install crawl4ai",
            }
        except Exception as e:
            return {
                "url": url,
                "success": False,
                "error": f"Error fetching URL: {str(e)}",
            }

    def forward(self, url: str, timeout: int = 30) -> WebFetchOutput:
        """Fetch web page content.

        Args:
            url: URL to fetch
            timeout: Maximum time to wait in seconds

        Returns:
            WebFetchOutput Pydantic model with fetched content
        """
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - run coroutine in a new thread with its own event loop
            import concurrent.futures

            def run_in_thread():
                """Run the async function in a new thread with a new event loop."""
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self._fetch_async(url, timeout))
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                result = future.result()
        except RuntimeError:
            # No event loop running, safe to create one
            result = asyncio.run(self._fetch_async(url, timeout))

        # Convert dict result to Pydantic model
        return WebFetchOutput(
            url=result.get("url", url),
            title=result.get("title", ""),
            content=result.get("markdown", "") or "",
            metadata=result.get("metadata", {}),
            success=result.get("success", False),
            error=result.get("error"),
        )

    async def forward_async(self, url: str, timeout: int = 30) -> WebFetchOutput:
        """Async version of forward for use in async contexts.

        Args:
            url: URL to fetch
            timeout: Maximum time to wait in seconds

        Returns:
            WebFetchOutput Pydantic model with fetched content
        """
        result = await self._fetch_async(url, timeout)
        # Convert dict result to Pydantic model
        return WebFetchOutput(
            url=result.get("url", url),
            title=result.get("title", ""),
            content=result.get("markdown", "") or "",
            metadata=result.get("metadata", {}),
            success=result.get("success", False),
            error=result.get("error"),
        )
