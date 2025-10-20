"""Advanced web fetching tool using crawl4ai for robust content extraction."""

import asyncio
import json
from typing import Optional, Dict, Any
from smolagents import Tool


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
        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)", "nullable": True},
    }
    output_type = "string"  # JSON string
    
    def __init__(self):
        """Initialize the web fetch tool."""
        super().__init__()
        self._crawler = None
        
    async def _fetch_async(
        self,
        url: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Async implementation of web fetching.
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            Dictionary with fetched content and metadata
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
            
            # Configure browser (headless, timeout)
            browser_config = BrowserConfig(
                headless=True,
                verbose=False
            )
            
            # Configure crawler run (bypass cache, set timeout)
            crawler_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout * 1000,  # Convert to milliseconds
            )
            
            # Fetch the page using context manager
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url, config=crawler_config)
            
            if not result.success:
                return {
                    "url": url,
                    "success": False,
                    "error": result.error_message or "Failed to fetch page"
                }
            
            # Extract metadata
            metadata = {}
            if result.metadata:
                metadata = {
                    "description": result.metadata.get("description", ""),
                    "keywords": result.metadata.get("keywords", ""),
                    "author": result.metadata.get("author", ""),
                }
            
            # Build response
            response = {
                "url": result.url,
                "title": result.metadata.get("title", "") if result.metadata else "",
                "markdown": result.markdown or "",
                "metadata": metadata,
                "success": True,
            }
            
            return response
            
        except ImportError:
            return {
                "url": url,
                "success": False,
                "error": "crawl4ai is not installed. Install it with: pip install crawl4ai"
            }
        except Exception as e:
            return {
                "url": url,
                "success": False,
                "error": f"Error fetching URL: {str(e)}"
            }
    
    def forward(
        self,
        url: str,
        timeout: int = 30
    ) -> str:
        """Fetch web page content.
        
        Args:
            url: URL to fetch
            timeout: Maximum time to wait in seconds
            
        Returns:
            JSON string with fetched content
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
        
        return json.dumps(result, indent=2)
    
    async def forward_async(
        self,
        url: str,
        timeout: int = 30
    ) -> str:
        """Async version of forward for use in async contexts.
        
        Args:
            url: URL to fetch
            timeout: Maximum time to wait in seconds
            
        Returns:
            JSON string with fetched content
        """
        result = await self._fetch_async(url, timeout)
        return json.dumps(result, indent=2)

