"""Article collection tool using web search for scraping."""

import hashlib
import json
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from smolagents import Tool, VisitWebpageTool
from src.utils.config import load_config
from src.data.models import Article


class ArticleCollectorTool(Tool):
    """Fetches and stores article data from URLs into Article objects.
    
    This tool helps the agent:
    1. Internally fetch full article content from a URL (using VisitWebpageTool)
    2. Convert content into structured Article format
    3. Generate unique article IDs
    4. Handle deduplication via content hashing
    5. Calculate metadata (word count, reading time, etc.)
    
    IMPORTANT: This tool ONLY needs the URL and metadata.
    The agent should use web_search to find article URLs, then pass ONLY the URL
    to this tool. This tool will internally fetch the full content, avoiding
    expensive token usage from passing large article text through the LLM.
    """
    
    name = "article_collector"
    description = """Fetches and stores article data from a URL.
    
    Use this tool AFTER you've found article URLs using web_search.
    Pass ONLY the URL and metadata (title, source, etc.) - do NOT pass article content.
    This tool will internally fetch the full article content to save tokens.
    
    Args:
        url (str): Source URL to fetch the article from
        title (str): Article headline/title from search results
        source (str): Publication name (e.g., "TechCrunch", "BBC News")
        domain (str): Article domain category - one of: finance, politics, tech, health, climate, general
        published_date (str, optional): Publication date in ISO format if available
        author (str, optional): Author name if available
    
    Returns:
        str: JSON string with the created Article object including generated ID and metadata
    """
    
    inputs = {
        "url": {"type": "string", "description": "Source URL to fetch the article from"},
        "title": {"type": "string", "description": "Article headline/title from search results"},
        "source": {"type": "string", "description": "Publication name"},
        "domain": {"type": "string", "description": "Domain category (finance|politics|tech|health|climate|general)", "nullable": True},
        "published_date": {"type": "string", "description": "Publication date (ISO format)", "nullable": True},
        "author": {"type": "string", "description": "Author name", "nullable": True},
    }
    output_type = "string"  # JSON string
    
    def __init__(self):
        """Initialize the article collector."""
        super().__init__()
        self.config = None
        self.seen_hashes = set()  # For deduplication
        self.web_visitor = VisitWebpageTool()  # Internal tool for fetching content
        self.collected_articles = []  # Store full Article objects internally
    
    def setup(self):
        """Load configuration (called on first use)."""
        if self.config is None:
            self.config = load_config()
    
    def forward(
        self,
        url: str,
        title: str,
        source: str,
        domain: str = "general",
        published_date: Optional[str] = None,
        author: Optional[str] = None
    ) -> str:
        """Fetch article content from URL and store as structured JSON.
        
        Args:
            url: Source URL to fetch article from
            title: Article headline from search results
            source: Publication name
            domain: Article domain category
            published_date: Optional publication date (ISO format)
            author: Optional author name
            
        Returns:
            JSON string of Article object
        """
        # Internally fetch the full article content
        # This avoids passing large content through the LLM
        try:
            content = self.web_visitor.forward(url)
            if not content or len(content.strip()) < 100:
                return json.dumps({"error": f"Failed to fetch content from {url}", "url": url})
        except Exception as e:
            return json.dumps({"error": f"Error fetching URL: {str(e)}", "url": url})
        
        # Parse published date or use current time
        if published_date:
            try:
                pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
            except:
                pub_date = datetime.now(timezone.utc)
        else:
            pub_date = datetime.now(timezone.utc)
        
        # Check for duplicate content
        content_hash = self._compute_content_hash(content)
        if content_hash in self.seen_hashes:
            return json.dumps({"error": "Duplicate article detected", "hash": content_hash})
        
        self.seen_hashes.add(content_hash)
        
        # Generate unique ID
        article_id = self._generate_article_id(domain, pub_date, len(self.seen_hashes))
        
        # Extract domain from URL if not provided
        parsed_url = urlparse(url)
        source_domain = parsed_url.netloc
        
        # Create Article object
        article = Article(
            id=article_id,
            title=title,
            content=content,
            url=url,
            source=source,
            author=author or "Unknown",
            published_date=pub_date,
            domain=domain,
            tags=[domain, source_domain],
            is_synthetic=False,
            language='en',
        )
        
        # Calculate metadata
        article.word_count = len(article.content.split())
        article.reading_time_minutes = max(1, article.word_count // 200)
        
        # Store full article internally for later pipeline stages
        self.collected_articles.append(article)
        
        # Convert to JSON and return a SUMMARY to save tokens
        # Return only metadata, NOT the full content
        summary = {
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "source": article.source,
            "author": article.author,
            "published_date": article.published_date.isoformat(),
            "domain": article.domain,
            "word_count": article.word_count,
            "reading_time_minutes": article.reading_time_minutes,
            "content_preview": article.content[:200] + "..." if len(article.content) > 200 else article.content,
            "status": "stored"
        }
        
        return json.dumps(summary, indent=2, default=str)
    
    def _generate_article_id(self, domain: str, published_date: datetime, counter: int) -> str:
        """Generate unique article ID."""
        date_str = published_date.strftime('%Y%m%d')
        return f"art_{domain}_{date_str}_{counter+1:03d}"
    
    def _compute_content_hash(self, content: str) -> str:
        """Compute SHA-256 hash of normalized content for deduplication.
        
        Args:
            content: Article content to hash
            
        Returns:
            Hexadecimal hash string
        """
        normalized = ' '.join(content.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def reset_deduplication(self):
        """Reset the deduplication cache."""
        self.seen_hashes.clear()
